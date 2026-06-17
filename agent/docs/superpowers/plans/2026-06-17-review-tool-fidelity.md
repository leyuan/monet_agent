# review-tool-fidelity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild `review-tool-fidelity` as a trace-native process-adherence audit where a deterministic tool computes the facts and the LLM only interprets/judges/consolidates.

**Architecture:** Pure analysis logic (invariants, phase ID, fact extraction, watermark cursor) lives in a new `review_agent/tool_fidelity.py` and is fully unit-testable on fabricated trace dicts. Thin I/O wrappers extend `trace.py` (graph-filtered LangSmith reads) and `db.py` (code-managed watermark). Two new reviewer tools expose run-resolution+analysis and watermark-advance. The `SKILL.md` carries only the behavioral contract.

**Tech Stack:** Python 3.13, pytest, langsmith SDK, Supabase (via `common.supabase_client`), deepagents.

**Spec:** `agent/docs/superpowers/specs/2026-06-17-review-tool-fidelity-design.md`

## Global Constraints

- All commands run from `agent/`. Tests: `python -m pytest tests/<file> -v`.
- The reviewer is **read-only on the trader** and writes ONLY to `agent_reviews` + `reviewer_memory`. New tools must not add any trading/mutating capability (enforced by `tests/test_review_tools_boundary.py`).
- Trader graph name in LangSmith = `autonomous_loop`; chat = `monet_agent`; reviewer = `review_agent`. The reviewer audits **only `autonomous_loop`**.
- Trader tool names (exact): `score_universe`, `enrich_eps_revisions`, `generate_factor_rankings`, `place_order`, `record_decision`, `write_journal_entry`, `update_stock_analysis`, `record_daily_snapshot`, `update_market_regime`, `check_live_vs_backtest_divergence`, `audit_factor_ic`, `suggest_factor_weight_adjustment`.
- Memory JSON shapes are **code-enforced, never restated in the SKILL.md** (spec §5 note).
- DB-touching tests are integration (gated by `RUN_DB_INTEGRATION=1`); pure-logic tests are not. Default to pure unit tests; only Task 5/7 touch DB/LangSmith.
- Date is unavailable as `Date.now()` in plan code — pass timestamps in explicitly. (Codebase uses `date.today().isoformat()` in tools.)

---

### Task 1: Per-phase invariants + phase identification (pure)

**Files:**
- Create: `agent/src/review_agent/tool_fidelity.py`
- Test: `agent/tests/test_tool_fidelity_phase.py`

**Interfaces:**
- Produces: `PHASE_INVARIANTS: dict[str, dict]`, `identify_phase(run: dict, *, weekend: bool) -> str`.
  - `run` is one element of `read_run_trace(...)["runs"]`: `{"run_id","name","start_time","error","tool_calls":[{"name","error",...}]}`.
  - phase ∈ `{"factor_loop_weekday","factor_loop_weekend","reflection","weekly_review","unknown"}`.

- [ ] **Step 1: Write the failing test**

```python
# agent/tests/test_tool_fidelity_phase.py
from review_agent.tool_fidelity import identify_phase, PHASE_INVARIANTS


def _run(tool_names):
    return {"run_id": "r", "name": "autonomous_loop", "start_time": "2026-06-17T14:00:00",
            "error": None, "tool_calls": [{"name": n, "error": None} for n in tool_names]}


def test_weekly_review_identified_by_audit_factor_ic():
    assert identify_phase(_run(["audit_factor_ic", "write_journal_entry"]), weekend=False) == "weekly_review"


def test_weekend_factor_loop():
    assert identify_phase(_run(["score_universe", "generate_factor_rankings"]), weekend=True) == "factor_loop_weekend"


def test_weekday_factor_loop():
    assert identify_phase(_run(["score_universe", "generate_factor_rankings", "place_order"]), weekend=False) == "factor_loop_weekday"


def test_reflection_no_scoring():
    assert identify_phase(_run(["check_live_vs_backtest_divergence", "write_journal_entry"]), weekend=False) == "reflection"


def test_unknown_when_no_signature():
    assert identify_phase(_run(["read_agent_memory"]), weekend=False) == "unknown"


def test_every_phase_has_an_invariant_entry():
    for p in ["factor_loop_weekday", "factor_loop_weekend", "reflection", "weekly_review", "unknown"]:
        assert p in PHASE_INVARIANTS
        entry = PHASE_INVARIANTS[p]
        assert set(entry) == {"required", "forbidden", "order", "terminal"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_tool_fidelity_phase.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'review_agent.tool_fidelity'`.

- [ ] **Step 3: Write minimal implementation**

