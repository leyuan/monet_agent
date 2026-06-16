# Reviewer Agent — Phase 1 Implementation Plan (Foundation + A1)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up an independent `review_agent` graph that can run one review skill (A1 `review-strategy-conformance`) end-to-end — read the trading agent's data + LangSmith trace as evidence, judge it, write a verdict, and update its own namespaced memory.

**Architecture:** A 3rd LangGraph graph (`review_agent`), built like the existing chat/autonomy graphs (`create_deep_agent` + `FilesystemBackend`), but with a **read-only tool set + its own write tools** (`write_review`, `write_reviewer_memory`) and **its own skills directory**. It reads the trader's Supabase tables and LangSmith traces as *evidence* (never mutating them) and writes only to its own `agent_reviews` + `reviewer_memory` tables. Memory is hierarchical/namespaced (index + per-type detail + global) and bounded.

**Tech Stack:** Python 3.11, `deepagents>=0.3.11`, `langgraph`, `langsmith`, Supabase (`supabase-py`), pytest + pytest-asyncio, `unittest.mock` (stdlib) for DB/LangSmith mocking.

**Phase boundary (revised 2026-06-15):** Phase 1 builds the **complete, hardened platform + A1 as the one template skill**, then extracts `common/`. Phase 2 is **only the 5 remaining skills** (A2, C1, B1, B2, A4), authored on the finished platform.

**Build order within Phase 1:**
1. Foundation (Tasks 1–7): scaffold, tables, DB helpers, loader, trace, tools+boundary, graph.
2. **Memory hardening (Tasks 10–15)** — done *before* A1 so A1 uses the final API. NOTE: this makes reviewer-memory writes **scope-based** (`write_reviewer_memory(scope=...)` with the namespace bound from `begin_review`), superseding the raw-namespace `write_reviewer_memory(namespace, value)` shown in Tasks 3/6/8. When executing, build the hardened API and have A1 (Task 8) consume it.
3. A1 skill (Task 8) — uses `begin_review` + scope-based writes.
4. Verification (Task 9).
5. **`common/` extraction (Task 16)** — LAST, informed by what the reviewer actually uses; repoints `stock_agent` + `review_agent` + `backtest` imports.

The capability boundary (no trading tools) is enforced by the **tool list** regardless of packaging, so building on `stock_agent` imports first and extracting `common/` last is safe.

---

## Execution Status (update after EVERY task)

- **Mode:** Subagent-Driven (`superpowers:subagent-driven-development`)
- **Execution order:** `1 → 2 → 3 → 4 → 5 → 6 → 10 → 11 → 12 → 13 → 14 → 15 → 7 → 8 → 9 → 16`
  (foundation 1–6 → memory hardening 10–15 → graph wiring 7 → A1 8 → verify 9 → common/ 16)
  NOTE: Task 7 moved AFTER hardening so it wires the final tool set + begin_review/scope-based prompt ONCE (hardening grows REVIEW_TOOLS + changes the write API, so wiring the graph before it would force rework).
- **Last completed:** Foundation 1–6 ✅. **Task 10 ✅ RESOLVED** via **Option A** (commit 4944c9c) — binding moved from ContextVar (broke cross-turn) to thread-scoped Supabase keyed by `thread_id` from the injected `RunnableConfig` (bare annotation — verified langchain only injects the bare form). **Task 17 ✅** (commits 1e43247 + fix) — gated local-Supabase integration harness; prod-safety guard airtight. **Option A VALIDATED LIVE**: 3/3 integration tests pass against local Supabase, incl. cross-turn binding (begin_review turn-1 → write_reviewer_memory turn-2 reads it back). Also fixed a pre-existing equity_snapshots migration-ordering bug to get local Supabase up.
- **Next task:** Task 11 (versioned/reversible detail writes). Then 12 → 13 → 14 → 15 → 7 → 8 → 9 → 16.
- **Local Supabase:** running. Integration tests: `cd agent && RUN_DB_INTEGRATION=1 SUPABASE_URL=http://127.0.0.1:54321 SUPABASE_SERVICE_ROLE_KEY=<local secret> python -m pytest tests/test_integration_reviewer.py` (sandbox must be off for localhost network). Minor hardening deferred: autouse local-URL guard for future integration tests, `--strict-markers`.
- **Working tree:** clean
- **Checkbox convention:** the Execution Status block (Last completed / Next) is the authoritative resume marker; each task header gets ✅ when its spec+quality reviews pass and it's committed.

## Execution & Resume Protocol

Each task is an **atomic commit boundary** — a task is either fully committed or not done. This is what makes a mid-task stop survivable.

1. **Before a task:** confirm `git status` is clean (prior task committed).
2. **During a task:** a fresh subagent implements it via the TDD steps. No commit until that task's tests pass.
3. **After a task:** orchestrator reviews → flip that task's `- [ ]` to `- [x]` → update this **Execution Status** block (Last completed / Next) → **commit code + plan together** in one commit.
4. **On resume (after any stop, crash, or blocker fix):**
   - `git status` — if **dirty**, the last task was partial: finish it, or `git checkout -- .` and redo that task fresh.
   - `git log --oneline` — find the last committed task.
   - Read this plan's checkboxes + the Execution Status block → the **Next task**.
   - Run `cd agent && python -m pytest tests/ -v` to confirm the current state is green.
   - Resume the subagent dispatch at **Next task**.

Because every task ends in a commit and the checkboxes are committed alongside the code, **no completed work is ever lost** — resume = "read the status block, verify green, continue from Next task."

## File Structure

