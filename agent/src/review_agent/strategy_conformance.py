"""Pure conformance core: deterministic per-rule status + run severity for an
autonomous_loop run, judged against the DECLARED, point-in-time strategy.

No I/O here — the tool assembles a plain-dict `context` and calls classify_conformance.
"""
from datetime import datetime, timedelta

# Effective-dated declared rule-set, newest-first. The prose-only advisory thresholds
# that have no canonical machine-readable store live here; git history IS the audit
# trail. PROPOSAL-strategy-spec.md would promote this to a shared trader+reviewer spec.
STRATEGY_SPEC_VERSIONS: list[dict] = [
    {
        "effective_from": "2026-01-01",
        "min_hold_trading_days": 5,   # autonomy.py prompt: "minimum 5 trading day hold"
        "max_positions": 8,           # autonomy.py prompt: "5-8 positions max"
        "min_positions_soft": 5,      # soft floor (warn, not fail)
    },
]

# Rules verified deterministically from stored data in v1.
VERIFIED_RULES: set[str] = {
    "anti_churn", "position_count", "stops_present",
    "factor_weights_conformance", "regime_gate",
}
# Rules with no durably-persisted point-in-time input (v1 — see plan's v1 scoping).
UNVERIFIABLE_RULES: set[str] = {"risk_limit_leak", "sell_justification", "ai_soft_caps"}
KNOWN_STRATEGY_RULES: set[str] = VERIFIED_RULES | UNVERIFIABLE_RULES

_UNVERIFIABLE_REASON: dict[str, str] = {
    "risk_limit_leak": "Needs point-in-time equity / earnings dates not durably stored (v1 deferred).",
    "sell_justification": "factor_rankings stores only top_10; a dropped symbol's rank is unrecoverable.",
    "ai_soft_caps": "No AI-bubble flag or AI-symbol tagging is persisted per run.",
}

_SEVERITY_ORDER = {"pass": 0, "info": 1, "warn": 2, "fail": 3}


def _fact(rule: str, status: str, severity: str, detail: str, evidence: dict) -> dict:
    return {"rule": rule, "status": status, "severity": severity,
            "detail": detail, "evidence": evidence}


def resolve_spec(run_date: str) -> dict:
    """The declared rule-set in force on run_date (YYYY-MM-DD). Newest version whose
    effective_from <= run_date; falls back to the oldest version for earlier dates."""
    for v in STRATEGY_SPEC_VERSIONS:                 # newest-first
        if v["effective_from"] <= run_date:
            return {**v}
    return {**STRATEGY_SPEC_VERSIONS[-1]}


def run_severity(facts: list[dict]) -> str:
    """Run verdict severity = the worst rule severity (unverifiable rules are 'info')."""
    worst = "pass"
    for f in facts:
        if _SEVERITY_ORDER[f["severity"]] > _SEVERITY_ORDER[worst]:
            worst = f["severity"]
    return worst


def _dtp(s):
    try:
        return datetime.fromisoformat(str(s))
    except (TypeError, ValueError):
        return None


def _f(x) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def trading_days_between(start_iso: str, end_iso: str) -> int:
    """Weekday count strictly after start through end (holidays ignored — see plan)."""
    s, e = _dtp(start_iso), _dtp(end_iso)
    if s is None or e is None or e < s:
        return 0
    days, cur = 0, s.date()
    end = e.date()
    while cur < end:
        cur += timedelta(days=1)
        if cur.weekday() < 5:
            days += 1
    return days


