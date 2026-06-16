"""Gated integration tests for the reviewer agent's Supabase round-trips.

These tests require:
  - RUN_DB_INTEGRATION=1 environment variable
  - SUPABASE_URL pointing at a LOCAL Supabase instance (127.0.0.1 or localhost)

Without those conditions the tests are SKIPPED (not failed) — the offline unit
suite remains green in CI and sandbox environments.
"""
import uuid

import pytest

from review_agent import db as rdb
from review_agent import tools as rtools

pytestmark = pytest.mark.integration


def _cfg(thread_id):
    return {"configurable": {"thread_id": thread_id}}


def test_write_review_and_list_roundtrip(local_supabase):
    """write_review persists a row; list_recent_reviews retrieves it."""
    subject = f"itest-{uuid.uuid4()}"
    # rdb.write_review: (review_type, subject, verdict, severity, confidence, evidence_refs)
    row = rdb.write_review(
        "conformance",
        subject,
        "all rules obeyed",
        "pass",
        0.9,
        evidence_refs={"run": subject},
    )
    try:
        recent = rdb.list_recent_reviews("conformance", limit=20)
        match = [r for r in recent if r["subject"] == subject]
        assert len(match) == 1
        assert match[0]["severity"] == "pass"
        assert float(match[0]["confidence"]) == 0.9
    finally:
        local_supabase.table("agent_reviews").delete().eq("id", row["id"]).execute()


def test_reviewer_memory_roundtrip(local_supabase):
    """write_reviewer_memory upserts; read_reviewer_memory retrieves the same value."""
    ns = f"itest:{uuid.uuid4()}"
    try:
        rdb.write_reviewer_memory(ns, {"patterns": ["x"], "n": 1})
        got = rdb.read_reviewer_memory(ns)
        assert got["value"] == {"patterns": ["x"], "n": 1}
    finally:
        local_supabase.table("reviewer_memory").delete().eq("namespace", ns).execute()


def test_cross_turn_active_review_binding(local_supabase):
    """THE Option A validation: begin_review (turn 1) persists the active review;
    write_reviewer_memory (turn 2, SEPARATE call) reads it back via thread_id and
    writes to the bound namespace. Proves the binding survives across tool-call
    turns against a real DB (no in-process state)."""
    thread_id = f"itest-thread-{uuid.uuid4()}"
    cfg = _cfg(thread_id)
    detail_ns = "conformance:detail"
    try:
        # Turn 1: begin_review binds the active review type for this thread.
        rtools.begin_review("conformance", "run-itest", "asked for conformance", config=cfg)
        assert rdb.get_active_review(thread_id) == "conformance"

        # Turn 2 (separate call): write detail — namespace derived from thread's active review.
        marker = uuid.uuid4().hex
        out = rtools.write_reviewer_memory("detail", {"k": marker}, config=cfg)
        assert out["namespace"] == detail_ns

        # And THIS run's value actually persisted under the bound namespace. Round-trip the
        # unique marker (not just `is not None`) so a stale leftover from a prior failed run
        # cannot produce a false pass.
        got = rdb.read_reviewer_memory(detail_ns)
        assert got is not None and got["value"]["k"] == marker

        # A thread with no begin_review has no active review -> write raises.
        with pytest.raises(ValueError):
            rtools.write_reviewer_memory("detail", {"k": 1}, config=_cfg(f"other-{uuid.uuid4()}"))
    finally:
        local_supabase.table("reviewer_memory").delete().eq("namespace", f"_active:{thread_id}").execute()
        local_supabase.table("reviewer_memory").delete().eq("namespace", detail_ns).execute()
