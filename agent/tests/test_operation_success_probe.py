from review_agent.operation_success import build_probe_sql


def _op(tool, bucket="db", output=None, inputs=None):
    return {"tool": tool, "bucket": bucket, "output": output or {}, "inputs": inputs or {}, "error": None}


def test_probe_by_output_id():
    sql = build_probe_sql(_op("place_order", output={"trade_id": "abc-123"}))
    assert sql == "SELECT * FROM trades WHERE id = 'abc-123' LIMIT 5"


def test_probe_none_for_traceonly_manage_watchlist():
    assert build_probe_sql(_op("manage_watchlist", bucket="trace_only", inputs={"symbol": "AAPL"})) is None


def test_probe_none_for_unknown_tool():
    assert build_probe_sql(_op("get_quote", bucket="unclassified")) is None


def test_probe_by_const_key():
    sql = build_probe_sql(_op("audit_factor_ic"))
    assert sql == "SELECT * FROM agent_memory WHERE key = 'strategy_health' LIMIT 5"


def test_probe_none_for_trace_only_and_missing_and_unsafe():
    assert build_probe_sql(_op("send_daily_recap", bucket="trace_only")) is None
    assert build_probe_sql(_op("place_order", output={})) is None            # no trade_id
    assert build_probe_sql(_op("write_agent_memory", output={"key": "a'b"})) is None  # unsafe
