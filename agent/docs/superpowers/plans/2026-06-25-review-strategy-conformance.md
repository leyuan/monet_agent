# review-strategy-conformance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the reviewer's `review-strategy-conformance` skill to the trace-native, deterministic-facts-plus-LLM-judgment template — auditing whether an `autonomous_loop` run obeyed the **declared** strategy (point-in-time), never a hardcoded copy of the rules.

**Architecture:** A pure module (`strategy_conformance.py`) holds an effective-dated `STRATEGY_SPEC_VERSIONS`, a `CHECK` rule-set partitioned into `VERIFIED_RULES` / `UNVERIFIABLE_RULES`, pure position-reconstruction helpers, five rule evaluators, and `classify_conformance` / `run_severity`. An I/O tool (`get_strategy_conformance_runs`) reads the trace for run identity + window, pulls `trades` (run window + 30-day trailing) and three memory snapshots read-only, then calls the pure classifier. Run-selection / watermark plumbing is reused from `run_cursor` (already extracted, imported via `tool_fidelity`). The `SKILL.md` orchestrates: interpret the facts, judge severity, write the verdict, consolidate, advance the watermark.

**Tech Stack:** Python 3.11+, pytest (`pythonpath=["src"]`, `asyncio_mode=auto`), deepagents, LangSmith (`read_run_trace`), Supabase (`query_database` → `exec_readonly_sql`, `read_agent_memory`).

## Global Constraints

- **Reviewer is read-only on the trader.** No trading tools; writes only to `agent_reviews` + `reviewer_memory`. The boundary test `tests/test_review_tools_boundary.py` must stay green (`place_order` etc. never appear in `REVIEW_TOOLS`).
- **Deterministic facts, LLM judgment.** The pure functions compute each rule's `status` and the run `severity`; the LLM writes prose and may add caveats but never re-derives a status and never overrides a computed `fail` downward. No model in the pure layer.
- **Pure functions take/return plain dicts** (no LangSmith/Supabase imports) so they unit-test without I/O — same convention as `tool_fidelity.py` / `operation_success.py`.
- **Trace is graph-filtered to `autonomous_loop`** (already done in `read_run_trace`); skip in-progress runs (`is_finished`).
- **Memory binding is by `begin_review("conformance")`** — watermark + detail namespaces bind from the active review type; the LLM chooses only `scope=`, never a raw namespace.
- **Never hardcode rule thresholds in `SKILL.md`.** Values resolve from `STRATEGY_SPEC_VERSIONS` (declared, effective-dated) or live memory/`risk_settings` reads.
- **Honest degradation, never a false fail.** A rule whose inputs are absent or changed-after-the-run is `unverifiable` (severity `info`), never `violated`. Same principle as operation-success's probe-error rule.
- **Run tests from `agent/`**: `cd agent && python -m pytest <path> -v`.
- **v1 scoping (explicit deviations from spec §4, conservative):**
  - `risk_limit_leak` (position size / total exposure / daily-loss / earnings-window) is **`unverifiable` in v1** — verifying it needs point-in-time equity and historical earnings dates that are not durably stored; a bad reconstruction would produce a *false fail on an enforced rule*, the worst outcome. Deferred to roadmap (subsumed by `PROPOSAL-strategy-spec.md`).
  - `regime_gate` v1 checks the **hard-block** sub-rule only (no buys when a recorded regime has VIX>26 AND breadth<30). The caution-tier "reduce position size" sub-rule needs equity → deferred.
  - Trading-day counting approximates with **weekday counting** (Mon–Fri), ignoring market holidays. Documented; acceptable for a 5-day min-hold gate.

---

## File Structure

- `src/review_agent/strategy_conformance.py` — **new, pure.** `STRATEGY_SPEC_VERSIONS`, `VERIFIED_RULES`, `UNVERIFIABLE_RULES`, `KNOWN_STRATEGY_RULES`, `_UNVERIFIABLE_REASON`, `resolve_spec`, `trading_days_between`, `reconstruct_open_positions`, five `_check_*` evaluators, `_EVALUATORS`, `classify_conformance`, `run_severity`, `_fact`.
- `src/review_agent/tools.py` — **modify.** Add `get_strategy_conformance_runs` + small datetime helpers; register the tool in `REVIEW_TOOLS`.
- `src/review_agent/skills/review-strategy-conformance/SKILL.md` — **rewrite.**
- `tests/test_strategy_conformance_spec.py` — **new** (resolve_spec + static partition).
- `tests/test_strategy_conformance_reconstruct.py` — **new** (position reconstruction + trading-day helper).
- `tests/test_strategy_conformance_checks_trades.py` — **new** (anti_churn, position_count, stops_present).
- `tests/test_strategy_conformance_classify.py` — **new** (factor_weights, regime_gate, dispatch + runtime coverage).
- `tests/test_strategy_conformance_tools.py` — **new** (the trace × DB join tool).
- `POSTDEPLOY_CHECK.md`, `docs/REVIEWER-TEST-PROD.md` — **modify** (verification block + test-prod note).

---

## Task 1: Pure module skeleton — spec resolution, rule partition, severity

**Files:**
- Create: `src/review_agent/strategy_conformance.py`
- Test: `tests/test_strategy_conformance_spec.py`