def reconstruct_open_positions(trades: list[dict], as_of_iso: str) -> dict[str, dict]:
    """Replay filled buys/sells with created_at <= as_of into net open lots per symbol."""
    as_of = _dtp(as_of_iso)
    if as_of is None:
        return {}
    net: dict[str, dict] = {}
    for t in sorted(trades, key=lambda r: str(r.get("created_at"))):
        ts = _dtp(t.get("created_at"))
        if as_of is not None and (ts is None or ts > as_of):
            continue
        sym = t.get("symbol")
        side = str(t.get("side")).lower()
        qty = _f(t.get("filled_quantity")) or _f(t.get("quantity"))
        cur = net.setdefault(sym, {"qty": 0.0, "opened_at": None, "stop_loss_price": None})
        if side == "buy":
            if cur["qty"] <= 1e-9:                      # opening a fresh position
                cur["opened_at"] = t.get("created_at")
                cur["stop_loss_price"] = t.get("stop_loss_price")
            cur["qty"] += qty
        elif side == "sell":
            cur["qty"] -= qty
            if cur["qty"] <= 1e-9:
                cur.update(qty=0.0, opened_at=None, stop_loss_price=None)
    return {s: v for s, v in net.items() if v["qty"] > 1e-9}


def _matching_open_buy(history: list[dict], sell: dict) -> dict | None:
    """Most recent filled BUY of the same symbol strictly before the sell."""
    sell_ts = _dtp(sell.get("created_at"))
    candidates = [
        t for t in history
        if t.get("symbol") == sell.get("symbol")
        and str(t.get("side")).lower() == "buy"
        and _dtp(t.get("created_at")) is not None
        and (sell_ts is None or _dtp(t.get("created_at")) < sell_ts)
    ]
    return max(candidates, key=lambda t: _dtp(t.get("created_at"))) if candidates else None


def _check_anti_churn(context: dict) -> dict:
    min_hold = context["spec"]["min_hold_trading_days"]
    history = context["trades_history"]
    violations = []
    for sell in context["trades_window"]:
        if str(sell.get("side")).lower() != "sell":
            continue
        if str(sell.get("order_class")) == "bracket_fill":       # stop/TP exit is exempt
            continue
        if _dtp(sell.get("created_at")) is None:
            continue
        buy = _matching_open_buy(history, sell)
        if buy is None:
            continue                                             # cannot match → not a violation
        held = trading_days_between(buy["created_at"], sell["created_at"])
        if held < min_hold:
            violations.append({"symbol": sell.get("symbol"), "held_trading_days": held,
                               "min": min_hold, "bought_at": buy["created_at"],
                               "sold_at": sell["created_at"]})
    if violations:
        return _fact("anti_churn", "violated", "fail",
                     f"{len(violations)} discretionary sell(s) inside the {min_hold}-day min hold.",
                     {"violations": violations})
    return _fact("anti_churn", "conformant", "pass", "No early discretionary exits.", {})


def _check_position_count(context: dict) -> dict:
    cap = context["spec"]["max_positions"]
    floor = context["spec"]["min_positions_soft"]
    history = context["trades_history"]
    if not history:
        return _fact("position_count", "unverifiable", "info",
                     "No trade history available to assess position count.", {})
    overages = []
    for t in context["trades_window"]:
        if str(t.get("side")).lower() != "buy":
            continue
        n = len(reconstruct_open_positions(history, t["created_at"]))
        if n > cap:
            overages.append({"at": t["created_at"], "open_positions": n,
                             "cap": cap, "after_buy": t.get("symbol")})
    end_of_run = len(reconstruct_open_positions(history, context["run_end"]))
    if overages:
        return _fact("position_count", "violated", "warn",
                     f"Held more than {cap} positions at {len(overages)} point(s).",
                     {"overages": overages, "end_of_run": end_of_run})
    if end_of_run > cap:
        return _fact("position_count", "violated", "warn",
                     f"Holding {end_of_run} positions at run end, over the cap of {cap}.",
                     {"end_of_run": end_of_run, "cap": cap})
    if end_of_run < floor:
        return _fact("position_count", "violated", "warn",
                     f"Under-invested: {end_of_run} positions at run end (soft floor {floor}).",
                     {"end_of_run": end_of_run, "floor": floor})
    return _fact("position_count", "conformant", "pass",
                 f"{end_of_run} positions at run end, within [{floor},{cap}].",
                 {"end_of_run": end_of_run})