**Create:**
- `agent/src/review_agent/__init__.py` — package marker
- `agent/src/review_agent/db.py` — Supabase CRUD for `agent_reviews` + `reviewer_memory` (reuses `stock_agent`'s client)
- `agent/src/review_agent/trace.py` — `read_run_trace` (LangSmith read-only evidence)
- `agent/src/review_agent/review_memory.py` — `load_review_context()` (bounded loader: index + detail + global + last K)
- `agent/src/review_agent/tools.py` — composes read-only evidence tools + `write_review`/`read_reviewer_memory`/`write_reviewer_memory`; defines `REVIEW_TOOLS`
- `agent/src/review_agent/reviewer.py` — the graph (`review_graph`) + `REVIEW_SYSTEM_PROMPT`
- `agent/src/review_agent/skills/review-strategy-conformance/SKILL.md` — the A1 skill
- `agent/tests/test_review_db.py`, `test_review_memory.py`, `test_review_trace.py`, `test_review_tools_boundary.py`
- `supabase/migrations/20260615000000_reviewer_tables.sql` — `agent_reviews` + `reviewer_memory`

**Modify:**
- `agent/langgraph.json` — register the 3rd graph

**Responsibilities:** `db.py` = raw persistence; `trace.py` = LangSmith evidence; `review_memory.py` = context assembly (bounded); `tools.py` = the agent-facing tool surface + capability boundary; `reviewer.py` = graph wiring + persona/contract; `skills/` = the per-task audit procedure.

---

### Task 1: Scaffold `review_agent` package + register the graph ✅ DONE

**Files:**
- Create: `agent/src/review_agent/__init__.py`
- Create: `agent/src/review_agent/reviewer.py` (minimal compiling stub; fleshed out in Task 7)
- Modify: `agent/langgraph.json`
- Test: `agent/tests/test_review_agent_imports.py`

- [ ] **Step 1: Write the failing test**

```python
# agent/tests/test_review_agent_imports.py
def test_review_graph_importable():
    from review_agent.reviewer import review_graph
    assert review_graph is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd agent && python -m pytest tests/test_review_agent_imports.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'review_agent'`

- [ ] **Step 3: Create the package + a minimal compiling graph**

```python
# agent/src/review_agent/__init__.py
"""Independent reviewer agent — audits the trading agent (read-only)."""
```

```python
# agent/src/review_agent/reviewer.py
"""Reviewer Agent — graph definition (minimal stub; tools/prompt added later)."""
import os
from pathlib import Path

from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend

from stock_agent.middleware import handle_tool_errors, retry_middleware
from stock_agent.tools.memory import query_database

PACKAGE_ROOT = Path(__file__).parent

REVIEW_SYSTEM_PROMPT = "You are an independent reviewer agent. (stub — see Task 7)"

model_name = os.environ.get("MODEL_NAME", "anthropic:claude-sonnet-4-5-20250929")
backend = FilesystemBackend(root_dir=PACKAGE_ROOT, virtual_mode=True)

review_graph = create_deep_agent(
    model=model_name,
    tools=[query_database],
    system_prompt=REVIEW_SYSTEM_PROMPT,
    backend=backend,
    skills=["/skills/"],
    middleware=[handle_tool_errors, retry_middleware],
)
```

Also create the skills dir so the backend has a valid path:
Run: `mkdir -p agent/src/review_agent/skills`

- [ ] **Step 4: Register the graph in `langgraph.json`**

Modify `agent/langgraph.json` — add the third graph entry:

```json
{
  "dependencies": [".", "langchain_anthropic"],
  "graphs": {
    "monet_agent": "./src/stock_agent/agent.py:graph",
    "autonomous_loop": "./src/stock_agent/autonomy.py:autonomous_graph",
    "review_agent": "./src/review_agent/reviewer.py:review_graph"
  },
  "auth": {
    "path": "./src/stock_agent/auth.py:auth"
  },
  "env": ".env"
}
```

- [ ] **Step 5: Verify the package is discoverable by the build**

Check `agent/pyproject.toml` for a `[tool.setuptools]` packages/package-dir section. If packages are explicitly enumerated, add `review_agent`. If it uses src-layout auto-discovery (find), no change needed.
Run: `cd agent && python -c "import review_agent.reviewer as r; print(type(r.review_graph).__name__)"`
Expected: prints a graph type (e.g. `CompiledStateGraph`), no ImportError.

- [ ] **Step 6: Run test to verify it passes**

Run: `cd agent && python -m pytest tests/test_review_agent_imports.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add agent/src/review_agent/__init__.py agent/src/review_agent/reviewer.py agent/langgraph.json agent/tests/test_review_agent_imports.py
git commit -m "feat(reviewer): scaffold review_agent package + register 3rd graph"
```

---

### Task 2: Database migration — `agent_reviews` + `reviewer_memory` ✅ DONE

**Files:**
- Create: `supabase/migrations/20260615000000_reviewer_tables.sql`

- [ ] **Step 1: Write the migration**

```sql
-- supabase/migrations/20260615000000_reviewer_tables.sql

-- agent_reviews: the reviewer's verdicts (append-only audit trail)
create table agent_reviews (
  id uuid primary key default gen_random_uuid(),
  review_type text not null,
  subject text,
  verdict text not null,
  severity text not null default 'info',
  confidence numeric(3,2),
  evidence_refs jsonb default '{}',
  provenance jsonb default '{}',
  created_at timestamptz default now()
);

-- reviewer_memory: the reviewer's standing priors (namespaced: 'index', '{type}:detail', 'global')
create table reviewer_memory (
  id uuid primary key default gen_random_uuid(),
  namespace text unique not null,
  value jsonb not null,
  updated_at timestamptz default now()
);

create index idx_agent_reviews_type_created on agent_reviews(review_type, created_at desc);
create index idx_agent_reviews_created on agent_reviews(created_at desc);

alter table agent_reviews enable row level security;
alter table reviewer_memory enable row level security;

create policy "Authenticated users can read agent_reviews"
  on agent_reviews for select to authenticated using (true);
create policy "Authenticated users can read reviewer_memory"
  on reviewer_memory for select to authenticated using (true);
```

- [ ] **Step 2: Apply + verify (when Supabase is reachable)**

Run (local): `supabase db reset` — applies all migrations.
Or verify against the live project that the tables exist:
Run: `cd agent && python -c "from stock_agent.supabase_client import get_supabase; print(get_supabase().table('reviewer_memory').select('*').limit(1).execute().data)"`
Expected: `[]` (empty list — table exists, no rows), no error.

- [ ] **Step 3: Commit**

```bash
git add supabase/migrations/20260615000000_reviewer_tables.sql
git commit -m "feat(reviewer): add agent_reviews + reviewer_memory tables"
```

---

### Task 3: DB helpers (`review_agent/db.py`) ✅ DONE

**Files:**
- Create: `agent/src/review_agent/db.py`
- Test: `agent/tests/test_review_db.py`

- [ ] **Step 1: Write the failing tests** (mock the Supabase client; assert correct table/columns)

```python
# agent/tests/test_review_db.py
from unittest.mock import MagicMock, patch


@patch("review_agent.db.get_supabase")
def test_write_review_inserts_row(mock_get):
    sb = MagicMock()
    sb.table.return_value.insert.return_value.execute.return_value.data = [{"id": "abc"}]
    mock_get.return_value = sb
    from review_agent.db import write_review

    row = write_review("conformance", "run-2026-06-07", "Obeyed all hard rules.", "pass", 0.9)
    sb.table.assert_called_with("agent_reviews")
    args = sb.table.return_value.insert.call_args[0][0]
    assert args["review_type"] == "conformance"
    assert args["severity"] == "pass"
    assert row == {"id": "abc"}


@patch("review_agent.db.get_supabase")
def test_list_recent_reviews_filters_by_type(mock_get):
    sb = MagicMock()
    chain = sb.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value
    chain.execute.return_value.data = [{"verdict": "x"}]
    mock_get.return_value = sb
    from review_agent.db import list_recent_reviews

    out = list_recent_reviews("conformance", limit=5)
    sb.table.return_value.select.return_value.eq.assert_called_with("review_type", "conformance")
    assert out == [{"verdict": "x"}]


@patch("review_agent.db.get_supabase")
def test_reviewer_memory_roundtrip(mock_get):
    sb = MagicMock()
    sb.table.return_value.upsert.return_value.execute.return_value.data = [{"namespace": "global"}]
    sb.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = {"value": {"k": 1}}
    mock_get.return_value = sb
    from review_agent.db import write_reviewer_memory, read_reviewer_memory

    write_reviewer_memory("global", {"k": 1})
    sb.table.return_value.upsert.assert_called()
    assert read_reviewer_memory("global") == {"value": {"k": 1}}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd agent && python -m pytest tests/test_review_db.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'review_agent.db'`

- [ ] **Step 3: Implement `review_agent/db.py`**

```python
# agent/src/review_agent/db.py
"""Supabase CRUD for the reviewer's own stores (agent_reviews + reviewer_memory).

Reuses the trading agent's Supabase client. The reviewer NEVER writes to the
trader's tables — only to these two.
"""
import logging

from stock_agent.supabase_client import get_supabase

logger = logging.getLogger(__name__)


def write_review(
    review_type: str,
    subject: str | None,
    verdict: str,
    severity: str = "info",
    confidence: float | None = None,
    evidence_refs: dict | None = None,
    provenance: dict | None = None,
) -> dict:
    """Append a review verdict row to agent_reviews."""
    sb = get_supabase()
    row = {
        "review_type": review_type,
        "subject": subject,
        "verdict": verdict,
        "severity": severity,
        "confidence": confidence,
        "evidence_refs": evidence_refs or {},
        "provenance": provenance or {},
    }
    result = sb.table("agent_reviews").insert(row).execute()
    return result.data[0]


def list_recent_reviews(review_type: str, limit: int = 5) -> list[dict]:
    """Most-recent verdicts for a review type (recency window)."""
    sb = get_supabase()
    result = (
        sb.table("agent_reviews")
        .select("*")
        .eq("review_type", review_type)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return result.data or []


def read_reviewer_memory(namespace: str) -> dict | None:
    """Read one reviewer_memory entry by namespace."""
    try:
        sb = get_supabase()
        result = (
            sb.table("reviewer_memory")
            .select("*")
            .eq("namespace", namespace)
            .maybe_single()
            .execute()
        )
        return result.data if result else None
    except Exception:
        logger.warning("Failed to read reviewer_memory namespace=%s", namespace)
        return None


def write_reviewer_memory(namespace: str, value: dict) -> dict:
    """Upsert one reviewer_memory entry."""
    sb = get_supabase()
    result = (
        sb.table("reviewer_memory")
        .upsert({"namespace": namespace, "value": value, "updated_at": "now()"}, on_conflict="namespace")
        .execute()
    )
    return result.data[0]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd agent && python -m pytest tests/test_review_db.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add agent/src/review_agent/db.py agent/tests/test_review_db.py
git commit -m "feat(reviewer): db helpers for agent_reviews + reviewer_memory"
```

---

### Task 4: Bounded context loader (`review_agent/review_memory.py`) ✅ DONE

**Files:**
- Create: `agent/src/review_agent/review_memory.py`
- Test: `agent/tests/test_review_memory.py`

- [ ] **Step 1: Write the failing tests**

```python
# agent/tests/test_review_memory.py
from unittest.mock import patch


@patch("review_agent.review_memory.list_recent_reviews")
@patch("review_agent.review_memory.read_reviewer_memory")
def test_load_context_includes_only_current_task_detail(mock_read, mock_recent):
    def fake_read(ns):
        return {
            "index": {"value": {"conformance": "clean 5 runs", "efficacy": "flagged 3x"}},
            "conformance:detail": {"value": {"patterns": ["anti-churn respected"]}},
            "global": {"value": {"bias": "over-bullish in low VIX"}},
        }.get(ns)
    mock_read.side_effect = fake_read
    mock_recent.return_value = [{"created_at": "2026-06-07", "severity": "pass", "verdict": "ok"}]
    from review_agent.review_memory import load_review_context

    ctx = load_review_context("conformance")
    assert "anti-churn respected" in ctx          # current task detail loaded
    assert "over-bullish in low VIX" in ctx        # global always loaded
    assert "efficacy" in ctx                        # index one-liner present
    assert "flagged 3x" in ctx                      # other task's index entry...
    # ...but NOT other task's *detail* (we never read efficacy:detail)
    assert "efficacy:detail" not in [c.args[0] for c in mock_read.call_args_list]


@patch("review_agent.review_memory.list_recent_reviews")
@patch("review_agent.review_memory.read_reviewer_memory")
def test_load_context_fresh_when_no_namespace(mock_read, mock_recent):
    mock_read.return_value = None
    mock_recent.return_value = []
    from review_agent.review_memory import load_review_context

    ctx = load_review_context("brand_new_type")
    assert "fresh" in ctx.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd agent && python -m pytest tests/test_review_memory.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'review_agent.review_memory'`

- [ ] **Step 3: Implement `review_agent/review_memory.py`**

```python
# agent/src/review_agent/review_memory.py
"""Bounded context loader for a review run.

Loads ONLY: the index (all tasks, one-liners) + the CURRENT task's detail +
global insights + the last K verdicts of this type. Never loads other tasks'
detail (kept isolated for objectivity). Context stays flat over time.
"""
import json

from review_agent.db import list_recent_reviews, read_reviewer_memory

K_RECENT = 5


def _fmt(mem: dict | None) -> str:
    if not mem or not mem.get("value"):
        return "(none yet — fresh)"
    return json.dumps(mem["value"], indent=2)


def load_review_context(review_type: str) -> str:
    """Assemble the bounded memory block for a review of `review_type`."""
    index = read_reviewer_memory("index")
    detail = read_reviewer_memory(f"{review_type}:detail")
    glob = read_reviewer_memory("global")
    recent = list_recent_reviews(review_type, limit=K_RECENT)

    parts = [
        "## Reviewer memory (PRIORS only — always re-read ground-truth evidence; "
        "memory never determines a verdict)",
        "",
        "### Index — all review tasks (headlines + links)",
        _fmt(index),
        "",
        "### Global insights (apply to every task)",
        _fmt(glob),
        "",
        f"### Standing detail for '{review_type}'",
        _fmt(detail),
        "",
        f"### Last {len(recent)} '{review_type}' verdicts",
    ]
    if recent:
        for r in recent:
            parts.append(f"- [{r['created_at']}] {r['severity']}: {r['verdict']}")
    else:
        parts.append("(none yet — fresh)")
    return "\n".join(parts)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd agent && python -m pytest tests/test_review_memory.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add agent/src/review_agent/review_memory.py agent/tests/test_review_memory.py
git commit -m "feat(reviewer): bounded namespaced context loader"
```

---

### Task 5: LangSmith trace evidence (`review_agent/trace.py`) ✅ DONE

**Files:**
- Create: `agent/src/review_agent/trace.py`
- Test: `agent/tests/test_review_trace.py`

- [ ] **Step 1: Write the failing test** (mock the LangSmith Client)

```python
# agent/tests/test_review_trace.py
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


@patch("review_agent.trace.Client")
def test_read_run_trace_extracts_tool_calls(mock_client_cls):
    client = MagicMock()
    root = SimpleNamespace(id="root-1", name="autonomous_loop", trace_id="t1",
                           start_time="2026-06-07", error=None, run_type="chain")
    tool = SimpleNamespace(name="query_database", inputs={"q": "x"}, outputs={"rows": 1},
                           error=None, run_type="tool")
    llm = SimpleNamespace(name="model", inputs={}, outputs={}, error=None, run_type="llm")
    client.list_runs.side_effect = [[root], [root, tool, llm]]  # roots, then children
    mock_client_cls.return_value = client
    from review_agent.trace import read_run_trace

    out = read_run_trace(limit=1)
    assert out["runs"][0]["name"] == "autonomous_loop"
    assert out["runs"][0]["tool_calls"] == [
        {"name": "query_database", "inputs": {"q": "x"}, "outputs": {"rows": 1}, "error": None}
    ]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd agent && python -m pytest tests/test_review_trace.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'review_agent.trace'`

- [ ] **Step 3: Implement `review_agent/trace.py`**

```python
# agent/src/review_agent/trace.py
"""Read-only LangSmith trace evidence for the reviewer.

Reads the TRADING agent's run traces (tool calls + inputs/outputs/errors) as
evidence. Project name comes from LANGSMITH_PROJECT (currently 'monet_agent') —
never hardcoded. The reviewer only READS LangSmith; it never writes there.
"""
import os

from langsmith import Client


def read_run_trace(
    run_id: str | None = None,
    limit: int = 1,
) -> dict:
    """Fetch trading-agent run trace(s) from LangSmith.

    Args:
        run_id: a specific root run id; if omitted, fetches the most recent root run(s).
        limit: how many recent root runs to fetch when run_id is not given.

    Returns:
        {"project": str, "runs": [{run_id, name, start_time, error, tool_calls:[...]}]}
        where each tool_call = {name, inputs, outputs, error}.
    """
    project = os.environ.get("LANGSMITH_PROJECT", "monet_agent")
    client = Client()

    if run_id:
        roots = [client.read_run(run_id)]
    else:
        roots = list(client.list_runs(project_name=project, is_root=True, limit=limit))

    runs_out = []
    for root in roots:
        children = list(client.list_runs(project_name=project, trace_id=root.trace_id))
        tool_calls = [
            {"name": c.name, "inputs": c.inputs, "outputs": c.outputs, "error": c.error}
            for c in children
            if c.run_type == "tool"
        ]
        runs_out.append(
            {
                "run_id": str(root.id),
                "name": root.name,
                "start_time": str(root.start_time),
                "error": root.error,
                "tool_calls": tool_calls,
            }
        )
    return {"project": project, "runs": runs_out}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd agent && python -m pytest tests/test_review_trace.py -v`
Expected: PASS

- [ ] **Step 5: Validate against a real trace (manual, optional now)**

Run: `cd agent && python -c "from dotenv import load_dotenv; load_dotenv('.env'); from review_agent.trace import read_run_trace; import json; print(json.dumps(read_run_trace(limit=1), default=str)[:1500])"`
Expected: a JSON blob with the most recent `autonomous_loop` run and its `tool_calls`. (Confirmed feasible by the 2026-06-15 F4 probe.)

- [ ] **Step 6: Commit**

```bash
git add agent/src/review_agent/trace.py agent/tests/test_review_trace.py
git commit -m "feat(reviewer): read_run_trace LangSmith evidence tool"
```

---

### Task 6: Compose `REVIEW_TOOLS` + capability-boundary guard test ✅ DONE

**Files:**
- Create: `agent/src/review_agent/tools.py`
- Test: `agent/tests/test_review_tools_boundary.py`

- [ ] **Step 1: Write the failing boundary test** (this enforces the security boundary)

```python
# agent/tests/test_review_tools_boundary.py
FORBIDDEN = {
    "place_order", "cancel_order", "attach_bracket_to_position",
    "write_agent_memory", "write_journal_entry", "manage_watchlist",
    "update_market_regime", "update_stock_analysis", "record_decision",
}


def test_review_tools_contain_no_trading_or_trader_mutation():
    from review_agent.tools import REVIEW_TOOLS
    names = {t.__name__ for t in REVIEW_TOOLS}
    leaked = names & FORBIDDEN
    assert not leaked, f"reviewer must not have these capabilities: {leaked}"


def test_review_tools_include_evidence_and_own_writers():
    from review_agent.tools import REVIEW_TOOLS
    names = {t.__name__ for t in REVIEW_TOOLS}
    assert {"query_database", "read_run_trace", "write_review",
            "read_reviewer_memory", "write_reviewer_memory"} <= names
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd agent && python -m pytest tests/test_review_tools_boundary.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'review_agent.tools'`

- [ ] **Step 3: Implement `review_agent/tools.py`**

```python
# agent/src/review_agent/tools.py
"""The reviewer's tool surface — READ-ONLY evidence + its OWN write tools.

Capability boundary: this list contains NO trading tools and NO tools that
mutate the trader's data. Enforced by tests/test_review_tools_boundary.py.
"""
# Read-only evidence tools, reused from the trading agent's package
from stock_agent.tools.memory import (
    query_database,
    read_agent_memory,
    read_all_agent_memory,
)
from stock_agent.tools.reports import get_performance_comparison

# Reviewer's own stores + LangSmith evidence
from review_agent.db import (
    write_review as _write_review,
    read_reviewer_memory as _read_rm,
    write_reviewer_memory as _write_rm,
)
from review_agent.trace import read_run_trace


def write_review(
    review_type: str,
    subject: str,
    verdict: str,
    severity: str = "info",
    confidence: float | None = None,
    evidence_refs: dict | None = None,
) -> dict:
    """Record a review verdict to the reviewer's own audit trail (agent_reviews).

    Args:
        review_type: which review this is (e.g. 'conformance'). Determines the namespace.
        subject: what was reviewed (e.g. a run id / date / description).
        verdict: the finding, in prose.
        severity: one of 'pass', 'info', 'warn', 'fail'.
        confidence: 0.0-1.0.
        evidence_refs: dict of what you looked at (run ids, journal ids, table names).

    Returns:
        {"review_id": str, "status": "written"}
    """
    row = _write_review(review_type, subject, verdict, severity, confidence, evidence_refs)
    return {"review_id": row["id"], "status": "written"}


def read_reviewer_memory(namespace: str) -> dict:
    """Read one of the reviewer's own memory namespaces (e.g. 'conformance:detail', 'global', 'index')."""
    mem = _read_rm(namespace)
    return {"namespace": namespace, "value": mem["value"] if mem else None}


def write_reviewer_memory(namespace: str, value: dict) -> dict:
    """Write/overwrite one of the reviewer's own memory namespaces.

    Args:
        namespace: 'index', 'global', or '{review_type}:detail'. Write the CURRENT
            review's detail to '{review_type}:detail' — do not write other tasks' namespaces.
        value: the distilled standing content (JSON-serializable dict).

    Returns:
        {"namespace": str, "status": "written"}
    """
    _write_rm(namespace, value)
    return {"namespace": namespace, "status": "written"}


REVIEW_TOOLS = [
    # evidence (read-only)
    query_database,
    read_agent_memory,
    read_all_agent_memory,
    get_performance_comparison,
    read_run_trace,
    # the reviewer's own stores
    write_review,
    read_reviewer_memory,
    write_reviewer_memory,
]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd agent && python -m pytest tests/test_review_tools_boundary.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add agent/src/review_agent/tools.py agent/tests/test_review_tools_boundary.py
git commit -m "feat(reviewer): REVIEW_TOOLS surface + capability-boundary guard test"
```

---

### Task 7: Flesh out the graph — `REVIEW_SYSTEM_PROMPT` + real tools

**Files:**
- Modify: `agent/src/review_agent/reviewer.py`
- Test: `agent/tests/test_review_agent_imports.py` (extend)

- [ ] **Step 1: Extend the test to assert the real tool set + prompt are wired**

```python
# append to agent/tests/test_review_agent_imports.py
def test_review_graph_uses_review_tools_and_skeptic_prompt():
    from review_agent import reviewer
    from review_agent.tools import REVIEW_TOOLS
    assert reviewer.REVIEW_TOOLS is REVIEW_TOOLS
    assert "evidence" in reviewer.REVIEW_SYSTEM_PROMPT.lower()
    assert "never determines a verdict" in reviewer.REVIEW_SYSTEM_PROMPT.lower() or \
           "re-read" in reviewer.REVIEW_SYSTEM_PROMPT.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd agent && python -m pytest tests/test_review_agent_imports.py -v`
Expected: FAIL — `AttributeError: module 'review_agent.reviewer' has no attribute 'REVIEW_TOOLS'` (stub used `[query_database]` inline).

- [ ] **Step 3: Replace `reviewer.py` with the full version**

```python
# agent/src/review_agent/reviewer.py
"""Reviewer Agent — independent auditor of the trading agent (read-only)."""
import os
from pathlib import Path

from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend

from stock_agent.middleware import handle_tool_errors, retry_middleware
from review_agent.tools import REVIEW_TOOLS

PACKAGE_ROOT = Path(__file__).parent

REVIEW_SYSTEM_PROMPT = """\
You are an INDEPENDENT REVIEWER agent. Your job is to AUDIT the Monet trading agent — \
judge whether it thinks properly, follows its strategy, calls the right tools, completes \
its operations, and whether it is rationalizing. You JUDGE and OBSERVE; you NEVER act in \
the trading domain.

## Objectivity (non-negotiable)
- You read the trading agent's data, journal, decisions, and LangSmith traces as EVIDENCE \
to audit — never as beliefs to adopt.
- A verdict is ALWAYS computed from freshly-read ground-truth evidence. Your memory supplies \
PRIORS only — it can never DETERMINE a verdict. If a prior conflicts with this run's evidence, \
the evidence wins.
- You are skeptical by default. Your value is catching what self-review cannot: rule violations, \
silent failures, and the agent rationalizing its own mistakes.

## Picking a review (routing)
- If the request names a specific review type, run that one.
- If it is ambiguous or names something you have no skill for, run `review-general` or ask — \
do NOT force a low-confidence specific review.
- Read your skills in /skills/ and follow the matching SKILL.md exactly.

## Memory contract (every review)
- At the START: your bounded memory block (index + this task's detail + global insights + \
recent verdicts) is provided. Use it as priors only.
- At the END (consolidation, REQUIRED): call `write_review(...)` with your verdict, then update \
`{review_type}:detail` and the `index` via `write_reviewer_memory(...)`. Promote only RECURRING or \
MATERIALLY SIGNIFICANT observations to standing memory — discard one-off noise. Write only the \
CURRENT review's namespace; never overwrite another task's detail.

## Boundaries
- You have NO trading tools and CANNOT mutate the trader's data. You write ONLY to your own \
`agent_reviews` and `reviewer_memory` stores.
"""

model_name = os.environ.get("MODEL_NAME", "anthropic:claude-sonnet-4-5-20250929")
backend = FilesystemBackend(root_dir=PACKAGE_ROOT, virtual_mode=True)

review_graph = create_deep_agent(
    model=model_name,
    tools=REVIEW_TOOLS,
    system_prompt=REVIEW_SYSTEM_PROMPT,
    backend=backend,
    skills=["/skills/"],
    middleware=[handle_tool_errors, retry_middleware],
)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd agent && python -m pytest tests/test_review_agent_imports.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add agent/src/review_agent/reviewer.py agent/tests/test_review_agent_imports.py
git commit -m "feat(reviewer): skeptic-persona prompt + full tool wiring"
```

---

### Task 8: A1 skill — `review-strategy-conformance/SKILL.md`

**Files:**
- Create: `agent/src/review_agent/skills/review-strategy-conformance/SKILL.md`
- Test: `agent/tests/test_skill_wellformed.py`

- [ ] **Step 1: Write a structural test for the skill file**

```python
# agent/tests/test_skill_wellformed.py
from pathlib import Path

SKILL = Path(__file__).parent.parent / "src/review_agent/skills/review-strategy-conformance/SKILL.md"


def test_a1_skill_exists_and_declares_required_fields():
    text = SKILL.read_text()
    assert SKILL.exists()
    # Authoring rubric: frontmatter declares identity + memory scope
    assert "name:" in text
    assert "memory_namespace: conformance" in text
    # Rubric: disjoint description, self-check, consolidation, write_review
    assert "Use when" in text and "Do NOT use" in text
    assert "write_review" in text
    assert "write_reviewer_memory" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd agent && python -m pytest tests/test_skill_wellformed.py -v`
Expected: FAIL — `FileNotFoundError` (skill not created yet)

- [ ] **Step 3: Write the SKILL.md**

```markdown
---
name: review-strategy-conformance
description: >
  Audit whether a trading run obeyed Monet's HARD RULES. Use when asked to review a
  run/period for rule compliance, discipline, or "did it follow strategy". Do NOT use
  for reasoning quality (use review-decision-quality), strategy efficacy (use
  review-strategy-efficacy), or tool-call correctness (use review-tool-fidelity).
memory_namespace: conformance
memory_access: { read: own, write: own }
tags: [rules, process, discipline]
---

# Review: Strategy Conformance

You are auditing whether a trading run **obeyed Monet's hard rules**. You judge against
the rules; you do not second-guess the strategy itself.

## Step 0 — Self-announce + fit-check
State: "Running a CONFORMANCE review of {subject} because {reason}." If the request is
really about reasoning quality, efficacy, or tool calls, STOP and route to the right
skill (or `review-general`).

## Step 1 — Load priors
Your bounded memory block (index + `conformance:detail` + global + last 5 conformance
verdicts) is already in context. Treat it as PRIORS only.

## Step 2 — Pull the ground-truth evidence (always re-read)
Use `query_database` to read, for the subject run/period:
- `trades` placed (symbol, side, qty, created_at, status, filled_avg_price)
- `agent_journal` entries (the run's market_scan / trade entries)
- `agent_memory` decision records (`decision:*`) and `factor_rankings`
Optionally use `read_run_trace` to see what actually executed.

## Step 3 — Check each hard rule (from CLAUDE.md "Important Rules")
For the run, verify and note PASS / WARN / FAIL with evidence for each:
1. **Regime gate** — if VIX > 26 AND breadth < 30%, were new BUYs blocked?
2. **Anti-churn** — any SELL inside the 5-day minimum hold? Any position re-entered too fast?
3. **Position count** — did holdings stay within 5–8 positions?
4. **Position size** — any position > 10% of equity?
5. **Cash buffer** — was ≥ 20% cash maintained?
6. **Earnings guard** — any BUY within 5 days of earnings?
7. **Stop-loss / bracket** — does every new position have a stop?
8. **AI soft caps** — if AI durability/bubble high, ≤ 1 new AI buy?

## Step 4 — Verdict
Decide an overall `severity`: `pass` (all clean), `warn` (minor/soft-rule), or `fail`
(a hard rule was broken). Write it:
`write_review(review_type="conformance", subject="<run/date>", verdict="<prose with
specifics>", severity="<pass|warn|fail>", confidence=<0-1>, evidence_refs={...})`

## Step 5 — Consolidate memory (REQUIRED)
- Update `conformance:detail` via `write_reviewer_memory("conformance:detail", {...})`:
  keep only RECURRING or MATERIAL patterns (e.g. "anti-churn respected 6 runs",
  "repeatedly near 10% cap on NVDA"); prune one-offs.
- Update the `index` entry for `conformance` (one-line headline + count + last-seen).
- If a finding clearly generalizes to ALL reviews (e.g. a systematic bias), note it for
  `global` — but only if it recurs.
- Write ONLY the conformance namespace. Never touch another task's detail.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd agent && python -m pytest tests/test_skill_wellformed.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agent/src/review_agent/skills/review-strategy-conformance/SKILL.md agent/tests/test_skill_wellformed.py
git commit -m "feat(reviewer): A1 review-strategy-conformance skill"
```

---

### Task 9: End-to-end verification

**Files:**
- (no new files — full-suite + manual smoke)

- [ ] **Step 1: Run the full reviewer test suite**

Run: `cd agent && python -m pytest tests/ -v`
Expected: all PASS (imports, db, memory, trace, tools-boundary, skill-wellformed).

- [ ] **Step 2: Confirm all three graphs compile under langgraph**

Run: `cd agent && python -c "import review_agent.reviewer, stock_agent.agent, stock_agent.autonomy; print('all graphs import OK')"`
Expected: `all graphs import OK`

- [ ] **Step 3: Manual smoke (requires ANTHROPIC credits + local server)**

Start: `cd agent && langgraph dev` (in a separate shell)
Then trigger a conformance review against the `review_agent` graph with a message like:
"Run a strategy-conformance review of the most recent autonomous_loop run."
Expected: a row appears in `agent_reviews` (`review_type='conformance'`), and
`reviewer_memory` has an `index` + `conformance:detail` entry. (Defer if credits are
still exhausted — see [[monet-agent-architecture]]; everything above is testable without it.)

- [ ] **Step 4: Update release log + POSTDEPLOY_CHECK**

- Add a `release-log.tsx` entry (new reviewer agent, A1 conformance review).
- Add a `POSTDEPLOY_CHECK.md` "Pending Verification" block for the reviewer (trigger: first conformance review; checkboxes: verdict row written, memory index/detail written, boundary holds, `read_run_trace` returns tool calls, fresh-vs-cumulative behavior).

- [ ] **Step 5: Commit**

```bash
git add web/components/trading/release-log.tsx POSTDEPLOY_CHECK.md
git commit -m "docs(reviewer): release log + postdeploy verification for reviewer v1"
```

---

## Phase 1 (cont.) — Memory platform hardening + `common/` extraction

> These build the "platform guarantees" from the spec. Execute Tasks 10–15 **before** A1 (Task 8) so A1 uses the final scope-based API. Each is TDD (failing test → implement → pass → commit), same rhythm as Tasks 1–9. Concrete designs below.

### Task 10: Structural namespace-binding (`begin_review` + scope-based writes)

**Files:** Modify `review_agent/tools.py`, `review_agent/review_memory.py`; Test `tests/test_namespace_binding.py`

- [ ] Add `review_agent/context.py` with a `ContextVar`:
```python
# agent/src/review_agent/context.py
from contextvars import ContextVar
active_review_type: ContextVar[str | None] = ContextVar("active_review_type", default=None)
```
- [ ] `begin_review(review_type: str, subject: str, reason: str) -> dict` tool: sets `active_review_type`, logs routing (Task 15), returns `{"context": load_review_context(review_type), "subject": subject}`.
- [ ] Replace `write_reviewer_memory(namespace, value)` with `write_reviewer_memory(scope: Literal["detail","global","index"], value: dict)`: resolves `detail → f"{active}:detail"`; raises if `active_review_type` is unset or scope invalid. **The LLM can no longer pass a raw namespace.**
- [ ] **Test:** after `begin_review("conformance",...)`, `write_reviewer_memory("detail", {...})` writes `conformance:detail`; calling write with no active review raises; `scope="efficacy:detail"` (raw) is impossible (type-rejected). 

### Task 11: Versioned / reversible detail writes

**Files:** Modify `review_agent/db.py`; Test `tests/test_memory_versioning.py`

- [ ] On `write_reviewer_memory`, before overwrite, push prior value into `value["_history"]` (cap 5 most recent). Add `revert_reviewer_memory(namespace)` restoring the last `_history` entry.
- [ ] **Test:** write A then B → stored value is B, `_history[0]` is A; `revert` → value is A again. Raw verdicts in `agent_reviews` are untouched (assert not modified).

### Task 12: Provenance schema on standing insights

**Files:** Modify `review_agent/db.py` (helper); Test `tests/test_provenance.py`

- [ ] Standing detail/global insights use shape: `{"patterns": [{"text", "source_review_ids": [...], "confidence", "first_seen", "last_seen", "count"}]}`. Add `stamp_insight(text, source_review_ids, confidence)` helper that builds/updates an entry (increments `count`, updates `last_seen`).
- [ ] **Test:** stamping the same `text` twice merges (count=2, source_ids unioned), not duplicates.

### Task 13: Confidence quarantine

**Files:** Modify `review_agent/db.py` + `review_memory.py`; Test `tests/test_quarantine.py`

- [ ] New insight enters `confidence="low"` (count=1); `stamp_insight` promotes to `"established"` at `count >= 3`. `load_review_context` labels low-confidence insights `(unconfirmed)`.
- [ ] **Test:** first stamp → low; third → established; loader prefixes unconfirmed ones.

### Task 14: Global-promotion gate

**Files:** Modify `review_agent/tools.py`; Test `tests/test_global_gate.py`

- [ ] `promote_to_global(text: str, justification: str, corroborating_review_ids: list[str]) -> dict`: requires `len(corroborating_review_ids) >= 2`, else returns `{"status":"rejected","reason":...}` and writes nothing. On success, `stamp_insight` into the `global` namespace.
- [ ] **Test:** 1 ref → rejected, global unchanged; 2 refs → written to global with provenance.

### Task 15: Routing logger

**Files:** Modify `review_agent/tools.py` (inside `begin_review`); Test `tests/test_routing_log.py`

- [ ] `begin_review` appends `{review_type, reason, subject, ts}` to the `routing_log` reviewer_memory namespace (capped list). (Used later to measure misroute rate.)
- [ ] **Test:** two `begin_review` calls → `routing_log` has two entries, newest first.

### Task 16: `common/` extraction (F2)

**Files:** Create `agent/src/common/` (move `supabase_client.py`, read-only db fns, read-only tool fns); Modify imports in `stock_agent/*`, `review_agent/*`, `backtest/*`; Test: full suite + import check.

- [ ] Create `agent/src/common/` package. Move `supabase_client.py` there. Move the **read-only** db functions (`read_memory`, journal/trades reads) and the read-only tool functions the reviewer uses (`query_database`, `read_agent_memory`, `read_all_agent_memory`, `get_performance_comparison`) into `common/`.
- [ ] Repoint imports: `stock_agent` and `backtest` import these from `common/`; `review_agent` imports from `common/` (no longer from `stock_agent`). Update `pyproject.toml` packages if explicitly listed.
- [ ] **Verify:** `cd agent && python -m pytest tests/ -v` all pass; `python -c "import stock_agent.agent, stock_agent.autonomy, review_agent.reviewer; print('ok')"`; confirm `review_agent` no longer imports from `stock_agent` (`grep -rn "import stock_agent" src/review_agent/` → only intentional, ideally none).
- [ ] **Commit:** `git commit -m "refactor: extract common/ shared core; review_agent imports from common"`

---

## Self-Review

**Spec coverage:** F1 (Task 1), F3 (Tasks 2–3), memory model loader (Task 4), F5 `read_run_trace` (Task 5), tool boundary D4 (Task 6), skeptic prompt + consolidation contract + objectivity invariant (Task 7), A1 skill + authoring rubric per-skill checklist (Task 8). **Memory platform guarantees now IN Phase 1** (revised scope): structural namespace-binding (Task 10), versioning/reversibility (Task 11), provenance schema (Task 12), confidence quarantine (Task 13), global-promotion gate (Task 14), routing logger (Task 15). **F2 `common/` extraction** = Task 16. **Only B1/B2, A2, C1, A4 → Phase 2** (the 5 remaining skills). No spec requirement left unaddressed in Phase 1.

**Placeholder scan:** No "TBD/TODO/handle appropriately". All code blocks complete. Manual smoke (Task 9 Step 3) is explicitly gated on credits, not a placeholder.

**Type consistency:** `write_review(review_type, subject, verdict, severity, confidence, evidence_refs, provenance)` consistent across db.py (Task 3) and tools.py (Task 6, omits provenance in the tool wrapper — wrapper intentionally exposes a subset). `read_reviewer_memory`/`write_reviewer_memory` signatures consistent across db.py, tools.py, review_memory.py. `read_run_trace(run_id, limit)` consistent (Task 5 ↔ Task 6 list). `REVIEW_TOOLS` name consistent (Tasks 6, 7). Namespace strings (`index`, `global`, `{type}:detail`) consistent across review_memory.py, tools.py, SKILL.md.
