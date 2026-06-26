# tests/test_strategy_conformance_tools.py
import review_agent.tools as T

FAKE_CONFIG = {"configurable": {"thread_id": "t1"}}

_TRACE = {"runs": [
    {"run_id": "r1", "name": "autonomous_loop",
     "start_time": "2026-06-19T14:00:00+00:00", "end_time": "2026-06-19T14:05:00+00:00",
     "error": None, "tool_calls": []},
]}

_TRADES = [
    {"symbol": "AAPL", "side": "buy", "order_class": "simple", "quantity": 10,
     "filled_quantity": 10, "filled_avg_price": 190.0, "stop_loss_price": 180.0,
     "status": "filled", "created_at": "2026-06-19T14:01:00+00:00", "thesis": "x"},
    {"symbol": "AAPL", "side": "sell", "order_class": "simple", "quantity": 10,
     "filled_quantity": 10, "filled_avg_price": 192.0, "stop_loss_price": None,
     "status": "filled", "created_at": "2026-06-19T14:02:00+00:00", "thesis": "early exit"},
]


def _setup(monkeypatch, trace=_TRACE, trades=_TRADES, memory=None):
    monkeypatch.setattr(T, "_get_active", lambda tid: "conformance")
    monkeypatch.setattr(T, "read_run_trace", lambda **k: trace)
    monkeypatch.setattr(T, "_read_watermark", lambda rt: None)         # cold start
    monkeypatch.setattr(T, "query_database", lambda sql: {"rows": trades})
    mem = memory or {}
    monkeypatch.setattr(T, "read_agent_memory", lambda key: mem.get(key, {"key": key, "value": None}))


def test_join_flags_anti_churn_and_missing_stop(monkeypatch):
    _setup(monkeypatch)
    out = T.get_strategy_conformance_runs(config=FAKE_CONFIG)
    run = out["runs"][0]
    by = {r["rule"]: r for r in run["rules"]}
    assert by["anti_churn"]["status"] == "violated"        # sold same minute it bought
    assert run["run_severity"] == "fail"
    assert "risk_limit_leak" in by and by["risk_limit_leak"]["status"] == "unverifiable"


def test_skips_in_progress(monkeypatch):
    trace = {"runs": [{"run_id": "rp", "name": "autonomous_loop",
                       "start_time": "2026-06-19T14:00:00+00:00", "end_time": None,
                       "error": None, "tool_calls": []}]}
    _setup(monkeypatch, trace=trace)
    out = T.get_strategy_conformance_runs(config=FAKE_CONFIG)
    assert out["runs"] == [] and "rp" in out["skipped_in_progress"]


def test_query_error_yields_empty_history_not_crash(monkeypatch):
    _setup(monkeypatch)
    monkeypatch.setattr(T, "query_database", lambda sql: {"error": "boom"})
    out = T.get_strategy_conformance_runs(config=FAKE_CONFIG)
    run = out["runs"][0]
    by = {r["rule"]: r for r in run["rules"]}
    assert by["anti_churn"]["status"] == "conformant"      # no trades → nothing violated
    assert run["run_severity"] in ("pass", "info")          # never a false fail off a dead probe


def test_requires_active_review(monkeypatch):
    monkeypatch.setattr(T, "_get_active", lambda tid: None)
    import pytest
    with pytest.raises(ValueError):
        T.get_strategy_conformance_runs(config=FAKE_CONFIG)


def test_counts_positions_opened_before_30d_window(monkeypatch):
    # 8 positions opened ~40 days before the run (still held) + 1 new in-run buy => 9 > cap(8).
    # Proves position_count reconstructs from FULL history, not a 30-day window.
    old = [
        {"symbol": f"S{i}", "side": "buy", "order_class": "simple", "quantity": 1,
         "filled_quantity": 1, "filled_avg_price": 10.0, "stop_loss_price": 9.0,
         "status": "filled", "created_at": "2026-05-10T14:00:00+00:00", "thesis": "old"}
        for i in range(8)
    ]
    new_buy = {"symbol": "S8", "side": "buy", "order_class": "simple", "quantity": 1,
               "filled_quantity": 1, "filled_avg_price": 10.0, "stop_loss_price": 9.0,
               "status": "filled", "created_at": "2026-06-19T14:01:00+00:00", "thesis": "new"}
    _setup(monkeypatch, trades=old + [new_buy])
    out = T.get_strategy_conformance_runs(config=FAKE_CONFIG)
    by = {r["rule"]: r for r in out["runs"][0]["rules"]}
    assert by["position_count"]["status"] == "violated"          # 9 > cap 8, counting pre-window holds
    assert by["position_count"]["evidence"]["overages"]


def test_explicit_mode_audits_single_run(monkeypatch):
    captured = {}
    def fake_trace(**k):
        captured.update(k)
        return _TRACE
    monkeypatch.setattr(T, "_get_active", lambda tid: "conformance")
    monkeypatch.setattr(T, "read_run_trace", fake_trace)
    monkeypatch.setattr(T, "query_database", lambda sql: {"rows": []})
    monkeypatch.setattr(T, "read_agent_memory", lambda key: {"key": key, "value": None})
    out = T.get_strategy_conformance_runs(subject="r1", config=FAKE_CONFIG)
    assert captured.get("run_id") == "r1"                        # explicit mode → trace by run_id
    assert out["runs"][0]["run_id"] == "r1"
