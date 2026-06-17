"""The reviewer's tool surface — READ-ONLY evidence + its OWN write tools.

Capability boundary: this list contains NO trading tools and NO tools that
mutate the trader's data. Enforced by tests/test_review_tools_boundary.py.
"""
from datetime import date
from typing import Literal

from langchain_core.runnables import RunnableConfig

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
    set_active_review as _set_active,
    get_active_review as _get_active,
    append_routing_log as _append_routing_log,
    read_watermark as _read_watermark,
    write_watermark as _write_watermark,
)
from review_agent.trace import read_run_trace
from review_agent.review_memory import load_review_context
from review_agent.insights import stamp_insight
from review_agent.tool_fidelity import (
    identify_phase, analyze_tool_fidelity, select_unreviewed, advance_cursor, is_finished,
)
from datetime import datetime as _dt


def _thread_id(config: RunnableConfig | None) -> str:
    tid = ((config or {}).get("configurable") or {}).get("thread_id")
    if not tid:
        raise ValueError("No thread_id in RunnableConfig — cannot bind the review.")
    return tid


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


def begin_review(review_type: str, subject: str, reason: str, config: RunnableConfig = None) -> dict:
    """Start a review: bind the active review type for this thread, log the routing
    decision, and return the bounded prior-context. `config` is injected by the runtime."""
    tid = _thread_id(config)
    _set_active(tid, review_type)
    _append_routing_log({
        "review_type": review_type, "subject": subject, "reason": reason,
        "thread_id": tid, "ts": date.today().isoformat(),
    })
    return {"review_type": review_type, "subject": subject, "context": load_review_context(review_type)}


def write_reviewer_memory(scope: Literal["detail", "global", "index"], value: dict, config: RunnableConfig = None) -> dict:
    """Write one of the reviewer's own memory scopes for the ACTIVE review.

    The namespace is BOUND from the active review type (set by begin_review and
    persisted in Supabase keyed by thread_id) — the caller chooses only the
    scope, never a raw namespace. 'detail' → '{active_review_type}:detail';
    'global'/'index' are shared scopes.

    Args:
        scope: one of 'detail', 'global', 'index'.
        value: the data to write.

    Raises:
        ValueError if no review is active for this thread or the scope is invalid.

    Note: `config` is injected by the runtime — not supplied by the LLM.
    """
    rt = _get_active(_thread_id(config))
    if rt is None:
        raise ValueError("No active review for this thread — call begin_review first.")
    if scope == "detail":
        namespace = f"{rt}:detail"
    elif scope in ("global", "index"):
        namespace = scope
    else:
        raise ValueError(f"Invalid scope {scope!r}; must be 'detail', 'global', or 'index'.")
    _write_rm(namespace, value)
    return {"namespace": namespace, "scope": scope, "status": "written"}


def record_insight(text: str, source_review_ids: list[str], config: RunnableConfig = None) -> dict:
    """Merge a provenance-stamped insight into the ACTIVE review's standing DETAIL memory.
    Confidence is derived from corroboration count (low until seen 3x, then established) — the
    deterministic logic lives here, not in the LLM. Use this (not raw write_reviewer_memory) to
    record recurring/material findings during consolidation. The namespace is bound by begin_review.

    Args:
        text: the standing observation (e.g. 'anti-churn respected across the week').
        source_review_ids: review ids that evidence this observation.

    Returns:
        {"namespace": str, "patterns": int} — the detail namespace and current pattern count.
    """
    rt = _get_active(_thread_id(config))
    if rt is None:
        raise ValueError("No active review — call begin_review first.")
    namespace = f"{rt}:detail"
    current = _read_rm(namespace)
    value = current["value"] if (current and isinstance(current.get("value"), dict)) else {}
    patterns = value.get("patterns", [])
    stamp_insight(patterns, text, source_review_ids, date.today().isoformat())
    value["patterns"] = patterns
    _write_rm(namespace, value)
    return {"namespace": namespace, "patterns": len(patterns)}


def promote_to_global(text: str, justification: str, corroborating_review_ids: list[str]) -> dict:
    """Promote an insight to the GLOBAL scope (loaded into every review). Gated: requires
    >= 2 corroborating review ids, else rejects and writes nothing. On success, stamps the
    insight into global's patterns with the justification attached.

    Args:
        text: the insight (e.g. 'agent rationalizes momentum in low-VIX regimes').
        justification: why this generalizes to ALL reviews.
        corroborating_review_ids: ids of reviews that evidence this (>= 2 required).

    Returns:
        {"status": "promoted", "text": str} or {"status": "rejected", "reason": str}.
    """
    if len(corroborating_review_ids) < 2:
        return {"status": "rejected",
                "reason": "global promotion requires >= 2 corroborating review ids"}
    current = _read_rm("global")
    value = current["value"] if (current and isinstance(current.get("value"), dict)) else {}
    patterns = value.get("patterns", [])
    stamp_insight(patterns, text, corroborating_review_ids, date.today().isoformat())
    for p in patterns:
        if p["text"] == text:
            p["justification"] = justification
            break
    value["patterns"] = patterns
    _write_rm("global", value)
    return {"status": "promoted", "text": text}


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
    out, skipped = [], []
    for run in roots:
        if not is_finished(run):
            # still running (end_time None) — its trace is partial; never audit it as 'done'.
            skipped.append(run["run_id"])
            continue
        phase = identify_phase(run, weekend=_is_weekend(run["start_time"]))
        out.append({"run_id": run["run_id"], "start_time": run["start_time"],
                    "facts": analyze_tool_fidelity(run, phase)})
    return {"runs": out, "skipped_in_progress": skipped}


def mark_run_reviewed(run_id: str, start_time: str, config: RunnableConfig = None) -> dict:
    """Advance the tool-fidelity watermark past a run. Call ONLY after its verdict is
    written (advance-on-success), so a failed review re-audits the run next time."""
    rt = _get_active(_thread_id(config))
    if rt is None:
        raise ValueError("No active review — call begin_review first.")
    cursor = advance_cursor(_read_watermark(rt), run_id, start_time)
    _write_watermark(rt, cursor)
    return {"status": "marked", "run_id": run_id}


REVIEW_TOOLS = [
    # evidence (read-only)
    query_database,
    read_agent_memory,
    read_all_agent_memory,
    get_performance_comparison,
    read_run_trace,
    # the reviewer's own stores
    begin_review,
    write_review,
    read_reviewer_memory,
    write_reviewer_memory,
    record_insight,
    promote_to_global,
    # tool-fidelity audit + watermark
    get_tool_fidelity_runs,
    mark_run_reviewed,
]