**Interfaces:**
- Produces: `resolve_spec(run_date: str) -> dict` (keys: `effective_from, min_hold_trading_days, max_positions, min_positions_soft`); `run_severity(facts: list[dict]) -> str`; `_fact(rule, status, severity, detail, evidence) -> dict`; module sets `VERIFIED_RULES: set[str]`, `UNVERIFIABLE_RULES: set[str]`, `KNOWN_STRATEGY_RULES: set[str]`, `_UNVERIFIABLE_REASON: dict[str,str]`.
- Consumes: nothing.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_strategy_conformance_spec.py
from review_agent.strategy_conformance import (
    resolve_spec, run_severity, VERIFIED_RULES, UNVERIFIABLE_RULES, KNOWN_STRATEGY_RULES,
)


def test_resolve_spec_picks_effective_dated_version():
    spec = resolve_spec("2026-06-19")
    assert spec["min_hold_trading_days"] == 5
    assert spec["max_positions"] == 8
    assert spec["min_positions_soft"] == 5


def test_resolve_spec_falls_back_to_oldest_for_early_dates():
    spec = resolve_spec("2000-01-01")           # predates all versions
    assert spec["max_positions"] == 8           # oldest version, not a crash


def test_rule_partition_is_clean():
    assert VERIFIED_RULES.isdisjoint(UNVERIFIABLE_RULES)
    assert KNOWN_STRATEGY_RULES == VERIFIED_RULES | UNVERIFIABLE_RULES
    assert "anti_churn" in VERIFIED_RULES
    assert "risk_limit_leak" in UNVERIFIABLE_RULES   # v1 deviation


def test_run_severity_is_worst_and_unverifiable_never_raises():
    facts = [
        {"rule": "a", "status": "conformant", "severity": "pass"},
        {"rule": "b", "status": "unverifiable", "severity": "info"},
        {"rule": "c", "status": "violated", "severity": "warn"},
    ]
    assert run_severity(facts) == "warn"
    assert run_severity([{"rule": "x", "status": "unverifiable", "severity": "info"}]) == "info"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd agent && python -m pytest tests/test_strategy_conformance_spec.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'review_agent.strategy_conformance'`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/review_agent/strategy_conformance.py
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
            return v
    return STRATEGY_SPEC_VERSIONS[-1]


def run_severity(facts: list[dict]) -> str:
    """Run verdict severity = the worst rule severity (unverifiable rules are 'info')."""
    worst = "pass"
    for f in facts:
        if _SEVERITY_ORDER[f["severity"]] > _SEVERITY_ORDER[worst]:
            worst = f["severity"]
    return worst
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd agent && python -m pytest tests/test_strategy_conformance_spec.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add agent/src/review_agent/strategy_conformance.py agent/tests/test_strategy_conformance_spec.py
git commit -m "feat(reviewer): conformance spec resolution + rule partition"
```

---

## Task 2: Position reconstruction + trading-day helper

**Files:**
- Modify: `src/review_agent/strategy_conformance.py` (add helpers)
- Test: `tests/test_strategy_conformance_reconstruct.py`

