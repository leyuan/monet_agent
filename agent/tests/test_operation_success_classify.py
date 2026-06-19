from review_agent.operation_success import classify_operation, run_severity

RUN_START = "2026-06-19T14:00:00+00:00"


def _op(tool, output=None, inputs=None, error=None):
    bucket = "trace_only" if tool.startswith("send_") or tool in (
        "attach_bracket_to_position", "reconcile_positions") else "db"
    return {"tool": tool, "bucket": bucket, "output": output or {}, "inputs": inputs or {}, "error": error}


def test_order_filled_lands():
    op = _op("place_order", output={"trade_id": "t1", "status": "filled"})
    r = classify_operation(op, [{"id": "t1", "status": "filled", "filled_avg_price": 10.0}], RUN_START)
    assert r["status"] == "landed" and r["severity"] == "pass"


def test_order_risk_rejected_is_expected_success():
    op = _op("place_order", output={"error": "Risk check failed: exposure"})
    r = classify_operation(op, [], RUN_START)
    assert r["status"] == "rejected_expected" and r["severity"] == "pass"


def test_order_silent_failure_is_critical_fail():
    op = _op("place_order", output={"trade_id": "t1", "status": "filled"})
    r = classify_operation(op, [], RUN_START)            # output claims a trade, but no row
    assert r["status"] == "silent_failure" and r["severity"] == "fail"


def test_memory_fresh_lands_stale_is_silent_failure():
    op = _op("write_agent_memory", output={"key": "k1", "updated_at": "2026-06-19T14:01:00+00:00"})
    fresh = classify_operation(op, [{"key": "k1", "updated_at": "2026-06-19T14:01:00+00:00"}], RUN_START)
    assert fresh["status"] == "landed"
    stale = classify_operation(op, [{"key": "k1", "updated_at": "2026-06-18T09:00:00+00:00"}], RUN_START)
    assert stale["status"] == "silent_failure" and stale["severity"] == "warn"


def test_snapshot_degraded_on_bad_content():
    op = _op("record_daily_snapshot", output={"date": "2026-06-19"})
    r = classify_operation(op, [{"snapshot_date": "2026-06-19", "spy_close": 0, "portfolio_equity": 100}], RUN_START)
    assert r["status"] == "degraded" and r["severity"] == "warn"


def test_trace_only_clean_lands_errored_warns():
    clean = classify_operation(_op("send_daily_recap", output={"status": "queued"}), [], RUN_START)
    assert clean["status"] == "landed" and clean["severity"] in ("pass", "info")
    errored = classify_operation(_op("send_daily_recap", output={}, error="SMTP 500"), [], RUN_START)
    assert errored["status"] == "errored_unrecovered" and errored["severity"] == "warn"


def test_unverifiable_when_no_probe_key():
    op = _op("write_agent_memory", output={})            # no key → can't probe
    r = classify_operation(op, [], RUN_START)
    assert r["status"] == "unverifiable" and r["severity"] == "info"


def test_probe_error_is_unverifiable_not_silent_failure():
    """A failed DB probe (bad column / DB down) must NEVER read as silent_failure."""
    op = _op("record_daily_snapshot", output={"date": "2026-06-19"})  # critical op
    r = classify_operation(op, [], RUN_START, probe_error=True)
    assert r["status"] == "unverifiable" and r["severity"] == "info"


def test_manage_watchlist_remove_lands_via_trace_only():
    op = {"tool": "manage_watchlist", "bucket": "trace_only",
          "output": {"action": "removed", "symbol": "AAPL", "success": True}, "inputs": {}, "error": None}
    r = classify_operation(op, [], RUN_START)
    assert r["status"] == "landed" and r["severity"] == "pass"


def test_run_severity_is_worst():
    assert run_severity([{"severity": "pass"}, {"severity": "warn"}, {"severity": "fail"}]) == "fail"
    assert run_severity([{"severity": "pass"}, {"severity": "info"}]) == "info"
    assert run_severity([]) == "pass"
