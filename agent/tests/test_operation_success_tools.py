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


def test_query_error_is_unverifiable_not_silent_failure(monkeypatch):
    """If query_database returns an error (e.g. bad column), the op is unverifiable — the
    run must NOT be reported as a silent failure off a broken probe."""
    monkeypatch.setattr(T, "_get_active", lambda tid: "operation_success")
    monkeypatch.setattr(T, "read_run_trace", lambda **k: _TRACE)
    monkeypatch.setattr(T, "_read_watermark", lambda rt: None)
    monkeypatch.setattr(T, "query_database", lambda sql: {"error": 'column "id" does not exist'})
    out = T.get_operation_success_runs(config=FAKE_CONFIG)
    statuses = {o["tool"]: o["status"] for o in out["runs"][0]["operations"]}
    assert statuses["write_journal_entry"] == "unverifiable"
    assert statuses["record_daily_snapshot"] == "unverifiable"
    assert out["runs"][0]["run_severity"] in ("info", "pass")   # never fail off a broken probe


def test_requires_active_review(monkeypatch):
    monkeypatch.setattr(T, "_get_active", lambda tid: None)
    import pytest
    with pytest.raises(ValueError):
        T.get_operation_success_runs(config=FAKE_CONFIG)


def test_registered_and_boundary_intact():
    names = {getattr(t, "__name__", getattr(t, "name", "")) for t in T.REVIEW_TOOLS}
    assert "get_operation_success_runs" in names
    assert "place_order" not in names


import os
import pytest

from review_agent.operation_success import OPERATION_SPECS, build_probe_sql


@pytest.mark.integration
@pytest.mark.skipif(os.environ.get("RUN_DB_INTEGRATION") != "1", reason="needs local Supabase")
def test_every_db_probe_runs_without_column_error():
    """Each db-backed op's probe SQL executes against the real schema with no
    'column does not exist' error (returns rows or an empty set, never a SQL error)."""
    from stock_agent.tools.memory import query_database
    samples = {"output": {"trade_id": "00000000-0000-0000-0000-000000000000",
                          "journal_id": "00000000-0000-0000-0000-000000000000",
                          "key": "market_regime", "date": "2026-01-01"},
               "input": {"symbol": "AAPL"}}
    for tool, spec in OPERATION_SPECS.items():
        if spec["kind"] != "db":
            continue
        op = {"tool": tool, "bucket": "db", "error": None, **samples}
        sql = build_probe_sql(op)
        assert sql, f"{tool}: expected a probe SQL from sample identifiers"
        res = query_database(sql)
        assert "error" not in res, f"{tool} probe failed: {res.get('error')}"