def _check_stops_present(context: dict) -> dict:
    missing = []
    for t in context["trades_window"]:
        if str(t.get("side")).lower() != "buy":
            continue
        if t.get("stop_loss_price") in (None, "", 0):
            missing.append({"symbol": t.get("symbol"), "at": t.get("created_at")})
    if missing:
        return _fact("stops_present", "violated", "fail",
                     f"{len(missing)} buy(s) opened without a stop-loss.", {"missing": missing})
    return _fact("stops_present", "conformant", "pass", "All buys carry a stop.", {})


def _check_factor_weights_conformance(context: dict) -> dict:
    active = context.get("factor_weights")
    rankings = context.get("factor_rankings")
    if not active or not rankings or not rankings.get("factor_weights"):
        return _fact("factor_weights_conformance", "unverifiable", "info",
                     "No recorded scoring weights or active weights to compare.", {})
    if context.get("factor_weights_stale"):
        return _fact("factor_weights_conformance", "unverifiable", "info",
                     "Active factor_weights changed after the run; cannot compare point-in-time.", {})
    if not context.get("factor_rankings_in_window"):
        return _fact("factor_weights_conformance", "unverifiable", "info",
                     "Recorded scoring snapshot is not from this run's window; cannot compare point-in-time.", {})
    used = rankings["factor_weights"]
    diffs = {k: round(_f(used.get(k)) - _f(active.get(k)), 4)
             for k in set(active) | set(used)
             if abs(_f(used.get(k)) - _f(active.get(k))) > 1e-3}
    if diffs:
        return _fact("factor_weights_conformance", "violated", "warn",
                     "Run scored with weights differing from the active strategy.", {"diffs": diffs})
    return _fact("factor_weights_conformance", "conformant", "pass",
                 "Scored with active weights.", {})


def _check_regime_gate(context: dict) -> dict:
    regime = context.get("market_regime")
    if not regime or not context.get("market_regime_in_window"):
        return _fact("regime_gate", "unverifiable", "info",
                     "No market_regime recorded within the run window.", {})
    vix, breadth = _f(regime.get("vix")), _f(regime.get("breadth_pct"))
    # Hard-block thresholds mirror the trader's risk.py:_check_regime_gate (VIX>26 AND breadth<30).
    if not (vix > 26 and breadth < 30):
        return _fact("regime_gate", "conformant", "pass",
                     f"Regime not in hard-block (VIX {vix}, breadth {breadth}%).", {})
    buys = [t for t in context["trades_window"] if str(t.get("side")).lower() == "buy"]
    if buys:
        return _fact("regime_gate", "violated", "fail",
                     f"{len(buys)} buy(s) during a hard-block regime (VIX {vix}, breadth {breadth}%).",
                     {"buys": [b.get("symbol") for b in buys], "vix": vix, "breadth_pct": breadth})
    return _fact("regime_gate", "conformant", "pass",
                 f"Hard-block regime respected — no buys (VIX {vix}, breadth {breadth}%).", {})


_EVALUATORS = {
    "anti_churn": _check_anti_churn,
    "position_count": _check_position_count,
    "stops_present": _check_stops_present,
    "factor_weights_conformance": _check_factor_weights_conformance,
    "regime_gate": _check_regime_gate,
}
assert set(_EVALUATORS) == VERIFIED_RULES, "evaluator table must cover exactly VERIFIED_RULES"


def classify_conformance(context: dict) -> list[dict]:
    """One deterministic fact per KNOWN_STRATEGY_RULES — verified via evaluators,
    unverifiable rules emitted with their fixed reason. Coverage cannot silently regress."""
    facts = [_EVALUATORS[r](context) for r in sorted(VERIFIED_RULES)]
    for r in sorted(UNVERIFIABLE_RULES):
        facts.append(_fact(r, "unverifiable", "info", _UNVERIFIABLE_REASON[r], {}))
    return facts
