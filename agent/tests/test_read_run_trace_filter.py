from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from review_agent.trace import select_roots_by_name


class _Root:
    def __init__(self, name, rid):
        self.name = name; self.id = rid


@patch("review_agent.trace.Client")
def test_tool_calls_returned_in_chronological_order(mock_client_cls):
    """LangSmith returns children newest-first; read_run_trace must sort tool_calls
    by start_time so order-dependent checks (terminal, dependency-order, recovery) work."""
    client = MagicMock()
    root = SimpleNamespace(id="root-1", name="autonomous_loop", trace_id="t1",
                           start_time="2026-06-17T10:00:00", end_time="2026-06-17T10:05:00",
                           error=None, status="success", run_type="chain", inputs={}, outputs={})
    # children NEWEST-FIRST (the real LangSmith order): journal (late) before score (early)
    late = SimpleNamespace(name="write_journal_entry", inputs={}, outputs={}, error=None,
                           run_type="tool", start_time="2026-06-17T10:04:00",
                           end_time="2026-06-17T10:04:30")
    early = SimpleNamespace(name="score_universe", inputs={}, outputs={}, error=None,
                            run_type="tool", start_time="2026-06-17T10:01:00",
                            end_time="2026-06-17T10:01:30")
    client.read_run.return_value = root
    client.list_runs.return_value = [late, early]  # children returned newest-first
    mock_client_cls.return_value = client
    from review_agent.trace import read_run_trace

    out = read_run_trace(run_id="root-1")
    names = [c["name"] for c in out["runs"][0]["tool_calls"]]
    assert names == ["score_universe", "write_journal_entry"]  # chronological, not reversed


def test_filters_to_trader_graph_excludes_reviewer():
    roots = [_Root("review_agent", "x"), _Root("autonomous_loop", "a"),
             _Root("monet_agent", "m"), _Root("autonomous_loop", "b")]
    out = select_roots_by_name(roots, "autonomous_loop", limit=5)
    assert [r.id for r in out] == ["a", "b"]


def test_limit_applied_after_filter():
    roots = [_Root("autonomous_loop", "a"), _Root("review_agent", "x"),
             _Root("autonomous_loop", "b"), _Root("autonomous_loop", "c")]
    out = select_roots_by_name(roots, "autonomous_loop", limit=2)
    assert [r.id for r in out] == ["a", "b"]
