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
