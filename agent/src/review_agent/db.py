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
