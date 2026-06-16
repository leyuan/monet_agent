"""The reviewer's tool surface — READ-ONLY evidence + its OWN write tools.

Capability boundary: this list contains NO trading tools and NO tools that
mutate the trader's data. Enforced by tests/test_review_tools_boundary.py.
"""
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
)
from review_agent.trace import read_run_trace
from review_agent.review_memory import load_review_context


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
    """Start a review. Binds the active review type for this thread (so every
    write_reviewer_memory call is namespaced to it — a raw namespace cannot be
    supplied) and returns the bounded prior-context for this review type.

    Args:
        review_type: e.g. 'conformance'. Becomes the active namespace for writes.
        subject: what is being reviewed (run id / date / description).
        reason: why this review type was chosen.

    Returns:
        {"review_type": str, "subject": str, "context": str}

    Note: `config` is injected by the runtime — not supplied by the LLM.
    """
    _set_active(_thread_id(config), review_type)
    return {"review_type": review_type, "subject": subject,
            "context": load_review_context(review_type)}


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
]