```python
# agent/src/review_agent/tool_fidelity.py
"""Pure tool-fidelity logic: phase identification, per-phase invariants, deterministic
fact extraction from a run trace, and the watermark cursor. No I/O — all functions take
plain dicts and return plain dicts so they unit-test without LangSmith or Supabase.
"""

# Per-phase process invariants for the trader (autonomous_loop).
#   required  : tools that MUST appear at least once (unconditional steps only —
#               conditional tools like place_order are covered by `order`, not `required`).
#   forbidden : tools that must NOT appear in this phase.
#   order     : (A, B) pairs — if both present, every A must precede every B.
#   terminal  : tools the run should end with (the last tool call should be one of these).
PHASE_INVARIANTS = {
    "factor_loop_weekday": {
        "required": ["score_universe", "generate_factor_rankings"],
        "forbidden": [],
        "order": [("generate_factor_rankings", "place_order"), ("place_order", "record_decision")],
        "terminal": ["write_journal_entry", "record_daily_snapshot"],
    },
    "factor_loop_weekend": {
        "required": ["score_universe", "generate_factor_rankings", "write_journal_entry"],
        "forbidden": ["place_order"],
        "order": [],
        "terminal": ["write_journal_entry"],
    },
    "reflection": {
        "required": ["write_journal_entry"],
        "forbidden": ["place_order", "score_universe"],
        "order": [],
        "terminal": ["write_journal_entry"],
    },
    "weekly_review": {
        "required": ["audit_factor_ic", "write_journal_entry"],
        "forbidden": ["place_order"],
        "order": [],
        "terminal": ["write_journal_entry"],
    },
    "unknown": {"required": [], "forbidden": [], "order": [], "terminal": []},
}


def identify_phase(run: dict, *, weekend: bool) -> str:
    """Deterministic heuristic from the tool calls + weekday/weekend. Returns 'unknown'
    when no signature matches (which limits checks to generic ones — honest degradation)."""
    names = {c.get("name") for c in run.get("tool_calls", [])}
    if "audit_factor_ic" in names:
        return "weekly_review"
    if "score_universe" in names:
        return "factor_loop_weekend" if weekend else "factor_loop_weekday"
    if "check_live_vs_backtest_divergence" in names or (
        "write_journal_entry" in names and "place_order" not in names
    ):
        return "reflection"
    return "unknown"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_tool_fidelity_phase.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add agent/src/review_agent/tool_fidelity.py agent/tests/test_tool_fidelity_phase.py
git commit -m "feat(reviewer): tool-fidelity phase ID + per-phase invariants (pure)"
```

---

### Task 2: Deterministic fact extraction `analyze_tool_fidelity` (pure)

**Files:**
- Modify: `agent/src/review_agent/tool_fidelity.py`
- Test: `agent/tests/test_tool_fidelity_analysis.py`

**Interfaces:**
- Consumes: `PHASE_INVARIANTS` (Task 1).
- Produces: `analyze_tool_fidelity(run: dict, phase: str) -> dict` returning the Tier-A/B fact set:
  `{phase, run_completed, total_calls, failed_calls, success_rate, invariant_violations[], per_tool_errors[], recovery[], redundant_calls[], runtime_ms, token_usage}`.
  - A tool call is **failed** iff its `error` field is truthy (spec §3d) — a structured "rejected" in `outputs` is NOT a failure.
  - `invariant_violations` entries: `{"type": "missing_required"|"forbidden_present"|"order_violation"|"missing_terminal", "detail": str}`.
  - `recovery` entries (per errored call): `{"tool", "action": "retried_ok"|"retried_failed"|"swallowed"}`.

- [ ] **Step 1: Write the failing test**

```python
# agent/tests/test_tool_fidelity_analysis.py
from review_agent.tool_fidelity import analyze_tool_fidelity


def _call(name, error=None, start=None, end=None, outputs=None):
    return {"name": name, "error": error, "inputs": {}, "outputs": outputs or {},
            "start_time": start, "end_time": end}


def _run(calls, run_error=None, total_tokens=None):
    return {"run_id": "r", "name": "autonomous_loop", "start_time": "2026-06-17T14:00:00",
            "error": run_error, "total_tokens": total_tokens, "tool_calls": calls}


def test_clean_factor_loop_passes_all_invariants():
    run = _run([_call("score_universe"), _call("generate_factor_rankings"),
                _call("place_order"), _call("record_decision"), _call("write_journal_entry")])
    f = analyze_tool_fidelity(run, "factor_loop_weekday")
    assert f["invariant_violations"] == []
    assert f["success_rate"] == 1.0
    assert f["run_completed"] is True


def test_missing_required_step_flagged():
    run = _run([_call("place_order"), _call("write_journal_entry")])  # no score_universe/rankings
    f = analyze_tool_fidelity(run, "factor_loop_weekday")
    types = {v["type"] for v in f["invariant_violations"]}
    assert "missing_required" in types


def test_forbidden_tool_on_weekend():
    run = _run([_call("score_universe"), _call("generate_factor_rankings"),
                _call("place_order"), _call("write_journal_entry")])
    f = analyze_tool_fidelity(run, "factor_loop_weekend")
    assert any(v["type"] == "forbidden_present" and "place_order" in v["detail"]
               for v in f["invariant_violations"])


def test_order_violation_place_before_rankings():
    run = _run([_call("score_universe"), _call("place_order"),
                _call("generate_factor_rankings"), _call("write_journal_entry")])
    f = analyze_tool_fidelity(run, "factor_loop_weekday")
    assert any(v["type"] == "order_violation" for v in f["invariant_violations"])


def test_benign_reorder_not_flagged():
    # enrich before score (both independent reads) — no ordering invariant between them
    run = _run([_call("enrich_eps_revisions"), _call("score_universe"),
                _call("generate_factor_rankings"), _call("write_journal_entry")])
    f = analyze_tool_fidelity(run, "factor_loop_weekday")
    assert f["invariant_violations"] == []


def test_success_rate_and_per_tool_errors():
    run = _run([_call("get_quote", error="timeout"), _call("get_quote"),
                _call("score_universe"), _call("generate_factor_rankings"),
                _call("write_journal_entry")])
    f = analyze_tool_fidelity(run, "factor_loop_weekday")
    assert f["total_calls"] == 5 and f["failed_calls"] == 1
    assert abs(f["success_rate"] - 0.8) < 1e-9
    assert any(e["tool"] == "get_quote" and e["count"] == 1 for e in f["per_tool_errors"])


def test_recovery_retried_ok():
    run = _run([_call("get_quote", error="timeout"), _call("get_quote"),
                _call("score_universe"), _call("generate_factor_rankings"),
                _call("write_journal_entry")])
    f = analyze_tool_fidelity(run, "factor_loop_weekday")
    assert {"tool": "get_quote", "action": "retried_ok"} in f["recovery"]


def test_recovery_swallowed_when_no_retry():
    run = _run([_call("score_universe"), _call("generate_factor_rankings"),
                _call("place_order", error="broker 500"), _call("write_journal_entry")])
    f = analyze_tool_fidelity(run, "factor_loop_weekday")
    assert {"tool": "place_order", "action": "swallowed"} in f["recovery"]


def test_run_not_completed_when_root_errored():
    run = _run([_call("score_universe")], run_error="GraphRecursionError")
    f = analyze_tool_fidelity(run, "factor_loop_weekday")
    assert f["run_completed"] is False


def test_redundant_calls_flagged():
    run = _run([_call("score_universe"), _call("score_universe"), _call("score_universe"),
                _call("generate_factor_rankings"), _call("write_journal_entry")])
    f = analyze_tool_fidelity(run, "factor_loop_weekday")
    assert any(r["tool"] == "score_universe" and r["count"] == 3 for r in f["redundant_calls"])


def test_empty_trace_zero_calls_no_crash():
    f = analyze_tool_fidelity(_run([]), "unknown")
    assert f["total_calls"] == 0 and f["success_rate"] == 1.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_tool_fidelity_analysis.py -v`
