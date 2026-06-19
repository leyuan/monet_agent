# review-operation-success Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the reviewer's `review-operation-success` skill to the trace-native, deterministic-facts-plus-LLM-judgment template — auditing whether each operation an `autonomous_loop` run *attempted* actually *landed* via a trace × Supabase join.

**Architecture:** A pure module (`operation_success.py`) holds a declarative `OPERATION_SPECS` registry, a `READ_ONLY_TOOLS` allowlist, and three pure functions (`extract_operations`, `build_probe_sql`, `classify_operation`). An I/O tool (`get_operation_success_runs`) reads the trace, runs one read-only SQL probe per operation via `query_database`, and calls the pure classifier. The generic run-selection/watermark trio is extracted from `tool_fidelity.py` into a shared `run_cursor.py`. The `SKILL.md` orchestrates: interpret the facts, judge severity, write the verdict, consolidate, advance the watermark.

**Tech Stack:** Python 3.11+, pytest (`pythonpath=["src"]`, `asyncio_mode=auto`), deepagents, LangSmith (`read_run_trace`), Supabase (`query_database` → `exec_readonly_sql`).

## Global Constraints

- **Reviewer is read-only on the trader.** No trading tools; writes only to `agent_reviews` + `reviewer_memory`. The boundary test `tests/test_review_tools_boundary.py` must stay green (`place_order` etc. never appear in `REVIEW_TOOLS`).
- **Deterministic facts, LLM judgment.** The pure functions compute status; the LLM never re-derives a status or hand-writes SQL. No model in the pure layer.
- **Pure functions take/return plain dicts** (no LangSmith/Supabase imports) so they unit-test without I/O — same convention as `tool_fidelity.py`.
- **Trace is graph-filtered to `autonomous_loop`** (already done in `read_run_trace`); skip in-progress runs (`is_finished`).
- **Memory binding is by `begin_review("operation_success")`** — the watermark + detail namespaces are bound from the active review type; the LLM chooses only `scope=`, never a raw namespace.
- **Run tests from `agent/`**: `cd agent && python -m pytest <path> -v`.
- **v1 scoping (explicit deviations from spec, conservative):** match keys are **Tier-1 only** (exact key from the tool's output/input); when the key is absent the operation is `unverifiable`, never matched by a fuzzy timestamp window (spec §3c Tier-2 → roadmap). Memory-write freshness uses **`updated_at >= run_start`** (robust to same-run overwrites) rather than exact-timestamp equality.

---

## File Structure

- `src/review_agent/run_cursor.py` — **new.** Generic, graph-agnostic `is_finished`, `select_unreviewed`, `advance_cursor` (+ `_GRAPH`), extracted from `tool_fidelity.py`. Shared by both trace-native skills.
- `src/review_agent/tool_fidelity.py` — **modify.** Remove the three functions; re-export them from `run_cursor` so existing imports keep working unchanged.
- `src/review_agent/operation_success.py` — **new.** `OPERATION_SPECS`, `READ_ONLY_TOOLS`, `CRITICAL_OPS`, `extract_operations`, `build_probe_sql`, `classify_operation`, `run_severity`. Pure.
- `src/review_agent/tools.py` — **modify.** Add `get_operation_success_runs` tool; register it in `REVIEW_TOOLS`.
- `src/review_agent/skills/review-operation-success/SKILL.md` — **rewrite.**
- `tests/test_run_cursor.py` — **new.**
- `tests/test_operation_success_registry.py` — **new** (the coverage/partition guarantee).
- `tests/test_operation_success_extract.py` — **new.**
- `tests/test_operation_success_probe.py` — **new.**
- `tests/test_operation_success_classify.py` — **new.**
- `tests/test_operation_success_tools.py` — **new.**
- `POSTDEPLOY_CHECK.md` — **modify** (add a verification block).

---

## Task 1: Extract the run-cursor trio into a shared module

**Files:**
- Create: `src/review_agent/run_cursor.py`
- Modify: `src/review_agent/tool_fidelity.py:56-166` (remove `is_finished`/`select_unreviewed`/`advance_cursor`/`_GRAPH`, add re-export)
- Test: `tests/test_run_cursor.py`

**Interfaces:**
- Produces: `is_finished(run: dict) -> bool`; `select_unreviewed(roots: list[dict], cursor: dict | None, *, cold_start_n: int) -> list[dict]`; `advance_cursor(cursor: dict | None, run_id: str, start_time: str, *, baseline: dict | None = None, cap: int = 50) -> dict`.
- Consumes: nothing. Behavior identical to the current `tool_fidelity.py` definitions.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_run_cursor.py
from review_agent.run_cursor import is_finished, select_unreviewed, advance_cursor


def test_is_finished_requires_end_time():
    assert is_finished({"end_time": "2026-06-19T14:05:00"}) is True
    assert is_finished({"end_time": None}) is False
    assert is_finished({}) is False


def test_select_unreviewed_cold_start_takes_most_recent_n():
    roots = [{"run_id": "r3"}, {"run_id": "r2"}, {"run_id": "r1"}]  # newest-first
    out = select_unreviewed(roots, None, cold_start_n=2)
    assert [r["run_id"] for r in out] == ["r2", "r3"]  # returned oldest-first


def test_select_unreviewed_skips_seen():
    roots = [{"run_id": "r3"}, {"run_id": "r2"}, {"run_id": "r1"}]
    cursor = {"reviewed_run_ids": ["r1", "r2"]}
    out = select_unreviewed(roots, cursor, cold_start_n=5)
    assert [r["run_id"] for r in out] == ["r3"]


def test_advance_cursor_prepends_and_caps():
    cur = advance_cursor(None, "r1", "2026-06-19T10:00:00")
    cur = advance_cursor(cur, "r2", "2026-06-19T11:00:00", baseline={"x": 1})
    assert cur["reviewed_run_ids"][0] == "r2"
    assert cur["graph"] == "autonomous_loop"
    assert cur["baseline"]["x"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd agent && python -m pytest tests/test_run_cursor.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'review_agent.run_cursor'`.

- [ ] **Step 3: Create `run_cursor.py` (move the three functions verbatim)**

```python
# src/review_agent/run_cursor.py
"""Generic, graph-agnostic run-selection + watermark cursor for trace-native reviews.

Pure — no I/O. Shared by review-tool-fidelity and review-operation-success so neither
skill depends on the other. Moved here verbatim from tool_fidelity.py.
"""

_GRAPH = "autonomous_loop"


def is_finished(run: dict) -> bool:
    """A LangSmith run has terminated iff it has an `end_time` (whether it succeeded or
    errored). A still-running run has end_time=None — auditing it yields a partial,
    misleading trace, so callers must skip it."""
    return run.get("end_time") is not None


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
    return {
        "graph": _GRAPH,
        "last_reviewed_start_time": start_time,
        "reviewed_run_ids": ids,
        "baseline": {**cursor.get("baseline", {}), **(baseline or {})},
    }
```

- [ ] **Step 4: Replace the moved definitions in `tool_fidelity.py` with a re-export**

In `src/review_agent/tool_fidelity.py`, delete the `is_finished` function (currently lines ~73-77), the `select_unreviewed` function (~144-152), the `advance_cursor` function (~155-166), and the `_GRAPH = "autonomous_loop"` line (~141). Then add this import near the top (just below the module docstring):

```python
# Generic run-selection + watermark helpers now live in run_cursor.py; re-exported here so
# existing `from review_agent.tool_fidelity import is_finished, select_unreviewed, advance_cursor`
# imports (tools.py + tool-fidelity tests) keep working unchanged.
from review_agent.run_cursor import is_finished, select_unreviewed, advance_cursor  # noqa: F401
```

- [ ] **Step 5: Run the new + existing tests to verify all pass**

Run: `cd agent && python -m pytest tests/test_run_cursor.py tests/test_tool_fidelity_watermark.py tests/test_tool_fidelity_completion.py tests/test_tool_fidelity_tools.py -v`
Expected: PASS (the re-export keeps the old import paths working; behavior unchanged).

- [ ] **Step 6: Commit**

```bash
git add src/review_agent/run_cursor.py src/review_agent/tool_fidelity.py tests/test_run_cursor.py
git commit -m "refactor(reviewer): extract run-cursor trio into shared run_cursor.py"
```

---

## Task 2: Operation registry, read-only allowlist, and the coverage guarantee

**Files:**
- Create: `src/review_agent/operation_success.py`
- Test: `tests/test_operation_success_registry.py`

**Interfaces:**
- Produces: `OPERATION_SPECS: dict[str, dict]` (keyed by tool name; each value has `kind` ∈ {`"db"`, `"trace_only"`} and, for `db`, `verify`/`table`/`match`/optional `critical`); `READ_ONLY_TOOLS: set[str]`; `CRITICAL_OPS: set[str]`.
- Consumes: `stock_agent.tools.AUTONOMOUS_TOOLS` (in the test only).

- [ ] **Step 1: Write the failing coverage test**

```python
# tests/test_operation_success_registry.py
from review_agent.operation_success import OPERATION_SPECS, READ_ONLY_TOOLS
from stock_agent.tools import AUTONOMOUS_TOOLS


def _tool_name(t):
    return getattr(t, "name", getattr(t, "__name__", ""))


def test_every_trader_tool_is_classified():
    """Coverage guarantee: each autonomous tool is either a known operation or a known
    read. Adding a new trader tool breaks this until someone classifies it."""
    names = {_tool_name(t) for t in AUTONOMOUS_TOOLS}
    classified = set(OPERATION_SPECS) | READ_ONLY_TOOLS
    assert names == classified, (
        f"unclassified trader tools: {names - classified}; "
        f"stale registry entries: {classified - names}"
    )


def test_db_specs_have_required_shape():
    for tool, spec in OPERATION_SPECS.items():
        assert spec["kind"] in ("db", "trace_only"), tool
        if spec["kind"] == "db":
            assert "verify" in spec and "table" in spec and "match" in spec, tool
            m = spec["match"]
            assert m["src"] in ("output", "input") and m["col"] and m["field"], tool
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd agent && python -m pytest tests/test_operation_success_registry.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'review_agent.operation_success'`.

- [ ] **Step 3: Create `operation_success.py` with the registry + allowlist**

```python
# src/review_agent/operation_success.py
"""Pure operation-success logic: the operation registry, the read-only allowlist, and the
trace × DB classification. No I/O — every function takes plain dicts (the trace tool call +
the DB rows the I/O layer fetched) so it unit-tests without LangSmith or Supabase.
"""

# Operations the trader can perform, and how to verify each one's durable effect landed.
#   kind="db"        : a row should appear/change in `table`; matched by `match`.
#       match.src    : "output" (the tool's return payload) or "input" (its call args)
#       match.field  : key in that payload holding the identifier
#       match.col    : the DB column to match it against
#       verify       : which landing rule classify_operation applies (see VERIFY_RULES)
#       critical     : a silent failure here is a `fail` (else `warn`)
#   kind="trace_only": no clean DB row (external / conditional multi-write) — judged from
#                      the tool's own output (error flag / reported failure).
OPERATION_SPECS: dict[str, dict] = {
    # --- db-backed -----------------------------------------------------------
    "place_order": {"kind": "db", "verify": "order_status", "table": "trades",
                    "match": {"src": "output", "field": "trade_id", "col": "id"},
                    "critical": True, "expected_fail_prefix": "Risk check failed"},
    "cancel_order": {"kind": "db", "verify": "order_cancelled", "table": "trades",
                     "match": {"src": "output", "field": "trade_id", "col": "id"}},
    "write_journal_entry": {"kind": "db", "verify": "row_exists", "table": "agent_journal",
                            "match": {"src": "output", "field": "journal_id", "col": "id"}},
    "write_agent_memory": {"kind": "db", "verify": "fresh_memory", "table": "agent_memory",
                           "match": {"src": "output", "field": "key", "col": "key"}},
    "update_market_regime": {"kind": "db", "verify": "fresh_memory", "table": "agent_memory",
                             "match": {"src": "output", "field": "key", "col": "key"}},
    "record_decision": {"kind": "db", "verify": "fresh_memory", "table": "agent_memory",
                        "match": {"src": "output", "field": "key", "col": "key"}},
    "update_stock_analysis": {"kind": "db", "verify": "fresh_memory", "table": "agent_memory",
                              "match": {"src": "output", "field": "key", "col": "key"}},
    "manage_watchlist": {"kind": "db", "verify": "row_exists", "table": "watchlist",
                         "match": {"src": "input", "field": "symbol", "col": "symbol"}},
    "record_daily_snapshot": {"kind": "db", "verify": "snapshot", "table": "equity_snapshots",
                              "match": {"src": "output", "field": "date", "col": "snapshot_date"},
                              "critical": True},
    "audit_factor_ic": {"kind": "db", "verify": "fresh_memory", "table": "agent_memory",
                        "match": {"src": "const", "field": "strategy_health", "col": "key"}},
    "check_live_vs_backtest_divergence": {"kind": "db", "verify": "fresh_memory", "table": "agent_memory",
                                          "match": {"src": "const", "field": "strategy_divergence", "col": "key"}},
    # --- trace-only (external / conditional multi-write) ----------------------
    "attach_bracket_to_position": {"kind": "trace_only"},
    "reconcile_positions": {"kind": "trace_only"},
    "send_daily_recap": {"kind": "trace_only"},
    "send_daily_subscription_emails": {"kind": "trace_only"},
    "send_weekly_cycle_report": {"kind": "trace_only"},
}

CRITICAL_OPS = {t for t, s in OPERATION_SPECS.items() if s.get("critical")}

# Tools with no durable operation to verify here: pure reads, plus tools whose only write
# is an incidental cache/perf detail (score_universe → agent_memory.factor_cache) that is
# not a meaningful "did the operation land" signal. The complement of OPERATION_SPECS.
READ_ONLY_TOOLS: set[str] = {
    "internet_search", "get_stock_quote", "get_historical_data", "technical_analysis",
    "fundamental_analysis", "screen_stocks", "company_profile", "sector_analysis",
    "peer_comparison", "earnings_calendar", "eps_estimates", "market_breadth",
    "get_open_orders", "get_portfolio_state", "check_trade_risk", "read_agent_memory",
    "read_all_agent_memory", "query_database", "get_performance_comparison",
    "position_health_check", "check_watchlist_alerts", "score_universe",
    "enrich_eps_revisions", "generate_factor_rankings", "discover_catalysts",
    "get_earnings_results", "assess_ai_bubble_risk", "assess_ai_cycle_durability",
    "suggest_factor_weight_adjustment",
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd agent && python -m pytest tests/test_operation_success_registry.py -v`
Expected: PASS. If `test_every_trader_tool_is_classified` fails listing unclassified tools, read each named tool's implementation and add it to `OPERATION_SPECS` (db if it writes a verifiable row, trace_only if external/conditional) or `READ_ONLY_TOOLS` (no meaningful operation), then re-run.

- [ ] **Step 5: Commit**

```bash
git add src/review_agent/operation_success.py tests/test_operation_success_registry.py
git commit -m "feat(reviewer): operation-success registry + coverage guarantee"
```

---

## Task 3: `extract_operations` — enumerate + bucket trace tool calls

**Files:**
- Modify: `src/review_agent/operation_success.py`
- Test: `tests/test_operation_success_extract.py`

**Interfaces:**
- Consumes: a run dict shaped like `read_run_trace` output — `{"tool_calls": [{"name", "inputs", "outputs", "error", ...}]}`.
- Produces: `extract_operations(run: dict) -> list[dict]` returning one entry per *operation or unknown* call (reads dropped): `{"tool": str, "bucket": "db"|"trace_only"|"unclassified", "inputs": dict, "output": dict, "error": str | None}`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_operation_success_extract.py
from review_agent.operation_success import extract_operations


def _call(name, outputs=None, inputs=None, error=None):
    return {"name": name, "inputs": inputs or {}, "outputs": outputs or {}, "error": error}


def test_reads_are_dropped_operations_kept():
    run = {"tool_calls": [
        _call("score_universe"),                                  # read → dropped
        _call("get_quote"),                                       # unknown read-ish? not in any set → unclassified
        _call("write_journal_entry", outputs={"journal_id": "j1"}),
        _call("send_daily_recap", outputs={"status": "queued"}),
    ]}
    ops = extract_operations(run)
    by_tool = {o["tool"]: o for o in ops}
    assert "score_universe" not in by_tool                        # known read dropped
    assert by_tool["write_journal_entry"]["bucket"] == "db"
    assert by_tool["send_daily_recap"]["bucket"] == "trace_only"
    assert by_tool["get_quote"]["bucket"] == "unclassified"       # unknown surfaced


def test_output_is_unwrapped_from_langsmith_wrapper():
    run = {"tool_calls": [_call("write_agent_memory",
                                outputs={"output": {"key": "k1", "updated_at": "t"}})]}
    op = extract_operations(run)[0]
    assert op["output"] == {"key": "k1", "updated_at": "t"}       # {"output": ...} unwrapped
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd agent && python -m pytest tests/test_operation_success_extract.py -v`
Expected: FAIL with `ImportError: cannot import name 'extract_operations'`.

- [ ] **Step 3: Implement `extract_operations` (append to `operation_success.py`)**

```python
def _unwrap_output(outputs) -> dict:
    """LangSmith stores a tool's return under varying shapes. Normalize to the return dict:
    a bare {"output": <dict>} wrapper is unwrapped; anything non-dict becomes {}."""
    if isinstance(outputs, dict):
        if set(outputs.keys()) == {"output"} and isinstance(outputs["output"], dict):
            return outputs["output"]
        return outputs
    return {}


def extract_operations(run: dict) -> list[dict]:
    """Enumerate the run's operations from its trace. Reads are dropped; operations and
    unknown (unclassified) tools are returned for verification/surfacing."""
    ops = []
    for c in run.get("tool_calls", []):
        name = c.get("name")
        if name in READ_ONLY_TOOLS:
            continue
        spec = OPERATION_SPECS.get(name)
        bucket = spec["kind"] if spec else "unclassified"
        ops.append({
            "tool": name,
            "bucket": bucket,
            "inputs": c.get("inputs") or {},
            "output": _unwrap_output(c.get("outputs")),
            "error": c.get("error"),
        })
    return ops
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd agent && python -m pytest tests/test_operation_success_extract.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/review_agent/operation_success.py tests/test_operation_success_extract.py
git commit -m "feat(reviewer): extract_operations enumerates + buckets trace calls"
```

---

## Task 4: `build_probe_sql` — the read-only DB probe per operation

**Files:**
- Modify: `src/review_agent/operation_success.py`
- Test: `tests/test_operation_success_probe.py`

**Interfaces:**
- Consumes: an operation dict from `extract_operations`.
- Produces: `build_probe_sql(op: dict) -> str | None` — a `SELECT * ... WHERE <col> = '<value>'` for `db` ops whose identifier is present; `None` for `trace_only`/`unclassified` ops, or when the identifier is missing/unsafe (→ classifier treats as `unverifiable`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_operation_success_probe.py
from review_agent.operation_success import build_probe_sql


def _op(tool, bucket="db", output=None, inputs=None):
    return {"tool": tool, "bucket": bucket, "output": output or {}, "inputs": inputs or {}, "error": None}


def test_probe_by_output_id():
    sql = build_probe_sql(_op("place_order", output={"trade_id": "abc-123"}))
    assert sql == "SELECT * FROM trades WHERE id = 'abc-123' LIMIT 5"


def test_probe_by_input_symbol():
    sql = build_probe_sql(_op("manage_watchlist", inputs={"symbol": "AAPL"}))
    assert sql == "SELECT * FROM watchlist WHERE symbol = 'AAPL' LIMIT 5"


def test_probe_by_const_key():
    sql = build_probe_sql(_op("audit_factor_ic"))
    assert sql == "SELECT * FROM agent_memory WHERE key = 'strategy_health' LIMIT 5"


def test_probe_none_for_trace_only_and_missing_and_unsafe():
    assert build_probe_sql(_op("send_daily_recap", bucket="trace_only")) is None
    assert build_probe_sql(_op("place_order", output={})) is None            # no trade_id
    assert build_probe_sql(_op("write_agent_memory", output={"key": "a'b"})) is None  # unsafe
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd agent && python -m pytest tests/test_operation_success_probe.py -v`
Expected: FAIL with `ImportError: cannot import name 'build_probe_sql'`.

- [ ] **Step 3: Implement `build_probe_sql` (append to `operation_success.py`)**

```python
import re

_SAFE_VALUE = re.compile(r"^[A-Za-z0-9 :._\-]+$")  # ids, keys, symbols, dates — no quotes


def _match_value(op: dict, match: dict) -> str | None:
    """Resolve the identifier for the probe from the op's output / input / a constant."""
    if match["src"] == "const":
        return match["field"]
    payload = op.get(match["src"]) or {}            # "output" or "input"
    return payload.get(match["field"])


def build_probe_sql(op: dict) -> str | None:
    """A single read-only SELECT to confirm the operation's row landed, or None when there
    is nothing safe to probe (trace-only/unclassified, missing identifier, unsafe value)."""
    spec = OPERATION_SPECS.get(op["tool"])
    if not spec or spec["kind"] != "db":
        return None
    match = spec["match"]
    value = _match_value(op, match)
    if not value or not _SAFE_VALUE.match(str(value)):
        return None
    return f"SELECT * FROM {spec['table']} WHERE {match['col']} = '{value}' LIMIT 5"
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd agent && python -m pytest tests/test_operation_success_probe.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/review_agent/operation_success.py tests/test_operation_success_probe.py
git commit -m "feat(reviewer): build_probe_sql read-only landing probe"
```

---

## Task 5: `classify_operation` + `run_severity` — the status logic

**Files:**
- Modify: `src/review_agent/operation_success.py`
- Test: `tests/test_operation_success_classify.py`

**Interfaces:**
- Consumes: an op dict; `rows: list[dict]` (the probe result, `[]` if none/none-found); `run_start: str` (the run's `start_time`).
- Produces: `classify_operation(op: dict, rows: list[dict], run_start: str) -> dict` → `{"tool", "status", "severity", "detail", "evidence"}`; `run_severity(classified: list[dict]) -> str`.
- Status vocabulary: `landed`, `rejected_expected`, `partial`, `degraded`, `silent_failure`, `rejected_unexpected`, `errored_unrecovered`, `unverifiable`. Severity: `pass`/`info`/`warn`/`fail`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_operation_success_classify.py
from review_agent.operation_success import classify_operation, run_severity

RUN_START = "2026-06-19T14:00:00+00:00"


def _op(tool, output=None, inputs=None, error=None):
    bucket = "trace_only" if tool.startswith("send_") or tool in (
        "attach_bracket_to_position", "reconcile_positions") else "db"
    return {"tool": tool, "bucket": bucket, "output": output or {}, "inputs": inputs or {}, "error": error}


def test_order_filled_lands():
    op = _op("place_order", output={"trade_id": "t1", "status": "filled"})
    r = classify_operation(op, [{"id": "t1", "status": "filled", "filled_avg_price": 10.0}], RUN_START)
    assert r["status"] == "landed" and r["severity"] == "pass"


def test_order_risk_rejected_is_expected_success():
    op = _op("place_order", output={"error": "Risk check failed: exposure"})
    r = classify_operation(op, [], RUN_START)
    assert r["status"] == "rejected_expected" and r["severity"] == "pass"


def test_order_silent_failure_is_critical_fail():
    op = _op("place_order", output={"trade_id": "t1", "status": "filled"})
    r = classify_operation(op, [], RUN_START)            # output claims a trade, but no row
    assert r["status"] == "silent_failure" and r["severity"] == "fail"


def test_memory_fresh_lands_stale_is_silent_failure():
    op = _op("write_agent_memory", output={"key": "k1", "updated_at": "2026-06-19T14:01:00+00:00"})
    fresh = classify_operation(op, [{"key": "k1", "updated_at": "2026-06-19T14:01:00+00:00"}], RUN_START)
    assert fresh["status"] == "landed"
    stale = classify_operation(op, [{"key": "k1", "updated_at": "2026-06-18T09:00:00+00:00"}], RUN_START)
    assert stale["status"] == "silent_failure" and stale["severity"] == "warn"


def test_snapshot_degraded_on_bad_content():
    op = _op("record_daily_snapshot", output={"date": "2026-06-19"})
    r = classify_operation(op, [{"snapshot_date": "2026-06-19", "spy_close": 0, "portfolio_equity": 100}], RUN_START)
    assert r["status"] == "degraded" and r["severity"] == "warn"


def test_trace_only_clean_lands_errored_warns():
    clean = classify_operation(_op("send_daily_recap", output={"status": "queued"}), [], RUN_START)
    assert clean["status"] == "landed" and clean["severity"] in ("pass", "info")
    errored = classify_operation(_op("send_daily_recap", output={}, error="SMTP 500"), [], RUN_START)
    assert errored["status"] == "errored_unrecovered" and errored["severity"] == "warn"


def test_unverifiable_when_no_probe_key():
    op = _op("write_agent_memory", output={})            # no key → can't probe
    r = classify_operation(op, [], RUN_START)
    assert r["status"] == "unverifiable" and r["severity"] == "info"


def test_run_severity_is_worst():
    assert run_severity([{"severity": "pass"}, {"severity": "warn"}, {"severity": "fail"}]) == "fail"
    assert run_severity([{"severity": "pass"}, {"severity": "info"}]) == "info"
    assert run_severity([]) == "pass"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd agent && python -m pytest tests/test_operation_success_classify.py -v`
Expected: FAIL with `ImportError: cannot import name 'classify_operation'`.

- [ ] **Step 3: Implement `classify_operation` + `run_severity` (append to `operation_success.py`)**

```python
from datetime import datetime

_SEVERITY_ORDER = {"pass": 0, "info": 1, "warn": 2, "fail": 3}


def _result(op, status, severity, detail, evidence):
    return {"tool": op["tool"], "status": status, "severity": severity,
            "detail": detail, "evidence": evidence}


def _parse_dt(s):
    try:
        return datetime.fromisoformat(str(s))
    except (TypeError, ValueError):
        return None


def classify_operation(op: dict, rows: list[dict], run_start: str) -> dict:
    """Decide the operation's status + severity from its trace output and the probe rows.
    Pure: `rows` is whatever the DB probe returned ([] = none found / no probe)."""
    spec = OPERATION_SPECS.get(op["tool"], {"kind": "unclassified"})
    out = op.get("output") or {}

    # Unknown tool — surfaced, never silently dropped.
    if spec["kind"] == "unclassified":
        return _result(op, "unverifiable", "info",
                       f"{op['tool']} is not a known operation — registry may need updating.",
                       {"bucket": "unclassified"})

    # Trace-only: judged from the tool's own report (no DB row exists to check).
    if spec["kind"] == "trace_only":
        errs = out.get("errors")
        if op.get("error") or out.get("error"):
            return _result(op, "errored_unrecovered", "warn",
                           f"{op['tool']} errored: {op.get('error') or out.get('error')}", {"output": out})
        if errs:
            return _result(op, "partial", "warn", f"{op['tool']} reported errors: {errs}", {"output": out})
        return _result(op, "landed", "pass", f"{op['tool']} reported success.", {"output": out})

    # db-backed.
    critical = op["tool"] in CRITICAL_OPS
    verify = spec["verify"]

    # Guardrail rejection (place_order returns early before any DB write) = success.
    prefix = spec.get("expected_fail_prefix")
    if prefix and str(out.get("error", "")).startswith(prefix):
        return _result(op, "rejected_expected", "pass", out["error"], {"output": out})

    # No identifier to probe → honest unverifiable (never guess).
    if build_probe_sql(op) is None:
        return _result(op, "unverifiable", "info",
                       f"{op['tool']}: no identifier in trace output to verify landing.", {"output": out})

    if verify == "order_status":
        if not rows:
            sev = "fail" if critical else "warn"
            return _result(op, "silent_failure", sev,
                           "place_order returned a trade but no trades row landed.", {"output": out})
        status = str(rows[0].get("status", "")).lower()
        if "filled" in status and "partially" not in status:
            return _result(op, "landed", "pass", f"order {status}", {"row": rows[0]})
        if "partially_filled" in status:
            return _result(op, "partial", "warn", f"order {status}", {"row": rows[0]})
        if "rejected" in status or "canceled" in status or "cancelled" in status:
            return _result(op, "rejected_unexpected", "fail", f"order {status}", {"row": rows[0]})
        return _result(op, "unverifiable", "info", f"order pending/{status}", {"row": rows[0]})

    if verify == "order_cancelled":
        if rows and "cancel" in str(rows[0].get("status", "")).lower():
            return _result(op, "landed", "pass", "order cancelled", {"row": rows[0]})
        return _result(op, "silent_failure", "warn", "cancel did not land", {"output": out})

    if verify == "row_exists":
        if rows:
            return _result(op, "landed", "pass", f"{spec['table']} row present", {"row": rows[0]})
        return _result(op, "silent_failure", "warn",
                       f"{op['tool']} returned OK but no {spec['table']} row landed.", {"output": out})

    if verify == "fresh_memory":
        if not rows:
            return _result(op, "silent_failure", "warn",
                           f"{op['tool']}: no agent_memory row for the key.", {"output": out})
        row_dt, start_dt = _parse_dt(rows[0].get("updated_at")), _parse_dt(run_start)
        if row_dt and start_dt and row_dt < start_dt:
            return _result(op, "silent_failure", "warn",
                           "memory key exists but was not updated this run (stale).", {"row": rows[0]})
        return _result(op, "landed", "pass", "memory write landed", {"row": rows[0]})

    if verify == "snapshot":
        if not rows:
            sev = "fail" if critical else "warn"
            return _result(op, "silent_failure", sev, "no equity_snapshots row for the date.", {"output": out})
        row = rows[0]
        if not row.get("spy_close") or float(row.get("portfolio_equity") or 0) <= 0:
            return _result(op, "degraded", "warn",
                           "snapshot landed but content looks degraded (spy_close=0 or equity<=0).", {"row": row})
        return _result(op, "landed", "pass", "snapshot landed", {"row": row})

    return _result(op, "unverifiable", "info", f"no rule for verify={verify}", {"output": out})


def run_severity(classified: list[dict]) -> str:
    """The run verdict severity = the worst operation severity."""
    worst = "pass"
    for r in classified:
        if _SEVERITY_ORDER[r["severity"]] > _SEVERITY_ORDER[worst]:
            worst = r["severity"]
    return worst
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd agent && python -m pytest tests/test_operation_success_classify.py -v`
Expected: PASS (8 tests).

- [ ] **Step 5: Commit**

```bash
git add src/review_agent/operation_success.py tests/test_operation_success_classify.py
git commit -m "feat(reviewer): classify_operation status logic + run_severity"
```

---

## Task 6: `get_operation_success_runs` tool + registration

**Files:**
- Modify: `src/review_agent/tools.py` (add the tool near `get_tool_fidelity_runs` ~line 184-222; add to `REVIEW_TOOLS` ~line 225-242; extend the `operation_success`/`run_cursor` imports ~line 30-36)
- Test: `tests/test_operation_success_tools.py`

**Interfaces:**
- Consumes: `extract_operations`, `build_probe_sql`, `classify_operation`, `run_severity` (Tasks 3-5); `is_finished`, `select_unreviewed` (run_cursor); `read_run_trace`, `query_database`, `_read_watermark`, `_get_active`, `_thread_id` (existing in `tools.py`).
- Produces: `get_operation_success_runs(subject: str | None = None, config=None) -> {"runs": [{"run_id", "start_time", "run_severity", "operations": [...]}], "skipped_in_progress": [...]}`.
- Reuses the existing `mark_run_reviewed` tool (namespace-bound) to advance the `operation_success` watermark — no new mark tool.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_operation_success_tools.py
import review_agent.tools as T

FAKE_CONFIG = {"configurable": {"thread_id": "t1"}}

_TRACE = {"runs": [
    {"run_id": "r1", "name": "autonomous_loop", "start_time": "2026-06-19T14:00:00+00:00",
     "end_time": "2026-06-19T14:05:00+00:00", "error": None, "total_tokens": 100,
     "tool_calls": [
         {"name": "score_universe", "inputs": {}, "outputs": {}, "error": None},
         {"name": "write_journal_entry", "inputs": {}, "outputs": {"journal_id": "j1"}, "error": None},
         {"name": "record_daily_snapshot", "inputs": {}, "outputs": {"date": "2026-06-19"}, "error": None},
     ]},
]}


def _setup(monkeypatch, rows_by_table):
    monkeypatch.setattr(T, "_get_active", lambda tid: "operation_success")
    monkeypatch.setattr(T, "read_run_trace", lambda **k: _TRACE)
    monkeypatch.setattr(T, "_read_watermark", lambda rt: None)  # cold start

    def fake_query(sql):
        if "agent_journal" in sql:
            return {"rows": [{"id": "j1"}]}
        if "equity_snapshots" in sql:
            return {"rows": []}                                  # snapshot silently missing
        return {"rows": []}
    monkeypatch.setattr(T, "query_database", fake_query)


def test_get_runs_joins_trace_and_db(monkeypatch):
    _setup(monkeypatch, {})
    out = T.get_operation_success_runs(config=FAKE_CONFIG)
    run = out["runs"][0]
    statuses = {o["tool"]: o["status"] for o in run["operations"]}
    assert statuses["write_journal_entry"] == "landed"
    assert statuses["record_daily_snapshot"] == "silent_failure"   # critical → fail
    assert "score_universe" not in statuses                          # read dropped
    assert run["run_severity"] == "fail"


def test_get_runs_skips_in_progress(monkeypatch):
    monkeypatch.setattr(T, "_get_active", lambda tid: "operation_success")
    monkeypatch.setattr(T, "read_run_trace", lambda **k: {"runs": [
        {"run_id": "rp", "name": "autonomous_loop", "start_time": "2026-06-19T14:00:00+00:00",
         "end_time": None, "error": None, "tool_calls": []}]})
    monkeypatch.setattr(T, "_read_watermark", lambda rt: None)
    out = T.get_operation_success_runs(config=FAKE_CONFIG)
    assert out["runs"] == [] and "rp" in out["skipped_in_progress"]


def test_requires_active_review(monkeypatch):
    monkeypatch.setattr(T, "_get_active", lambda tid: None)
    import pytest
    with pytest.raises(ValueError):
        T.get_operation_success_runs(config=FAKE_CONFIG)


def test_registered_and_boundary_intact():
    names = {getattr(t, "__name__", getattr(t, "name", "")) for t in T.REVIEW_TOOLS}
    assert "get_operation_success_runs" in names
    assert "place_order" not in names
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd agent && python -m pytest tests/test_operation_success_tools.py -v`
Expected: FAIL with `AttributeError: module 'review_agent.tools' has no attribute 'get_operation_success_runs'`.

- [ ] **Step 3: Extend imports in `tools.py`**

In `src/review_agent/tools.py`, just below the existing `from review_agent.tool_fidelity import (...)` block (~line 33-35), add:

```python
from review_agent.operation_success import (
    extract_operations, build_probe_sql, classify_operation, run_severity,
)
```

(`query_database` is already imported at the top from `stock_agent.tools.memory`; `is_finished`/`select_unreviewed` are already imported via the tool_fidelity re-export.)

- [ ] **Step 4: Add the tool (place it right after `mark_run_reviewed`, ~line 222)**

```python
def get_operation_success_runs(subject: str | None = None, config: RunnableConfig = None) -> dict:
    """Resolve the trader runs to audit and return their DETERMINISTIC operation-success facts.

    For each finished run: enumerate operations from the trace, probe the trader's Supabase
    tables read-only to confirm each durable effect landed, and classify the outcome. Sweep
    mode (subject None) = runs newer than the operation_success watermark; explicit mode
    (subject a run_id) = just that run. You INTERPRET the statuses, write a verdict per run
    with write_review, then call mark_run_reviewed(run_id, start_time).

    Returns: {"runs": [{"run_id","start_time","run_severity","operations":[...]}],
              "skipped_in_progress": [...]}.
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

    out, skipped = [], []
    for run in roots:
        if not is_finished(run):
            skipped.append(run["run_id"])
            continue
        classified = []
        for op in extract_operations(run):
            sql = build_probe_sql(op)
            rows = []
            if sql:
                res = query_database(sql)
                rows = res.get("rows") or []
            classified.append(classify_operation(op, rows, run["start_time"]))
        out.append({"run_id": run["run_id"], "start_time": run["start_time"],
                    "run_severity": run_severity(classified), "operations": classified})
    return {"runs": out, "skipped_in_progress": skipped}
```

- [ ] **Step 5: Register in `REVIEW_TOOLS`**

In the `REVIEW_TOOLS` list, just below `get_tool_fidelity_runs,` / `mark_run_reviewed,`, add:

```python
    # operation-success audit (reuses mark_run_reviewed for the watermark)
    get_operation_success_runs,
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd agent && python -m pytest tests/test_operation_success_tools.py tests/test_review_tools_boundary.py -v`
Expected: PASS (4 new tests + the boundary test stays green).

- [ ] **Step 7: Commit**

```bash
git add src/review_agent/tools.py tests/test_operation_success_tools.py
git commit -m "feat(reviewer): get_operation_success_runs tool (trace × DB join)"
```

---

## Task 7: Rewrite `review-operation-success/SKILL.md`

**Files:**
- Modify (rewrite): `src/review_agent/skills/review-operation-success/SKILL.md`
- Verify: read the file back; no test (skill prose).

**Interfaces:**
- Consumes: `begin_review`, `get_operation_success_runs`, `write_review`, `record_insight`, `write_reviewer_memory`, `promote_to_global`, `mark_run_reviewed`.

- [ ] **Step 1: Replace the file contents**

````markdown
---
name: review-operation-success
description: >
  Audit whether each OPERATION an autonomous_loop run attempted actually completed — orders
  filled, snapshots saved, memory/journal writes landed, emails sent — by joining the run's
  LangSmith trace to the trader's Supabase tables. Use when asked if a run's side-effects
  succeeded or whether something silently failed. Do NOT use for tool-call ordering or whether
  a call errored (use review-tool-fidelity), hard-rule compliance (use review-strategy-conformance),
  reasoning or bias (use review-decision-quality), or strategy efficacy (use review-strategy-efficacy).
memory_namespace: operation_success
memory_access: { read: own, write: own }
tags: [process, execution, trace]
---

# Review: Operation Success

Audit whether each operation a run ATTEMPTED actually LANDED. A tool can return OK while its
durable effect silently fails (order rejected at the broker, a write that never persisted). You
judge execution OUTCOMES — not tool ordering, not rule compliance, not reasoning.

**Detection is deterministic — `get_operation_success_runs` computes the facts** (trace × DB join).
Your job is to INTERPRET them (is this silent failure material or a one-off?), judge severity, and
consolidate. Do not hand-write SQL or re-derive a status the tool already computed.

## Step 0 — begin + fit-check
Call `begin_review("operation_success", subject="<run id / date / 'sweep'>", reason="<why operation-success>")`
FIRST — it binds your memory and returns prior context. State: "Running an OPERATION SUCCESS review
of {subject}." If the request is about WHICH tools were called or in what order, route to
`review-tool-fidelity`; for rule compliance or reasoning, route accordingly or use `review-general`.

## Step 1 — treat priors as priors
Prior context (standing operation-failure patterns + recent verdicts) is PRIORS only. The
freshly-computed facts are ground truth; if a prior conflicts with this run's facts, the facts win.
Treat "(unconfirmed)" insights cautiously.

## Step 2 — get the facts
Call `get_operation_success_runs()` (sweep — runs newer than your watermark) or
`get_operation_success_runs(subject="<run_id>")` for a specific run. Each run returns
`{run_id, start_time, run_severity, operations:[{tool, status, severity, detail, evidence}]}`.
If no runs are returned, there is nothing un-reviewed — say so and stop. If a run has no operations,
say there were no side-effects to audit (do not invent).

## Step 3 — interpret each operation
Statuses and what they mean:
- `landed` / `rejected_expected` — success. A guardrail rejection (risk check / anti-churn) is the
  system working, NOT a failure.
- `partial` — partial fill or partial multi-write. Note it; judge whether material.
- `degraded` — the row landed but its content looks wrong (e.g. snapshot `spy_close=0`). Worth a
  finding when it recurs.
- `silent_failure` — the headline catch: returned OK but no fresh row. On `place_order` /
  `record_daily_snapshot` this is critical; elsewhere it is a warning unless recurring.
- `rejected_unexpected` / `errored_unrecovered` — a real failure the run did not recover from.
- `unverifiable` — could not confirm (trace-only op, no identifier, or an unknown tool). LOWER your
  confidence; never turn absence of evidence into a `fail`. An `unclassified` tool means the registry
  needs updating — call that out.

## Step 4 — verdict (per run)
`write_review(review_type="operation_success", subject="<run_id> (<date>)", verdict="<prose citing the
operations + statuses>", severity="<pass|info|warn|fail>", confidence=<0-1>, evidence_refs={...the
operations you relied on})`. Default the severity to the tool's `run_severity`, adjusting only with a
stated reason (e.g. a single transient email error you judge immaterial). `unverifiable`-heavy runs
get lower confidence. Then call `mark_run_reviewed(run_id, start_time)` — ONLY after the verdict is
written, so a failed review re-audits the run next time.

## Step 5 — consolidate (selective)
- For a RECURRING or MATERIALLY SIGNIFICANT pattern (e.g. `record_daily_snapshot` silently missing
  across afternoon runs; memory writes consistently stale), call `record_insight(text="<standing
  observation>", source_review_ids=[<this + related ids>])`. Discard one-off noise.
- Update the headline: `write_reviewer_memory(scope="index", value={...})` — one-line summary +
  count + last-seen for "operation_success".
- If a silent failure here also shows up as a skipped/missing tool in `review-tool-fidelity`, call
  `promote_to_global(text, justification, corroborating_review_ids)` (>= 2 reviews).
- Write only via the bound scopes — never a raw namespace, never another task's detail. The
  watermark advances via `mark_run_reviewed`, not by you writing memory.
````

- [ ] **Step 2: Verify the file reads correctly**

Run: `cd agent && python -c "import frontmatter, pathlib; p='src/review_agent/skills/review-operation-success/SKILL.md'; d=frontmatter.load(p); print(d['name'], d['memory_namespace'])"` (if `python-frontmatter` is unavailable, just open the file and confirm the YAML frontmatter + 6 steps are present).
Expected: `review-operation-success operation_success`.

- [ ] **Step 3: Commit**

```bash
git add src/review_agent/skills/review-operation-success/SKILL.md
git commit -m "feat(reviewer): rewrite review-operation-success skill (trace × DB join)"
```

---

## Task 8: Post-deploy verification block

**Files:**
- Modify: `POSTDEPLOY_CHECK.md` (add to the `## Pending Verification` section)

- [ ] **Step 1: Add the verification block**

Add under `## Pending Verification`:

```markdown
### review-operation-success skill (trace × DB join) — shipped 2026-06-19
**Trigger:** first on-demand `operation_success` review run against a real `autonomous_loop` trace
(needs a fired trader run with artifacts in Supabase).
- [ ] `get_operation_success_runs` returns operations with statuses for a real run (happy path).
- [ ] A `landed` order/snapshot/memory write is confirmed against the actual Supabase row.
- [ ] A risk-rejected `place_order` is classified `rejected_expected` (pass), not a failure.
- [ ] An engineered missing-row case yields `silent_failure` (critical → run_severity `fail`).
- [ ] A trace-only op (email) with a clean output is `landed`; with an error flag is `errored_unrecovered`.
- [ ] An unknown/unclassified tool surfaces as `unverifiable` (registry-gap callout), not a silent drop.
- [ ] `mark_run_reviewed` advances the `operation_success` watermark independently of tool_fidelity's.
- [ ] Coverage test `test_every_trader_tool_is_classified` is green in CI.
```

- [ ] **Step 2: Commit**

```bash
git add POSTDEPLOY_CHECK.md
git commit -m "docs(reviewer): post-deploy checks for review-operation-success"
```

---

## Final verification

- [ ] **Run the full reviewer test suite:**

Run: `cd agent && python -m pytest tests/test_run_cursor.py tests/test_operation_success_registry.py tests/test_operation_success_extract.py tests/test_operation_success_probe.py tests/test_operation_success_classify.py tests/test_operation_success_tools.py tests/test_tool_fidelity_watermark.py tests/test_tool_fidelity_completion.py tests/test_tool_fidelity_tools.py tests/test_review_tools_boundary.py -v`
Expected: ALL PASS — new operation-success suite green, tool-fidelity + boundary tests unchanged.

---

## Self-Review

**1. Spec coverage:**
- §1a tool vs operation → READ_ONLY_TOOLS vs OPERATION_SPECS partition (Task 2); reads dropped, ops kept (Task 3).
- §2 trace × Supabase evidence → `get_operation_success_runs` joins `read_run_trace` × `query_database` (Task 6); not-Alpaca/not-logs honored (no broker/log tools used).
- §3b declarative registry → `OPERATION_SPECS` (Task 2).
- §3c match keys → `build_probe_sql` Tier-1 (Task 4); **Tier-2 fuzzy fallback deferred to roadmap (v1 deviation, stated in Global Constraints)**; freshness via `updated_at >= run_start` (Task 5).
- §3d success definition + status taxonomy → `classify_operation` covers landed/rejected_expected/partial/degraded/silent_failure(crit)/rejected_unexpected/errored_unrecovered/unverifiable; carve-outs (guardrail=success, unverifiable≠fail) tested (Task 5).
- §3e content checks → snapshot `degraded` rule (Task 5).
- §3f boundaries → reads dropped, in-progress skipped (`is_finished`), inverse-join absent, tool-errors not double-counted (only affect landing) — Tasks 3/5/6.
- §4 coverage guarantee → partition coverage test + runtime `unclassified` surfacing (Tasks 2/3/5).
- §5 atomic unit/sweep/own watermark → `get_operation_success_runs` sweep + reuse `mark_run_reviewed` bound to `operation_success` (Task 6); independence asserted in POSTDEPLOY (Task 8).
- §6 shared plumbing → `run_cursor.py` extraction (Task 1); `read_run_trace` reused as-is.
- §7 components → run_cursor / operation_success / get_operation_success_runs / coverage test / SKILL.md all present.
- SKILL.md rewrite (Task 7); POSTDEPLOY block (Task 8).

**2. Placeholder scan:** none — every step has concrete code/commands. The two conscious v1 deviations (Tier-2 deferral, fresh-memory rule) are stated in Global Constraints, not hidden.

**3. Type consistency:** the op dict (`tool`/`bucket`/`inputs`/`output`/`error`) is produced by `extract_operations` (Task 3) and consumed by `build_probe_sql` (Task 4) + `classify_operation` (Task 5); the classified dict (`tool`/`status`/`severity`/`detail`/`evidence`) is produced by `classify_operation` and consumed by `run_severity` + the tool (Tasks 5/6). `get_operation_success_runs` signature matches the test and the SKILL.md description. `mark_run_reviewed` reused unchanged.

---

## Execution Handoff

See the handoff message after this plan is saved.
