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


_HISTORY_CAP = 5


def write_reviewer_memory(namespace: str, value: dict) -> dict:
    """Upsert a reviewer_memory entry, preserving the prior value in a capped
    history namespace ('{namespace}:__history') so a write can be reverted."""
    sb = get_supabase()
    current = read_reviewer_memory(namespace)
    if current and current.get("value") is not None:
        hist_ns = f"{namespace}:__history"
        hist = read_reviewer_memory(hist_ns)
        versions = hist["value"] if hist and isinstance(hist.get("value"), list) else []
        versions = [current["value"], *versions][:_HISTORY_CAP]
        sb.table("reviewer_memory").upsert(
            {"namespace": hist_ns, "value": versions, "updated_at": "now()"},
            on_conflict="namespace",
        ).execute()
    result = sb.table("reviewer_memory").upsert(
        {"namespace": namespace, "value": value, "updated_at": "now()"},
        on_conflict="namespace",
    ).execute()
    return result.data[0]


def revert_reviewer_memory(namespace: str) -> dict | None:
    """Restore the most recent prior value from history. Returns the restored row, or None
    if there is no history. (Recovery operation — not exposed as an LLM tool in v1.)"""
    sb = get_supabase()
    hist_ns = f"{namespace}:__history"
    hist = read_reviewer_memory(hist_ns)
    versions = hist["value"] if hist and isinstance(hist.get("value"), list) else []
    if not versions:
        return None
    restored, rest = versions[0], versions[1:]
    sb.table("reviewer_memory").upsert(
        {"namespace": hist_ns, "value": rest, "updated_at": "now()"}, on_conflict="namespace"
    ).execute()
    result = sb.table("reviewer_memory").upsert(
        {"namespace": namespace, "value": restored, "updated_at": "now()"}, on_conflict="namespace"
    ).execute()
    return result.data[0]


def set_active_review(thread_id: str, review_type: str) -> dict:
    """Persist the active review type for a thread (thread-scoped binding)."""
    return write_reviewer_memory(f"_active:{thread_id}", {"review_type": review_type})


def get_active_review(thread_id: str) -> str | None:
    """Read the active review type for a thread, or None."""
    mem = read_reviewer_memory(f"_active:{thread_id}")
    if mem and mem.get("value"):
        return mem["value"].get("review_type")
    return None