**Interfaces:**
- Produces: `trading_days_between(start_iso: str, end_iso: str) -> int`; `reconstruct_open_positions(trades: list[dict], as_of_iso: str) -> dict[str, dict]` where each value is `{"qty": float, "opened_at": str | None, "stop_loss_price": float | None}`.
- Consumes: nothing (operates on plain trade dicts with keys `symbol, side, filled_quantity, quantity, stop_loss_price, created_at`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_strategy_conformance_reconstruct.py
from review_agent.strategy_conformance import trading_days_between, reconstruct_open_positions


def _t(symbol, side, qty, created_at, stop=None, order_class="simple"):
    return {"symbol": symbol, "side": side, "filled_quantity": qty, "quantity": qty,
            "stop_loss_price": stop, "created_at": created_at, "order_class": order_class}


def test_trading_days_between_counts_weekdays():
    # Fri 2026-06-19 -> Wed 2026-06-24: Mon22, Tue23, Wed24 = 3 trading days
    assert trading_days_between("2026-06-19T14:00:00+00:00", "2026-06-24T14:00:00+00:00") == 3


def test_trading_days_between_handles_bad_or_reversed_input():
    assert trading_days_between("nonsense", "2026-06-24T00:00:00+00:00") == 0
    assert trading_days_between("2026-06-24T00:00:00+00:00", "2026-06-19T00:00:00+00:00") == 0


def test_reconstruct_open_positions_nets_buys_and_sells():
    trades = [
        _t("AAPL", "buy", 10, "2026-06-10T14:00:00+00:00", stop=180.0),
        _t("MSFT", "buy", 5, "2026-06-11T14:00:00+00:00", stop=400.0),
        _t("AAPL", "sell", 10, "2026-06-15T14:00:00+00:00"),   # closes AAPL
    ]
    held = reconstruct_open_positions(trades, "2026-06-20T00:00:00+00:00")
    assert set(held) == {"MSFT"}
    assert held["MSFT"]["opened_at"] == "2026-06-11T14:00:00+00:00"
    assert held["MSFT"]["stop_loss_price"] == 400.0


def test_reconstruct_is_point_in_time():
    trades = [
        _t("AAPL", "buy", 10, "2026-06-10T14:00:00+00:00", stop=180.0),
        _t("AAPL", "sell", 10, "2026-06-15T14:00:00+00:00"),
    ]
    # as_of before the sell → still held
    assert set(reconstruct_open_positions(trades, "2026-06-12T00:00:00+00:00")) == {"AAPL"}
    # as_of after the sell → flat
    assert reconstruct_open_positions(trades, "2026-06-16T00:00:00+00:00") == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd agent && python -m pytest tests/test_strategy_conformance_reconstruct.py -v`
Expected: FAIL — `ImportError: cannot import name 'trading_days_between'`.

- [ ] **Step 3: Write minimal implementation** (append to `strategy_conformance.py`)

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd agent && python -m pytest tests/test_strategy_conformance_reconstruct.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add agent/src/review_agent/strategy_conformance.py agent/tests/test_strategy_conformance_reconstruct.py
git commit -m "feat(reviewer): conformance position reconstruction + trading-day helper"
```

---

## Task 3: Trades-pure evaluators — anti_churn, position_count, stops_present

**Files:**
- Modify: `src/review_agent/strategy_conformance.py` (add three evaluators + `_matching_open_buy`)
- Test: `tests/test_strategy_conformance_checks_trades.py`

**Interfaces:**
- Produces: `_check_anti_churn(context) -> dict`, `_check_position_count(context) -> dict`, `_check_stops_present(context) -> dict`. Each returns a `_fact(...)`. They read `context["spec"]`, `context["trades_window"]`, `context["trades_history"]`, `context["run_end"]`.
- Consumes: `_fact`, `resolve_spec` shape, `reconstruct_open_positions`, `trading_days_between` (Tasks 1–2).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_strategy_conformance_checks_trades.py
from review_agent.strategy_conformance import (
    _check_anti_churn, _check_position_count, _check_stops_present,
)

SPEC = {"min_hold_trading_days": 5, "max_positions": 8, "min_positions_soft": 5}


def _t(symbol, side, qty, created_at, stop=180.0, order_class="simple"):
    return {"symbol": symbol, "side": side, "filled_quantity": qty, "quantity": qty,
            "stop_loss_price": stop, "created_at": created_at, "order_class": order_class}


def _ctx(window, history=None, run_end="2026-06-30T00:00:00+00:00"):
    return {"spec": SPEC, "trades_window": window,
            "trades_history": history if history is not None else window, "run_end": run_end}


def test_anti_churn_flags_early_discretionary_sell():
    buy = _t("AAPL", "buy", 10, "2026-06-15T14:00:00+00:00")
    sell = _t("AAPL", "sell", 10, "2026-06-17T14:00:00+00:00")        # 2 trading days < 5
    f = _check_anti_churn(_ctx([buy, sell]))
    assert f["status"] == "violated" and f["severity"] == "fail"


def test_anti_churn_exempts_bracket_fill_exits():
    buy = _t("AAPL", "buy", 10, "2026-06-15T14:00:00+00:00")
    stop_exit = _t("AAPL", "sell", 10, "2026-06-16T14:00:00+00:00", order_class="bracket_fill")
    f = _check_anti_churn(_ctx([buy, stop_exit]))
    assert f["status"] == "conformant"


def test_anti_churn_passes_when_held_long_enough():
    buy = _t("AAPL", "buy", 10, "2026-06-08T14:00:00+00:00")
    sell = _t("AAPL", "sell", 10, "2026-06-17T14:00:00+00:00")        # 7 trading days >= 5
    f = _check_anti_churn(_ctx([buy, sell]))
    assert f["status"] == "conformant"


def test_position_count_warns_when_over_cap():
    hist = [_t(f"S{i}", "buy", 1, f"2026-06-1{i}T14:00:00+00:00") for i in range(9)]  # 9 > 8
    last_buy = hist[-1]
    f = _check_position_count(_ctx([last_buy], history=hist))
    assert f["status"] == "violated" and f["severity"] == "warn"
    assert f["evidence"]["overages"]


def test_position_count_conformant_within_band():
    hist = [_t(f"S{i}", "buy", 1, f"2026-06-1{i}T14:00:00+00:00") for i in range(6)]  # 6 in [5,8]
    f = _check_position_count(_ctx([hist[-1]], history=hist))
    assert f["status"] == "conformant"


def test_stops_present_flags_missing_stop():
    buy = _t("AAPL", "buy", 10, "2026-06-15T14:00:00+00:00", stop=None)
    f = _check_stops_present(_ctx([buy]))
    assert f["status"] == "violated" and f["severity"] == "fail"


def test_stops_present_passes_when_all_buys_have_stops():
    buy = _t("AAPL", "buy", 10, "2026-06-15T14:00:00+00:00", stop=170.0)
    f = _check_stops_present(_ctx([buy]))
    assert f["status"] == "conformant"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd agent && python -m pytest tests/test_strategy_conformance_checks_trades.py -v`
Expected: FAIL — `ImportError: cannot import name '_check_anti_churn'`.

- [ ] **Step 3: Write minimal implementation** (append to `strategy_conformance.py`)

```python
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
    return max(candidates, key=lambda t: str(t.get("created_at"))) if candidates else None


def _check_anti_churn(context: dict) -> dict:
    min_hold = context["spec"]["min_hold_trading_days"]
    history = context["trades_history"]
    violations = []
    for sell in context["trades_window"]:
        if str(sell.get("side")).lower() != "sell":
            continue
        if str(sell.get("order_class")) == "bracket_fill":       # stop/TP exit is exempt
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd agent && python -m pytest tests/test_strategy_conformance_checks_trades.py -v`
Expected: PASS (7 passed).

- [ ] **Step 5: Commit**

```bash
git add agent/src/review_agent/strategy_conformance.py agent/tests/test_strategy_conformance_checks_trades.py
git commit -m "feat(reviewer): conformance trades-pure checks (anti_churn, position_count, stops_present)"
```

---

## Task 4: Memory-dependent evaluators + dispatch + runtime coverage

**Files:**
- Modify: `src/review_agent/strategy_conformance.py` (add two evaluators, `_EVALUATORS`, `classify_conformance`)
- Test: `tests/test_strategy_conformance_classify.py`

**Interfaces:**
- Produces: `_check_factor_weights_conformance(context) -> dict`; `_check_regime_gate(context) -> dict`; `classify_conformance(context: dict) -> list[dict]` (one fact per `KNOWN_STRATEGY_RULES`).
- Consumes: `context` keys `factor_weights` (dict|None), `factor_weights_stale` (bool), `factor_rankings` (dict|None), `market_regime` (dict|None), `market_regime_in_window` (bool), plus the trades keys from Task 3.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_strategy_conformance_classify.py
from review_agent.strategy_conformance import (
    _check_factor_weights_conformance, _check_regime_gate, classify_conformance,
    KNOWN_STRATEGY_RULES, UNVERIFIABLE_RULES,
)

SPEC = {"min_hold_trading_days": 5, "max_positions": 8, "min_positions_soft": 5}


def _base_ctx(**over):
    ctx = {"spec": SPEC, "trades_window": [], "trades_history": [],
           "run_end": "2026-06-30T00:00:00+00:00",
           "factor_weights": None, "factor_weights_stale": False,
           "factor_rankings": None, "market_regime": None, "market_regime_in_window": False}
    ctx.update(over)
    return ctx


def test_factor_weights_conformant_when_matching():
    w = {"momentum": 0.35, "quality": 0.30, "value": 0.20, "eps_revision": 0.15}
    f = _check_factor_weights_conformance(_base_ctx(
        factor_weights=w, factor_rankings={"factor_weights": dict(w)}))
    assert f["status"] == "conformant"


def test_factor_weights_violated_when_run_used_stale_weights():
    active = {"momentum": 0.45, "quality": 0.30, "value": 0.15, "eps_revision": 0.10}
    used = {"momentum": 0.35, "quality": 0.30, "value": 0.20, "eps_revision": 0.15}
    f = _check_factor_weights_conformance(_base_ctx(
        factor_weights=active, factor_rankings={"factor_weights": used}))
    assert f["status"] == "violated" and f["severity"] == "warn"
    assert "momentum" in f["evidence"]["diffs"]


def test_factor_weights_unverifiable_when_active_changed_after_run():
    w = {"momentum": 0.35}
    f = _check_factor_weights_conformance(_base_ctx(
        factor_weights=w, factor_rankings={"factor_weights": {"momentum": 0.40}},
        factor_weights_stale=True))
    assert f["status"] == "unverifiable" and f["severity"] == "info"


def test_regime_gate_violated_when_buy_during_hard_block():
    buy = {"symbol": "AAPL", "side": "buy", "created_at": "2026-06-19T14:00:00+00:00",
           "filled_quantity": 1, "quantity": 1, "stop_loss_price": 1.0, "order_class": "simple"}
    f = _check_regime_gate(_base_ctx(
        trades_window=[buy], market_regime={"vix": 30, "breadth_pct": 20},
        market_regime_in_window=True))
    assert f["status"] == "violated" and f["severity"] == "fail"


def test_regime_gate_unverifiable_when_no_regime_in_window():
    f = _check_regime_gate(_base_ctx(market_regime=None, market_regime_in_window=False))
    assert f["status"] == "unverifiable"


def test_classify_emits_exactly_the_known_rule_set():
    facts = classify_conformance(_base_ctx())
    emitted = {f["rule"] for f in facts}
    assert emitted == KNOWN_STRATEGY_RULES               # runtime coverage guarantee
    # every unverifiable rule reports unverifiable
    by = {f["rule"]: f for f in facts}
    for r in UNVERIFIABLE_RULES:
        assert by[r]["status"] == "unverifiable"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd agent && python -m pytest tests/test_strategy_conformance_classify.py -v`
Expected: FAIL — `ImportError: cannot import name '_check_factor_weights_conformance'`.

- [ ] **Step 3: Write minimal implementation** (append to `strategy_conformance.py`)

```python
def _check_factor_weights_conformance(context: dict) -> dict:
    active = context.get("factor_weights")
    rankings = context.get("factor_rankings")
    if not active or not rankings or not rankings.get("factor_weights"):
        return _fact("factor_weights_conformance", "unverifiable", "info",
                     "No recorded scoring weights or active weights to compare.", {})
    if context.get("factor_weights_stale"):
        return _fact("factor_weights_conformance", "unverifiable", "info",
                     "Active factor_weights changed after the run; cannot compare point-in-time.", {})
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd agent && python -m pytest tests/test_strategy_conformance_classify.py tests/test_strategy_conformance_spec.py tests/test_strategy_conformance_reconstruct.py tests/test_strategy_conformance_checks_trades.py -v`
Expected: PASS (all conformance pure tests green).

- [ ] **Step 5: Commit**

```bash
git add agent/src/review_agent/strategy_conformance.py agent/tests/test_strategy_conformance_classify.py
git commit -m "feat(reviewer): conformance memory checks + classify dispatch with runtime coverage"
```

---

## Task 5: I/O tool `get_strategy_conformance_runs` + registration

**Files:**
- Modify: `src/review_agent/tools.py` (add datetime helpers, the tool, register in `REVIEW_TOOLS`, import from `strategy_conformance`)
- Test: `tests/test_strategy_conformance_tools.py`, and re-run `tests/test_review_tools_boundary.py`

**Interfaces:**
- Produces: `get_strategy_conformance_runs(subject: str | None = None, config: RunnableConfig = None) -> dict` returning `{"runs": [{"run_id", "start_time", "run_severity", "rules": [...]}], "skipped_in_progress": [...]}`.
- Consumes (already in `tools.py` namespace): `read_run_trace`, `query_database`, `read_agent_memory`, `_get_active`, `_thread_id`, `_read_watermark`, `_COLD_START_N`, `select_unreviewed`, `is_finished`, `_dt` (`datetime`). Adds `from datetime import timedelta as _td`. From `strategy_conformance`: `resolve_spec`, `classify_conformance`, `run_severity`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_strategy_conformance_tools.py
import review_agent.tools as T

FAKE_CONFIG = {"configurable": {"thread_id": "t1"}}

_TRACE = {"runs": [
    {"run_id": "r1", "name": "autonomous_loop",
     "start_time": "2026-06-19T14:00:00+00:00", "end_time": "2026-06-19T14:05:00+00:00",
     "error": None, "tool_calls": []},
]}

_TRADES = [
    {"symbol": "AAPL", "side": "buy", "order_class": "simple", "quantity": 10,
     "filled_quantity": 10, "filled_avg_price": 190.0, "stop_loss_price": 180.0,
     "status": "filled", "created_at": "2026-06-19T14:01:00+00:00", "thesis": "x"},
    {"symbol": "AAPL", "side": "sell", "order_class": "simple", "quantity": 10,
     "filled_quantity": 10, "filled_avg_price": 192.0, "stop_loss_price": None,
     "status": "filled", "created_at": "2026-06-19T14:02:00+00:00", "thesis": "early exit"},
]


def _setup(monkeypatch, trace=_TRACE, trades=_TRADES, memory=None):
    monkeypatch.setattr(T, "_get_active", lambda tid: "conformance")
    monkeypatch.setattr(T, "read_run_trace", lambda **k: trace)
    monkeypatch.setattr(T, "_read_watermark", lambda rt: None)         # cold start
    monkeypatch.setattr(T, "query_database", lambda sql: {"rows": trades})
    mem = memory or {}
    monkeypatch.setattr(T, "read_agent_memory", lambda key: mem.get(key, {"key": key, "value": None}))


def test_join_flags_anti_churn_and_missing_stop(monkeypatch):
    _setup(monkeypatch)
    out = T.get_strategy_conformance_runs(config=FAKE_CONFIG)
    run = out["runs"][0]
    by = {r["rule"]: r for r in run["rules"]}
    assert by["anti_churn"]["status"] == "violated"        # sold same minute it bought
    assert run["run_severity"] == "fail"
    assert "risk_limit_leak" in by and by["risk_limit_leak"]["status"] == "unverifiable"


def test_skips_in_progress(monkeypatch):
    trace = {"runs": [{"run_id": "rp", "name": "autonomous_loop",
                       "start_time": "2026-06-19T14:00:00+00:00", "end_time": None,
                       "error": None, "tool_calls": []}]}
    _setup(monkeypatch, trace=trace)
    out = T.get_strategy_conformance_runs(config=FAKE_CONFIG)
    assert out["runs"] == [] and "rp" in out["skipped_in_progress"]


def test_query_error_yields_empty_history_not_crash(monkeypatch):
    _setup(monkeypatch)
    monkeypatch.setattr(T, "query_database", lambda sql: {"error": "boom"})
    out = T.get_strategy_conformance_runs(config=FAKE_CONFIG)
    run = out["runs"][0]
    by = {r["rule"]: r for r in run["rules"]}
    assert by["anti_churn"]["status"] == "conformant"      # no trades → nothing violated
    assert run["run_severity"] in ("pass", "info")          # never a false fail off a dead probe


def test_requires_active_review(monkeypatch):
    monkeypatch.setattr(T, "_get_active", lambda tid: None)
    import pytest
    with pytest.raises(ValueError):
        T.get_strategy_conformance_runs(config=FAKE_CONFIG)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd agent && python -m pytest tests/test_strategy_conformance_tools.py -v`
Expected: FAIL — `AttributeError: module 'review_agent.tools' has no attribute 'get_strategy_conformance_runs'`.

- [ ] **Step 3: Write minimal implementation**

Add the import alongside the existing `from datetime import datetime as _dt` line in `tools.py`:

```python
from datetime import datetime as _dt, timedelta as _td
```

Add the `strategy_conformance` import next to the `operation_success` import block:

```python
from review_agent.strategy_conformance import (
    resolve_spec, classify_conformance, run_severity as conformance_run_severity,
)
```

> Note: alias `run_severity as conformance_run_severity` to avoid colliding with operation-success's `run_severity` already imported in `tools.py`.

Add the helpers + tool (place after `get_operation_success_runs`):

```python
def _conformance_trades_sql(window_start: str, run_end: str) -> str:
    return (
        "SELECT symbol, side, order_class, quantity, filled_quantity, filled_avg_price, "
        "stop_loss_price, status, created_at, thesis FROM trades "
        f"WHERE created_at >= '{window_start}' AND created_at <= '{run_end}' "
        "AND status ILIKE '%filled%' ORDER BY created_at ASC"
    )


def _ts_ge(a: str | None, b: str) -> bool:
    try:
        return _dt.fromisoformat(str(a)) >= _dt.fromisoformat(str(b))
    except (TypeError, ValueError):
        return False


def _within(ts: str | None, start: str, end: str) -> bool:
    return bool(ts) and _ts_ge(ts, start) and _ts_ge(end, ts)


def get_strategy_conformance_runs(subject: str | None = None, config: RunnableConfig = None) -> dict:
    """Resolve trader runs to audit and return their DETERMINISTIC conformance facts.

    For each finished run: pull the trade ledger (run window + 30-day trailing) and three
    memory snapshots read-only, resolve the declared strategy in force at run time, and
    classify each rule. Sweep mode (subject None) = runs newer than the conformance
    watermark; explicit mode (subject a run_id) = just that run. You INTERPRET the statuses,
    write a verdict per run with write_review, then call mark_run_reviewed(run_id, start_time).

    Returns: {"runs": [{"run_id","start_time","run_severity","rules":[...]}],
              "skipped_in_progress": [...]}.
    """
    rt = _get_active(_thread_id(config))
    if rt is None:
        raise ValueError("No active review — call begin_review first.")
    if subject:
        roots = read_run_trace(run_id=subject)["runs"]
    else:
        cursor = _read_watermark(rt)
        roots = select_unreviewed(read_run_trace(limit=10)["runs"], cursor, cold_start_n=_COLD_START_N)

    fw = read_agent_memory("factor_weights")
    fr = read_agent_memory("factor_rankings")
    mr = read_agent_memory("market_regime")

    out, skipped = [], []
    for run in roots:
        if not is_finished(run):
            skipped.append(run["run_id"])
            continue
        run_start = run["start_time"]
        run_end = run.get("end_time") or run_start
        try:
            window_start = (_dt.fromisoformat(run_start) - _td(days=30)).isoformat()
        except (TypeError, ValueError):
            window_start = run_start
        res = query_database(_conformance_trades_sql(window_start, run_end))
        history = [] if res.get("error") else (res.get("rows") or [])
        window = [t for t in history if _ts_ge(t.get("created_at"), run_start)]
        context = {
            "run_id": run["run_id"], "run_start": run_start, "run_end": run_end,
            "spec": resolve_spec(run_start[:10]),
            "trades_window": window, "trades_history": history,
            "factor_weights": (fw or {}).get("value"),
            "factor_weights_stale": _ts_ge(fw.get("updated_at"), run_end) and (fw.get("updated_at") != run_end) if fw else False,
            "factor_rankings": (fr or {}).get("value"),
            "market_regime": (mr or {}).get("value"),
            "market_regime_in_window": _within(mr.get("updated_at"), run_start, run_end) if mr else False,
        }
        facts = classify_conformance(context)
        out.append({"run_id": run["run_id"], "start_time": run_start,
                    "run_severity": conformance_run_severity(facts), "rules": facts})
    return {"runs": out, "skipped_in_progress": skipped}
```

Register the tool — add to the `REVIEW_TOOLS` list, after `get_operation_success_runs`:

```python
    # conformance audit (reuses mark_run_reviewed for the watermark)
    get_strategy_conformance_runs,
```

- [ ] **Step 4: Run tests to verify they pass (incl. the boundary test stays green)**

Run: `cd agent && python -m pytest tests/test_strategy_conformance_tools.py tests/test_review_tools_boundary.py -v`
Expected: PASS — the four tool tests pass and the boundary test still confirms no trading tools in `REVIEW_TOOLS`.

- [ ] **Step 5: Commit**

```bash
git add agent/src/review_agent/tools.py agent/tests/test_strategy_conformance_tools.py
git commit -m "feat(reviewer): get_strategy_conformance_runs (trace x DB join) + register"
```

---

## Task 6: Rewrite `SKILL.md`

**Files:**
- Rewrite: `src/review_agent/skills/review-strategy-conformance/SKILL.md`

**Interfaces:**
- Consumes: `begin_review`, `get_strategy_conformance_runs`, `write_review`, `record_insight`, `write_reviewer_memory`, `promote_to_global`, `mark_run_reviewed` (all existing tools). No new code.

- [ ] **Step 1: Replace the file with the trace-native orchestration**

Write `src/review_agent/skills/review-strategy-conformance/SKILL.md`:

````markdown
---
name: review-strategy-conformance
description: >
  Audit whether an autonomous run obeyed the DECLARED strategy (point-in-time): anti-churn
  min-hold, position-count band, factor-weight conformance, stops-present, regime hard-block.
  Deterministic facts come from get_strategy_conformance_runs; you judge severity and write the
  verdict. Use for rule compliance / discipline / "did it follow strategy". NOT for reasoning
  quality (review-decision-quality), efficacy (review-strategy-efficacy), tool correctness
  (review-tool-fidelity), or persistence (review-operation-success).
memory_namespace: conformance
memory_access: { read: own, write: own }
tags: [rules, process, discipline]
---

# Review: Strategy Conformance

You audit whether a run OBEYED the declared strategy. You judge against the rules as the tool
resolved them (point-in-time); you never hand-derive thresholds and never second-guess the
strategy itself.

## Step 0 — begin + fit-check
Call `begin_review("conformance", subject="<run id / date>", reason="<why conformance>")` FIRST —
it binds your memory and returns your bounded prior-context. Then state:
"Running a CONFORMANCE review of {subject}." If the request is really about reasoning quality,
efficacy, tool correctness, or persistence, STOP and route to the right skill (or `review-general`).

## Step 1 — treat priors as priors
The prior-context is PRIORS only. The deterministic facts below are ground truth; if a prior
conflicts with this run's facts, the facts win. Treat "(unconfirmed)" insights cautiously.

## Step 2 — pull the deterministic facts
Call `get_strategy_conformance_runs()` (sweep — runs newer than the watermark) or
`get_strategy_conformance_runs(subject="<run_id>")` (one run). For each run you get
`run_severity` and a `rules` list; each rule has `status`
(`conformant | violated | unverifiable`), `severity`, `detail`, `evidence`. The numbers are
already computed against the strategy in force when the run ran — do not recompute them.

## Step 3 — interpret, don't recompute
Read each rule's `status`/`evidence` and explain the run in plain terms:
- `violated` + `fail` (anti_churn, stops_present, regime_gate) → a hard discipline breach. Name the
  specific trade(s) from `evidence`.
- `violated` + `warn` (position_count, factor_weights_conformance) → a soft slip. Note it; don't
  inflate it to a fail.
- `unverifiable` → say plainly what couldn't be checked and why (from `detail`); it must NOT lower
  the verdict to a fail, only the confidence.
A clean run (all `conformant`, the rest `unverifiable`) is a `pass`.

## Step 4 — verdict
Use the tool's `run_severity` as your severity (do not soften a computed `fail`). Record it:
`write_review(review_type="conformance", subject="<run/date>", verdict="<prose with the specific
violating trades + which rules were unverifiable and why>", severity="<pass|info|warn|fail>",
confidence=<0-1, lower it when key rules were unverifiable>, evidence_refs={"run_id":..., "rules":...})`.

## Step 5 — consolidate (REQUIRED)
- For each RECURRING or MATERIALLY SIGNIFICANT finding, call
  `record_insight(text="<standing observation>", source_review_ids=[<this + related ids>])`.
  Discard one-off noise.
- Update the index headline: `write_reviewer_memory(scope="index", value={...})` — one-line
  summary + count + last-seen for "conformance".
- If a finding generalizes to ALL review types, call `promote_to_global(text, justification,
  corroborating_review_ids)` (requires ≥ 2 reviews).
- Write only via the bound scopes — never a raw namespace, never another task's detail.

## Step 6 — advance the watermark
For each run reviewed, call `mark_run_reviewed(run_id, start_time)` so a re-run audits only new runs.

## What this skill does NOT check
- Process / tool sequence → `review-tool-fidelity`.  · Persistence of effects → `review-operation-success`.
- Reasoning quality → `review-decision-quality`.       · Did it make money → `review-strategy-efficacy`.

## v1 limits (honest degradation, by design)
- `risk_limit_leak` (size/exposure/daily-loss/earnings) is `unverifiable` in v1 — needs point-in-time
  equity / earnings not durably stored (see `PROPOSAL-strategy-spec.md`).
- `regime_gate` checks the hard-block only; the caution-tier size-reduction is deferred.
- `sell_justification` / `ai_soft_caps` are `unverifiable` — the inputs aren't persisted.
- Thresholds come from the declared, effective-dated spec resolved by the tool — never hardcode them here.
````

- [ ] **Step 2: Sanity-check the skill file shape**

Run: `cd agent && python -c "import pathlib,yaml; t=pathlib.Path('src/review_agent/skills/review-strategy-conformance/SKILL.md').read_text(); fm=t.split('---')[1]; d=yaml.safe_load(fm); assert d['name']=='review-strategy-conformance' and d['memory_namespace']=='conformance'; print('SKILL frontmatter OK')"`
Expected: prints `SKILL frontmatter OK`.

- [ ] **Step 3: Commit**

```bash
git add agent/src/review_agent/skills/review-strategy-conformance/SKILL.md
git commit -m "docs(reviewer): rewrite review-strategy-conformance skill (trace x DB join)"
```

---

## Task 7: Post-deploy checks + test-prod note

**Files:**
- Modify: `POSTDEPLOY_CHECK.md` (add a Pending Verification block)
- Modify: `docs/REVIEWER-TEST-PROD.md` (append a `## 3. review-strategy-conformance` section above the "(future skills append here)" marker)

**Interfaces:** none (docs only).

- [ ] **Step 1: Add the POSTDEPLOY verification block**

Append to the `## Pending Verification` section of `POSTDEPLOY_CHECK.md`:

```markdown
### review-strategy-conformance (rebuilt, trace-native) — first exercised on the next conformance review run
- [ ] A clean run → `pass`; a run that sold inside the 5-day min hold (non-`bracket_fill`) → `fail` citing the trade.
- [ ] A `bracket_fill` stop/TP exit inside 5 days does NOT trip anti_churn.
- [ ] `position_count` warns (not fails) when > 8 open positions point-in-time.
- [ ] `stops_present` fails a buy with NULL `stop_loss_price`.
- [ ] `factor_weights_conformance` flags a run that scored with weights ≠ active `factor_weights`; reports `unverifiable` if weights changed after the run.
- [ ] `regime_gate` fails a buy during a recorded hard-block regime (VIX>26 & breadth<30); `unverifiable` when no regime in-window.
- [ ] `risk_limit_leak` / `sell_justification` / `ai_soft_caps` always `unverifiable` — never push severity to `fail`.
- [ ] A dead/error `query_database` probe yields empty history and a `pass`/`info` run — never a false `fail`.
- [ ] `conformance` watermark advances; a re-run audits only new runs.
```

- [ ] **Step 2: Append the test-prod catch-up note**

Insert above the `## (future skills append here)` line in `docs/REVIEWER-TEST-PROD.md`:

```markdown
## 3. `review-strategy-conformance` (rebuilt 2026-06-25; validated locally, not yet on cloud)

**What it does:** Audits whether a run obeyed the DECLARED strategy, point-in-time. Deterministic
facts from `get_strategy_conformance_runs` (trace for run identity/window × `trades` ledger + 3
memory snapshots); the LLM judges severity and writes the verdict. Anchored to an effective-dated
`STRATEGY_SPEC_VERSIONS` so it survives the strategy changing — no thresholds in the markdown.

**How to test:** *"Run a conformance review of run `<run_id>`."* Inspect the new `agent_reviews` row
+ the `rules` facts it cited.

### ✅ What good looks like
- An `agent_reviews` row, `review_type='conformance'`, with per-rule facts in `evidence_refs`.
- Hard breach (early discretionary sell / missing stop / buy in hard-block regime) → `fail` naming
  the trade. Soft slip (>8 positions, stale weights) → `warn`. Clean → `pass`.
- `conformance` watermark advanced; a re-run audits only new runs.

### 🚩 Red flags
- **A false fail off missing/changed data.** `risk_limit_leak`, `sell_justification`, `ai_soft_caps`
  must read `unverifiable`; a dead probe must yield `pass`/`info`, never `fail`.
- **Hardcoded thresholds.** Verdicts must trace to the resolved declared spec, not numbers in the
  markdown. If the strategy's `max_positions`/min-hold change, only `STRATEGY_SPEC_VERSIONS` should.
- **bracket_fill exits tripping anti_churn.** Stop/TP exits are exempt from the min-hold rule.
- **Auditing the wrong graph / an in-progress run.** Only finished `autonomous_loop` runs.

### ⚠️ Known gotchas / limits (by design)
- v1 defers `risk_limit_leak` (needs point-in-time equity/earnings), the regime caution-tier, and
  the rank/AI-cap rules — all `unverifiable`. See `PROPOSAL-strategy-spec.md` for the shared-spec fix.
- Trading-day counting is weekday-based (ignores market holidays).
- Memory snapshots (`factor_weights`/`factor_rankings`/`market_regime`) are current values; checks
  degrade to `unverifiable` when they changed after the run rather than guessing.

### Open follow-ups (track, not blockers)
- Same reviewer-table migration prereq as everything else (see setup).
- `PROPOSAL-strategy-spec.md`: shared declarative strategy spec (trader enforces + reviewer audits) —
  would make the deferred rules verifiable and eliminate the reviewer's second-copy drift.
```

- [ ] **Step 3: Run the full conformance suite once more**

Run: `cd agent && python -m pytest tests/test_strategy_conformance_*.py tests/test_review_tools_boundary.py -v`
Expected: PASS (all conformance pure + tool tests + boundary test green).

- [ ] **Step 4: Commit**

```bash
git add agent/POSTDEPLOY_CHECK.md agent/docs/REVIEWER-TEST-PROD.md
git commit -m "docs(reviewer): post-deploy + test-prod notes for review-strategy-conformance"
```

---

## Self-Review

**Spec coverage** (against `2026-06-19-review-strategy-conformance-design.md`):
- §2 spec-anchoring / point-in-time → Task 1 `resolve_spec` (effective-dated) + Task 5 stale-source `unverifiable` wiring. ✅
- §3 evidence model (trace window × trades + 30d trailing, reconstruction) → Task 2 reconstruction, Task 5 SQL + window split. ✅
- §4 check registry → Tasks 3–4 (5 verified evaluators + 3 unverifiable via `classify_conformance`). **Deviation:** `risk_limit_leak` and the regime caution-tier are `unverifiable` in v1 — documented in Global Constraints / v1 scoping and surfaced in the skill + test-prod note. ✅
- §5 status/severity (deterministic, unverifiable never raises, LLM can't soften a fail) → Task 1 `run_severity`, Task 6 skill Step 4. ✅
- §6 coverage guarantee → Task 4 runtime `classify_emits_exactly_the_known_rule_set` + Task 1 static partition + the `_EVALUATORS` dev-time assert. ✅
- §7 watermark/sweep reuse → Task 5 reuses `select_unreviewed`/`is_finished`/`_read_watermark`; Task 6 Step 6 `mark_run_reviewed`. ✅
- §8 components / boundary → Tasks 1–6; boundary test re-run in Task 5. ✅

**Placeholder scan:** No TBD/TODO; every code step shows full code; every test shows real assertions. ✅

**Type consistency:** `_fact(rule,status,severity,detail,evidence)` shape is used identically across Tasks 1/3/4; `context` keys produced by Task 5 match those consumed in Tasks 3/4; `run_severity` imported into `tools.py` aliased to `conformance_run_severity` to avoid the existing `run_severity` name from operation-success; tool returns `{"runs":[{...,"rules":[...]}],"skipped_in_progress":[...]}` consumed by the skill Step 2/3. ✅