Expected: FAIL — `ImportError: cannot import name 'analyze_tool_fidelity'`.

- [ ] **Step 3: Write minimal implementation** (append to `tool_fidelity.py`)

```python
from collections import Counter

# Tools that legitimately repeat within a run (don't flag as redundant).
_REPEATABLE = {"place_order", "record_decision", "update_stock_analysis", "get_quote"}
_REDUNDANT_THRESHOLD = 2  # a non-repeatable tool called > this many times is wasteful


def _parse_ms(start: str | None, end: str | None) -> int | None:
    if not start or not end:
        return None
    from datetime import datetime
    try:
        return int((datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds() * 1000)
    except (ValueError, TypeError):
        return None


def analyze_tool_fidelity(run: dict, phase: str) -> dict:
    calls = run.get("tool_calls", [])
    names = [c.get("name") for c in calls]
    inv = PHASE_INVARIANTS.get(phase, PHASE_INVARIANTS["unknown"])
    present = set(names)

    violations = []
    for req in inv["required"]:
        if req not in present:
            violations.append({"type": "missing_required", "detail": req})
    for fb in inv["forbidden"]:
        if fb in present:
            violations.append({"type": "forbidden_present", "detail": fb})
    for a, b in inv["order"]:
        if a in present and b in present:
            # every A must precede every B → last A index must be < first B index
            if max(i for i, n in enumerate(names) if n == a) > min(i for i, n in enumerate(names) if n == b):
                violations.append({"type": "order_violation", "detail": f"{a} must precede {b}"})
    if inv["terminal"] and names and names[-1] not in inv["terminal"]:
        violations.append({"type": "missing_terminal",
                           "detail": f"run ended with {names[-1]}, expected one of {inv['terminal']}"})

    total = len(calls)
    failed = sum(1 for c in calls if c.get("error"))
    per_tool_errors = [{"tool": t, "error": "see trace", "count": n}
                       for t, n in Counter(c.get("name") for c in calls if c.get("error")).items()]

    # recovery: for each errored call, did a later same-tool call succeed / fail / never happen?
    recovery = []
    for idx, c in enumerate(calls):
        if not c.get("error"):
            continue
        later = [x for x in calls[idx + 1:] if x.get("name") == c.get("name")]
        if not later:
            recovery.append({"tool": c.get("name"), "action": "swallowed"})
        elif any(not x.get("error") for x in later):
            recovery.append({"tool": c.get("name"), "action": "retried_ok"})
        else:
            recovery.append({"tool": c.get("name"), "action": "retried_failed"})

    redundant = [{"tool": t, "count": n} for t, n in Counter(names).items()
                 if t not in _REPEATABLE and n > _REDUNDANT_THRESHOLD]

    durations = [d for d in (_parse_ms(c.get("start_time"), c.get("end_time")) for c in calls) if d]
    return {
        "phase": phase,
        "run_completed": run.get("error") is None,
        "total_calls": total,
        "failed_calls": failed,
        "success_rate": (total - failed) / total if total else 1.0,
        "invariant_violations": violations,
        "per_tool_errors": per_tool_errors,
        "recovery": recovery,
        "redundant_calls": redundant,
        "runtime_ms": sum(durations) if durations else None,
        "token_usage": run.get("total_tokens"),
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_tool_fidelity_analysis.py -v`
Expected: PASS (11 tests).

- [ ] **Step 5: Commit**

```bash
git add agent/src/review_agent/tool_fidelity.py agent/tests/test_tool_fidelity_analysis.py
git commit -m "feat(reviewer): deterministic tool-fidelity fact extraction (Tier-A/B)"
```

---

