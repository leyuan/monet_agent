"""Tests for scope-based reviewer-memory namespace binding via thread-scoped Supabase.

The binding mechanism (Option A): begin_review persists _active:{thread_id} to
Supabase; write_reviewer_memory reads it. Both receive thread_id via the injected
RunnableConfig. These tests use a fake config dict and mock the db helpers.
"""
import pytest


FAKE_CONFIG = {"configurable": {"thread_id": "t1"}}


def test_write_detail_resolves_to_active_namespace(monkeypatch):
    """detail scope → '{active_review_type}:detail'."""
    monkeypatch.setattr("review_agent.tools._set_active", lambda tid, rt: None)
    monkeypatch.setattr("review_agent.tools._get_active", lambda tid: "conformance")
    monkeypatch.setattr("review_agent.tools.load_review_context", lambda rt: "ctx")
    captured = {}
    monkeypatch.setattr("review_agent.tools._write_rm",
                        lambda ns, val: captured.update(ns=ns) or {"namespace": ns})

    monkeypatch.setattr("review_agent.tools._append_routing_log", lambda *a, **k: None)
    from review_agent.tools import begin_review, write_reviewer_memory
    begin_review("conformance", "run-x", "asked for conformance", config=FAKE_CONFIG)
    write_reviewer_memory("detail", {"a": 1}, config=FAKE_CONFIG)
    assert captured["ns"] == "conformance:detail"


def test_write_without_active_review_raises(monkeypatch):
    """No active review → ValueError."""
    monkeypatch.setattr("review_agent.tools._get_active", lambda tid: None)

    from review_agent.tools import write_reviewer_memory
    with pytest.raises(ValueError, match="No active review"):
        write_reviewer_memory("detail", {"a": 1}, config=FAKE_CONFIG)


def test_global_scope_resolves_to_global(monkeypatch):
    """global scope → 'global' (shared, not namespaced to review type)."""
    monkeypatch.setattr("review_agent.tools._set_active", lambda tid, rt: None)
    monkeypatch.setattr("review_agent.tools._get_active", lambda tid: "conformance")
    monkeypatch.setattr("review_agent.tools.load_review_context", lambda rt: "ctx")
    captured = {}
    monkeypatch.setattr("review_agent.tools._write_rm",
                        lambda ns, val: captured.update(ns=ns) or {"namespace": ns})

    monkeypatch.setattr("review_agent.tools._append_routing_log", lambda *a, **k: None)
    from review_agent.tools import begin_review, write_reviewer_memory
    begin_review("conformance", "s", "r", config=FAKE_CONFIG)
    write_reviewer_memory("global", {"x": 1}, config=FAKE_CONFIG)
    assert captured["ns"] == "global"


def test_missing_thread_id_raises():
    """No thread_id in config → ValueError (cannot bind the review)."""
    from review_agent.tools import begin_review
    with pytest.raises(ValueError, match="No thread_id"):
        begin_review("conformance", "s", "r", config={"configurable": {}})


def test_missing_thread_id_on_write_raises():
    """No thread_id in config → ValueError on write_reviewer_memory too."""
    from review_agent.tools import write_reviewer_memory
    with pytest.raises(ValueError, match="No thread_id"):
        write_reviewer_memory("detail", {"a": 1}, config={})
