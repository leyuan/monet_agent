from types import SimpleNamespace
from unittest.mock import MagicMock, patch


@patch("review_agent.trace.Client")
def test_read_run_trace_extracts_tool_calls(mock_client_cls):
    client = MagicMock()
    root = SimpleNamespace(id="root-1", name="autonomous_loop", trace_id="t1",
                           start_time="2026-06-07", error=None, run_type="chain")
    tool = SimpleNamespace(name="query_database", inputs={"q": "x"}, outputs={"rows": 1},
                           error=None, run_type="tool")
    llm = SimpleNamespace(name="model", inputs={}, outputs={}, error=None, run_type="llm")
    client.list_runs.side_effect = [[root], [root, tool, llm]]  # roots, then children
    mock_client_cls.return_value = client
    from review_agent.trace import read_run_trace

    out = read_run_trace(limit=1)
    assert out["runs"][0]["name"] == "autonomous_loop"
    assert out["runs"][0]["tool_calls"] == [
        {"name": "query_database", "inputs": {"q": "x"}, "outputs": {"rows": 1}, "error": None}
    ]