### Task 3: Watermark cursor logic (pure)

**Files:**
- Modify: `agent/src/review_agent/tool_fidelity.py`
- Test: `agent/tests/test_tool_fidelity_watermark.py`

**Interfaces:**
- Produces:
  - `select_unreviewed(roots: list[dict], cursor: dict | None, *, cold_start_n: int) -> list[dict]` — roots are `{"run_id","start_time",...}` newest-first; returns the ones to review (oldest-first). Cold start (cursor None) → most recent `cold_start_n`. Otherwise → roots whose `run_id` not in `cursor["reviewed_run_ids"]`.
  - `advance_cursor(cursor: dict | None, run_id: str, start_time: str, *, baseline: dict | None = None, cap: int = 50) -> dict` — returns a new cursor with `run_id` prepended to `reviewed_run_ids` (capped), `last_reviewed_start_time` updated, `graph` stamped, optional `baseline` merged.

- [ ] **Step 1: Write the failing test**

```python
# agent/tests/test_tool_fidelity_watermark.py
from review_agent.tool_fidelity import select_unreviewed, advance_cursor


def _roots(ids):  # newest-first
    return [{"run_id": i, "start_time": f"2026-06-17T1{n}:00:00"} for n, i in enumerate(ids)]


def test_cold_start_returns_most_recent_n_oldest_first():
    roots = _roots(["c", "b", "a"])  # c newest
    out = select_unreviewed(roots, None, cold_start_n=2)
    assert [r["run_id"] for r in out] == ["b", "c"]  # 2 most recent, oldest-first


def test_skips_already_reviewed():
    roots = _roots(["c", "b", "a"])
    cursor = {"reviewed_run_ids": ["a", "b"]}
    out = select_unreviewed(roots, cursor, cold_start_n=5)
    assert [r["run_id"] for r in out] == ["c"]


def test_late_arrival_older_run_still_reviewed_if_unseen():
    # 'a' arrives late (older start_time) but was never reviewed → still selected
    roots = _roots(["c", "b", "a"])
    cursor = {"reviewed_run_ids": ["c", "b"], "last_reviewed_start_time": "2026-06-17T11:00:00"}
    out = select_unreviewed(roots, cursor, cold_start_n=5)
    assert [r["run_id"] for r in out] == ["a"]


def test_advance_prepends_and_caps():
    cur = advance_cursor(None, "r1", "2026-06-17T10:00:00")
    cur = advance_cursor(cur, "r2", "2026-06-17T11:00:00", baseline={"runtime_ms_p50": 100})
    assert cur["reviewed_run_ids"][0] == "r2"
    assert cur["graph"] == "autonomous_loop"
    assert cur["last_reviewed_start_time"] == "2026-06-17T11:00:00"
    assert cur["baseline"]["runtime_ms_p50"] == 100


def test_advance_respects_cap():
    cur = None
    for n in range(60):
        cur = advance_cursor(cur, f"r{n}", "2026-06-17T10:00:00", cap=50)
    assert len(cur["reviewed_run_ids"]) == 50
    assert cur["reviewed_run_ids"][0] == "r59"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_tool_fidelity_watermark.py -v`
Expected: FAIL — `ImportError: cannot import name 'select_unreviewed'`.

- [ ] **Step 3: Write minimal implementation** (append to `tool_fidelity.py`)

```python
_GRAPH = "autonomous_loop"


def select_unreviewed(roots: list[dict], cursor: dict | None, *, cold_start_n: int) -> list[dict]:
    """roots newest-first. Returns runs to review, OLDEST-first (so the watermark advances
    monotonically as each is processed)."""
    if cursor is None:
        chosen = roots[:cold_start_n]
    else:
        seen = set(cursor.get("reviewed_run_ids", []))
        chosen = [r for r in roots if r["run_id"] not in seen]
    return list(reversed(chosen))


def advance_cursor(cursor: dict | None, run_id: str, start_time: str, *,
                   baseline: dict | None = None, cap: int = 50) -> dict:
    cursor = dict(cursor or {})
    ids = [run_id, *cursor.get("reviewed_run_ids", [])][:cap]
    out = {
        "graph": _GRAPH,
        "last_reviewed_start_time": start_time,
        "reviewed_run_ids": ids,
        "baseline": {**cursor.get("baseline", {}), **(baseline or {})},
    }
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_tool_fidelity_watermark.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add agent/src/review_agent/tool_fidelity.py agent/tests/test_tool_fidelity_watermark.py
git commit -m "feat(reviewer): tool-fidelity watermark cursor (cold-start, late-arrival, cap)"
```

---

### Task 4: Extend `read_run_trace` — graph filter + targeting + richer fields

**Files:**
- Modify: `agent/src/review_agent/trace.py`
- Test: `agent/tests/test_read_run_trace_filter.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `read_run_trace(run_id=None, graph_name="autonomous_loop", limit=5, config=None)` — filters root runs to `graph_name` (excludes `review_agent`/`monet_agent`), and each `tool_call` now includes `start_time`/`end_time`; each run includes `total_tokens`. Plus a pure helper `select_roots_by_name(roots, graph_name, limit)` for unit testing the filter.

- [ ] **Step 1: Write the failing test** (pure helper only — no LangSmith I/O)

```python
# agent/tests/test_read_run_trace_filter.py
from review_agent.trace import select_roots_by_name


class _Root:
    def __init__(self, name, rid):
        self.name = name; self.id = rid


