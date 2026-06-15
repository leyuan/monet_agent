import pytest
from review_agent.context import active_review_type


def test_write_detail_resolves_to_active_namespace(monkeypatch):
    active_review_type.set(None)
    captured = {}
    monkeypatch.setattr("review_agent.tools._write_rm",
                        lambda ns, val: captured.update(ns=ns) or {"namespace": ns})
    monkeypatch.setattr("review_agent.tools.load_review_context", lambda rt: "ctx")
    from review_agent.tools import begin_review, write_reviewer_memory
    begin_review("conformance", "run-x", "asked for conformance")
    write_reviewer_memory("detail", {"a": 1})
    assert captured["ns"] == "conformance:detail"


def test_write_without_active_review_raises():
    active_review_type.set(None)
    from review_agent.tools import write_reviewer_memory
    with pytest.raises(ValueError):
        write_reviewer_memory("detail", {"a": 1})


def test_global_scope_resolves_to_global(monkeypatch):
    active_review_type.set(None)
    captured = {}
    monkeypatch.setattr("review_agent.tools._write_rm",
                        lambda ns, val: captured.update(ns=ns) or {"namespace": ns})
    monkeypatch.setattr("review_agent.tools.load_review_context", lambda rt: "ctx")
    from review_agent.tools import begin_review, write_reviewer_memory
    begin_review("conformance", "s", "r")
    write_reviewer_memory("global", {"x": 1})
    assert captured["ns"] == "global"
