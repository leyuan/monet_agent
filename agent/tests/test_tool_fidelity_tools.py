import review_agent.tools as T

FAKE_CONFIG = {"configurable": {"thread_id": "t1"}}

_TRACE = {"runs": [
    {"run_id": "r1", "name": "autonomous_loop", "start_time": "2026-06-17T14:00:00",
     "end_time": "2026-06-17T14:05:00", "error": None, "total_tokens": 100,
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


def test_get_runs_skips_in_progress(monkeypatch):
    """A still-running run (end_time=None) must NOT be audited — it's reported as skipped."""
    monkeypatch.setattr(T, "_get_active", lambda tid: "tool_fidelity")
    in_progress = {"runs": [
        {"run_id": "rp", "name": "autonomous_loop", "start_time": "2026-06-17T14:00:00",
         "end_time": None, "error": None, "total_tokens": 1,
         "tool_calls": [{"name": "score_universe", "error": None}]}]}
    monkeypatch.setattr(T, "read_run_trace", lambda **k: in_progress)
    monkeypatch.setattr(T, "_read_watermark", lambda rt: None)
    out = T.get_tool_fidelity_runs(config=FAKE_CONFIG)
    assert out["runs"] == []
    assert "rp" in out["skipped_in_progress"]


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