def test_filters_to_trader_graph_excludes_reviewer():
    roots = [_Root("review_agent", "x"), _Root("autonomous_loop", "a"),
             _Root("monet_agent", "m"), _Root("autonomous_loop", "b")]
    out = select_roots_by_name(roots, "autonomous_loop", limit=5)
    assert [r.id for r in out] == ["a", "b"]


def test_limit_applied_after_filter():
    roots = [_Root("autonomous_loop", "a"), _Root("review_agent", "x"),
             _Root("autonomous_loop", "b"), _Root("autonomous_loop", "c")]
    out = select_roots_by_name(roots, "autonomous_loop", limit=2)
    assert [r.id for r in out] == ["a", "b"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_read_run_trace_filter.py -v`
Expected: FAIL — `ImportError: cannot import name 'select_roots_by_name'`.

- [ ] **Step 3: Write minimal implementation** — replace the body of `trace.py` with:

```python
"""Read-only LangSmith trace evidence for the reviewer.

Reads the TRADING agent's run traces (tool calls + timing + errors) as evidence.
Project name comes from LANGSMITH_PROJECT. The reviewer only READS LangSmith.
"""
import os

from langsmith import Client


def select_roots_by_name(roots, graph_name: str, limit: int):
    """Pure: keep only roots whose name == graph_name (excludes reviewer/chat runs),
    preserving order, capped at limit."""
    return [r for r in roots if r.name == graph_name][:limit]


def read_run_trace(run_id: str | None = None, graph_name: str = "autonomous_loop",
                   limit: int = 5, config=None) -> dict:
    """Fetch trader run trace(s). Filters to `graph_name` (the trader graph) so the
    reviewer never audits its own or the chat graph's runs. `config` is accepted and
    ignored (runtime-injected; keeps the tool signature uniform)."""
    project = os.environ.get("LANGSMITH_PROJECT", "monet_agent")
    client = Client()

    if run_id:
        roots = [client.read_run(run_id)]
    else:
        # over-fetch then filter by name (a mixed project holds several graphs)
        raw = list(client.list_runs(project_name=project, is_root=True, limit=max(limit * 5, 25)))
        roots = select_roots_by_name(raw, graph_name, limit)

    runs_out = []
    for root in roots:
        children = list(client.list_runs(project_name=project, trace_id=root.trace_id))
        tool_calls = [
            {"name": c.name, "inputs": c.inputs, "outputs": c.outputs, "error": c.error,
             "start_time": str(c.start_time) if c.start_time else None,
             "end_time": str(c.end_time) if c.end_time else None}
            for c in children if c.run_type == "tool"
        ]
        runs_out.append({
            "run_id": str(root.id), "name": root.name, "start_time": str(root.start_time),
            "error": root.error, "total_tokens": getattr(root, "total_tokens", None),
            "tool_calls": tool_calls,
        })
    return {"project": project, "runs": runs_out}
```

> Implementation note: confirm `root.total_tokens` is the correct attribute on the installed `langsmith` `Run` object; if it lives under `root.extra` or `prompt_tokens`/`completion_tokens`, adjust the `getattr` line. Token usage is Tier-B (best-effort) so a `None` here does not break the skill.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_read_run_trace_filter.py tests/test_review_trace.py -v`
Expected: PASS (the new filter tests + the existing trace tests still green).

- [ ] **Step 5: Commit**

```bash
git add agent/src/review_agent/trace.py agent/tests/test_read_run_trace_filter.py
git commit -m "fix(reviewer): read_run_trace filters to trader graph + adds timing/tokens"
```

---

### Task 5: Watermark DB helpers + two reviewer tools

**Files:**
- Modify: `agent/src/review_agent/db.py` (watermark read/advance, code-managed)
- Modify: `agent/src/review_agent/tools.py` (two new tools + REVIEW_TOOLS)
- Test: `agent/tests/test_tool_fidelity_tools.py`, and extend `tests/test_review_tools_boundary.py`

**Interfaces:**
- Consumes: `read_run_trace` (Task 4), `identify_phase`/`analyze_tool_fidelity` (Tasks 1–2), `select_unreviewed`/`advance_cursor` (Task 3), `get_active_review` (db.py).
- Produces:
  - db: `read_watermark(review_type: str) -> dict | None`, `write_watermark(review_type: str, cursor: dict) -> None` (direct upsert, like `append_routing_log`).
  - tools: `get_tool_fidelity_runs(subject: str | None = None, config=None) -> dict` and `mark_run_reviewed(run_id: str, start_time: str, config=None) -> dict`; both added to `REVIEW_TOOLS`.

- [ ] **Step 1: Write the failing test** (mock the I/O boundaries; assert wiring + boundary)

```python
# agent/tests/test_tool_fidelity_tools.py
import review_agent.tools as T

FAKE_CONFIG = {"configurable": {"thread_id": "t1"}}

_TRACE = {"runs": [
    {"run_id": "r1", "name": "autonomous_loop", "start_time": "2026-06-17T14:00:00",
     "error": None, "total_tokens": 100,
     "tool_calls": [{"name": "score_universe", "error": None},
                    {"name": "generate_factor_rankings", "error": None},
                    {"name": "write_journal_entry", "error": None}]},
]}


def test_get_runs_returns_analyzed_facts_for_unreviewed(monkeypatch):
    monkeypatch.setattr(T, "_get_active", lambda tid: "tool_fidelity")
    monkeypatch.setattr(T, "read_run_trace", lambda **k: _TRACE)
    monkeypatch.setattr(T, "_read_watermark", lambda rt: None)  # cold start
    out = T.get_tool_fidelity_runs(config=FAKE_CONFIG)
    assert out["runs"][0]["run_id"] == "r1"
    assert out["runs"][0]["facts"]["phase"] in ("factor_loop_weekday", "factor_loop_weekend")
    assert out["runs"][0]["facts"]["invariant_violations"] == []


def test_get_runs_requires_active_review(monkeypatch):
    monkeypatch.setattr(T, "_get_active", lambda tid: None)
    import pytest
    with pytest.raises(ValueError):
        T.get_tool_fidelity_runs(config=FAKE_CONFIG)


def test_mark_run_reviewed_advances_watermark(monkeypatch):
    monkeypatch.setattr(T, "_get_active", lambda tid: "tool_fidelity")
    monkeypatch.setattr(T, "_read_watermark", lambda rt: None)
    captured = {}
    monkeypatch.setattr(T, "_write_watermark", lambda rt, cur: captured.update(rt=rt, cur=cur))
    T.mark_run_reviewed("r1", "2026-06-17T14:00:00", config=FAKE_CONFIG)
    assert captured["rt"] == "tool_fidelity"
    assert "r1" in captured["cur"]["reviewed_run_ids"]


def test_new_tools_registered_and_no_trading_tools():
    names = {getattr(t, "__name__", getattr(t, "name", "")) for t in T.REVIEW_TOOLS}
    assert {"get_tool_fidelity_runs", "mark_run_reviewed"} <= names
    assert "place_order" not in names  # boundary intact
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_tool_fidelity_tools.py -v`
Expected: FAIL — `AttributeError: module 'review_agent.tools' has no attribute 'get_tool_fidelity_runs'`.

- [ ] **Step 3: Write minimal implementation**

In `db.py`, add (after `append_routing_log`):

```python
def read_watermark(review_type: str) -> dict | None:
    """Read the code-managed tool-fidelity cursor for a review type."""
    mem = read_reviewer_memory(f"{review_type}:watermark")
    return mem["value"] if (mem and isinstance(mem.get("value"), dict)) else None


def write_watermark(review_type: str, cursor: dict) -> None:
    """Upsert the cursor directly (NOT via write_reviewer_memory) so it doesn't accrue
    version history — it is operational state, not an insight. Mirrors append_routing_log."""
    sb = get_supabase()
    sb.table("reviewer_memory").upsert(
        {"namespace": f"{review_type}:watermark", "value": cursor, "updated_at": "now()"},
        on_conflict="namespace",
    ).execute()
```

In `tools.py`, add imports + tools and register them:

```python
# add to the existing review_agent.db import block:
from review_agent.db import (
    read_watermark as _read_watermark,
    write_watermark as _write_watermark,
)
# add near the other imports:
from review_agent.tool_fidelity import (
    identify_phase, analyze_tool_fidelity, select_unreviewed, advance_cursor,
)
from datetime import datetime as _dt

_COLD_START_N = 3


def _is_weekend(start_time: str) -> bool:
    try:
        return _dt.fromisoformat(start_time).weekday() >= 5
    except (ValueError, TypeError):
        return False


def get_tool_fidelity_runs(subject: str | None = None, config: RunnableConfig = None) -> dict:
    """Resolve the trader runs to audit and return their DETERMINISTIC tool-fidelity facts.

    Sweep mode (subject is None): returns runs newer than the tool-fidelity watermark.
    Explicit mode (subject is a run_id): returns just that run. You INTERPRET the facts,
    write a verdict per run with write_review, then call mark_run_reviewed(run_id, start_time).

    Returns: {"runs": [{"run_id","start_time","facts": {...}}]}.
    """
    rt = _get_active(_thread_id(config))
    if rt is None:
        raise ValueError("No active review — call begin_review first.")
    if subject:
        roots = read_run_trace(run_id=subject)["runs"]
    else:
        cursor = _read_watermark(rt)
        all_runs = read_run_trace(limit=10)["runs"]  # newest-first
        roots = select_unreviewed(all_runs, cursor, cold_start_n=_COLD_START_N)
    out = []
    for run in roots:
        phase = identify_phase(run, weekend=_is_weekend(run["start_time"]))
        out.append({"run_id": run["run_id"], "start_time": run["start_time"],
                    "facts": analyze_tool_fidelity(run, phase)})
    return {"runs": out}


def mark_run_reviewed(run_id: str, start_time: str, config: RunnableConfig = None) -> dict:
    """Advance the tool-fidelity watermark past a run. Call ONLY after its verdict is
    written (advance-on-success), so a failed review re-audits the run next time."""
    rt = _get_active(_thread_id(config))
    if rt is None:
        raise ValueError("No active review — call begin_review first.")
    cursor = advance_cursor(_read_watermark(rt), run_id, start_time)
    _write_watermark(rt, cursor)
    return {"status": "marked", "run_id": run_id}
```

Then add both to `REVIEW_TOOLS`:

```python
REVIEW_TOOLS = [
    query_database, read_agent_memory, read_all_agent_memory, get_performance_comparison,
    read_run_trace,
    begin_review, write_review, read_reviewer_memory, write_reviewer_memory,
    record_insight, promote_to_global,
    get_tool_fidelity_runs, mark_run_reviewed,
]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_tool_fidelity_tools.py tests/test_review_tools_boundary.py -v`
Expected: PASS (new wiring tests + boundary test still green).

- [ ] **Step 5: Commit**

```bash
git add agent/src/review_agent/db.py agent/src/review_agent/tools.py agent/tests/test_tool_fidelity_tools.py
git commit -m "feat(reviewer): tool-fidelity run-resolution + watermark tools"
```

---

### Task 6: Rewrite `review-tool-fidelity/SKILL.md` (behavioral only)

**Files:**
- Rewrite: `agent/src/review_agent/skills/review-tool-fidelity/SKILL.md`
- Test: `agent/tests/test_phase2_skills_wellformed.py` (confirm it still passes; extend if it asserts specific skills).

**Interfaces:** none (prose skill). Must reference the new tools and carry NO memory JSON.

- [ ] **Step 1: Confirm the well-formedness contract**

Run: `python -m pytest tests/test_phase2_skills_wellformed.py -v`
Expected: PASS currently (records the contract the rewrite must keep: valid frontmatter `name`/`description`, disjoint use/don't-use, steps present).

- [ ] **Step 2: Rewrite the skill** — replace the file contents with:

```markdown
---
name: review-tool-fidelity
description: >
  Audit whether an autonomous_loop run followed its prescribed tool choreography — required
  tools present, forbidden tools absent, dependency-ordering honoured, the run completed, errors
  recovered, and the tool-call success rate. Use when asked if the agent followed its process,
  skipped a step, called tools out of order, or whether tool calls are erroring. Do NOT use for
  whether operations completed/filled (use review-operation-success), hard-rule compliance (use
  review-strategy-conformance), reasoning or bias (use review-decision-quality), or strategy
  efficacy (use review-strategy-efficacy).
memory_namespace: tool_fidelity
memory_access: { read: own, write: own }
tags: [process, tools, trace]
---

# Review: Tool Fidelity

Audit process adherence for the trader (`autonomous_loop`), from its LangSmith trace. You judge
whether the prescribed tool choreography was followed — not outcomes, rules, or reasoning.

**Detection is deterministic — `get_tool_fidelity_runs` computes the facts.** Your job is to
INTERPRET those facts (is an error transient or real?), judge severity, and consolidate. Do not
eyeball the raw trace or re-count anything the tool already counted.

## Step 0 — begin + fit-check
Call `begin_review("tool_fidelity", subject="<run id / date / 'sweep'>", reason="<why tool-fidelity>")`
FIRST — it binds your memory and returns prior context. State: "Running a TOOL FIDELITY review of
{subject}." If the request is about whether operations *succeeded* (fills, snapshots saved), route
to `review-operation-success`; for rule compliance or reasoning, route accordingly or use
`review-general`.

## Step 1 — treat priors as priors
Prior context (standing skip/error patterns + recent verdicts) is PRIORS only. The freshly-computed
facts are ground truth; if a prior conflicts with this run's facts, the facts win. Treat
"(unconfirmed)" insights cautiously.

## Step 2 — get the facts
Call `get_tool_fidelity_runs()` (sweep — returns trader runs newer than your watermark) or
`get_tool_fidelity_runs(subject="<run_id>")` for a specific run. Each run returns:
`{run_id, start_time, facts}` where `facts` holds `phase`, `run_completed`, `invariant_violations`,
`total_calls`/`failed_calls`/`success_rate`, `per_tool_errors`, `recovery`, `redundant_calls`,
`runtime_ms`, `token_usage`. If no runs are returned, there is nothing un-reviewed — say so and stop.
If a run has no trace / no tool calls, say you cannot audit it (confidence 0) — do not invent.

## Step 3 — interpret each run (two tiers)
**Tier A — correctness (drives severity):**
1. **Invariants** — any `invariant_violations`? A `missing_required` or `forbidden_present` is
   serious; weigh `order_violation`/`missing_terminal` in context.
2. **Success rate** — interpret `per_tool_errors`: is a failure transient (a quote timeout) or a
   real process break (a persistent tool exception)?
3. **Recovery** — in `recovery`, a `swallowed` error on a consequential tool (e.g. `place_order`)
   is a key finding; `retried_ok` is healthy.
4. **Run completion** — `run_completed == false` (the loop crashed) is a major failure.

**Tier B — observability (NEVER a standalone fail; `info`/`warn` at most):**
5. **Runtime / tokens** — only flag an *egregious* anomaly relative to recent norms; absolute
   numbers alone are not a finding.
6. **Redundant calls** — a soft note, not a severity driver.

## Step 4 — verdict (per run)
`write_review(review_type="tool_fidelity", subject="<run_id> (<phase>)", verdict="<prose citing the
facts>", severity="<pass|info|warn|fail>", confidence=<0-1>, evidence_refs={...the facts you relied
on: run_id, success_rate, invariant_violations, ...})`. Lower confidence if `phase=="unknown"` or
the trace was partial. Tier B alone never yields `fail`.

Then call `mark_run_reviewed(run_id, start_time)` — ONLY after the verdict is written, so a failed
review re-audits the run next time.

## Step 5 — consolidate (selective)
- For a RECURRING or MATERIALLY SIGNIFICANT pattern (e.g. `record_daily_snapshot` missing across
  afternoon runs; a tool erroring every run), call `record_insight(text="<standing observation>",
  source_review_ids=[<this + related ids>])`. Discard one-off noise.
- Update the headline: `write_reviewer_memory(scope="index", value={...})` — one-line summary +
  count + last-seen for "tool_fidelity".
- If a skip also shows up as a failed operation in `review-operation-success`, call
  `promote_to_global(text, justification, corroborating_review_ids)` (>= 2 reviews).
- Write only via the bound scopes — never a raw namespace, never another task's detail. The
  watermark advances via `mark_run_reviewed`, not by you writing memory.
```

- [ ] **Step 3: Run well-formedness + import checks**

Run: `python -m pytest tests/test_phase2_skills_wellformed.py tests/test_skill_wellformed.py -v`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add agent/src/review_agent/skills/review-tool-fidelity/SKILL.md
git commit -m "feat(reviewer): rewrite review-tool-fidelity skill (deterministic facts + LLM judgment)"
```

---

### Task 7: End-to-end validation against a real trace

**Files:** none (manual validation + notes).

- [ ] **Step 1: Fire one real trader run so a trace exists**

Run (separate shell, server already on :2024): `python scripts/run_factor_loop_local.py`
Expected: a new `autonomous_loop` root run appears in the LangSmith `monet_agent` project with
real `run_type=="tool"` children (score_universe, generate_factor_rankings, …).

- [ ] **Step 2: Confirm the trace is fetchable + filtered**

Run:
```bash
python - <<'PY'
from dotenv import dotenv_values; import os
env = dotenv_values("agent/.env")
for k in ("LANGSMITH_API_KEY","LANGSMITH_PROJECT","LANGSMITH_ENDPOINT"):
    if env.get(k): os.environ[k] = env[k].strip('"')
os.environ.setdefault("LANGSMITH_PROJECT","monet_agent")
import sys; sys.path.insert(0, "agent/src")
from review_agent.trace import read_run_trace
t = read_run_trace(limit=3)
for r in t["runs"]:
    print(r["name"], r["start_time"], "tool_calls=", len(r["tool_calls"]))
PY
```
Expected: only `autonomous_loop` runs (no `review_agent`), with non-empty `tool_calls`.

- [ ] **Step 3: Run the skill end-to-end (async, via the local server)**

Run: `python scripts/run_reviewer_local.py "Run a tool-fidelity review of the most recent autonomous_loop run."`
Expected: the reviewer calls `begin_review("tool_fidelity")` → `get_tool_fidelity_runs` →
`write_review` (severity reflecting the real run) → `mark_run_reviewed`. Verify a row in
`agent_reviews` (`review_type='tool_fidelity'`, fact-laden `evidence_refs`) and a
`tool_fidelity:watermark` row in `reviewer_memory`.

- [ ] **Step 4: Record honest validation limits + run the full suite**

Run: `python -m pytest tests/ -v`
Expected: all green (unit) + integration skipped unless `RUN_DB_INTEGRATION=1`.
Note in the spec/PR: the local run validates the **happy path** only; "missing required" / "errored
tool" branches are covered by the unit fixtures (Task 2), not the live run.

- [ ] **Step 5: Commit (docs/log only)**

```bash
# update POSTDEPLOY_CHECK.md (new skill, trigger: first tool-fidelity review) + release-log.tsx
git add POSTDEPLOY_CHECK.md web/components/trading/release-log.tsx
git commit -m "docs(reviewer): tool-fidelity postdeploy checklist + release log"
```

---

## Self-Review

**Spec coverage:**
- §1 purpose/boundaries → SKILL.md description + routing (Task 6).
- §2 trace-only + honest-inert → `read_run_trace` is the sole evidence (Task 4); skill says "no trace → cannot audit" (Task 6 Step 2).
- §3a deterministic detection / LLM judgment → analysis in `tool_fidelity.py` (Task 2); skill interprets (Task 6).
- §3b invariants not golden sequence → `PHASE_INVARIANTS` required/forbidden/order/terminal + benign-reorder test (Tasks 1–2).
- §3c tiers → Tier-A drives severity (Task 2 facts + Task 6 Step 3/4); Tier-B never fails (Task 6 explicit).
- §3d failure definition → `error` field only; `test_success_rate_and_per_tool_errors` (Task 2).
- §4 which run / which group → `select_roots_by_name` filter + `get_tool_fidelity_runs` targeting (Tasks 4–5).
- §5 atomic unit + watermark + memory shape → cursor (Task 3), DB helpers (Task 5), skill consolidation (Task 6); watermark code-managed.
- §6 single skill + seam → one SKILL.md with phase invariants table as the seam (Tasks 1, 6).
- §9 validation → Task 7 (+ honest happy-path-only note).
- §10 open: trigger/cadence not implemented (correct — deferred); severity thresholds = sensible defaults in the skill prose (Task 6).

**Placeholder scan:** none. The one implementation note (Task 4, `total_tokens` attribute) is a "confirm this field name against the installed SDK" check on a best-effort Tier-B value, not missing logic.

**Type consistency:** `analyze_tool_fidelity(run, phase)` signature consistent Task 2 ↔ Task 5. `select_unreviewed(roots, cursor, *, cold_start_n)` / `advance_cursor(cursor, run_id, start_time, *, baseline, cap)` consistent Task 3 ↔ Task 5. `read_run_trace(run_id, graph_name, limit, config)` consistent Task 4 ↔ Task 5. Tool names `get_tool_fidelity_runs` / `mark_run_reviewed` consistent Tasks 5–6. Watermark namespace `{review_type}:watermark` consistent (db.py Task 5, spec §5).
