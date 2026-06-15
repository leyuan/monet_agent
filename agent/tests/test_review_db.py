from unittest.mock import MagicMock, patch


@patch("review_agent.db.get_supabase")
def test_write_review_inserts_row(mock_get):
    sb = MagicMock()
    sb.table.return_value.insert.return_value.execute.return_value.data = [{"id": "abc"}]
    mock_get.return_value = sb
    from review_agent.db import write_review

    row = write_review("conformance", "run-2026-06-07", "Obeyed all hard rules.", "pass", 0.9)
    sb.table.assert_called_with("agent_reviews")
    args = sb.table.return_value.insert.call_args[0][0]
    assert args["review_type"] == "conformance"
    assert args["severity"] == "pass"
    assert row == {"id": "abc"}


@patch("review_agent.db.get_supabase")
def test_list_recent_reviews_filters_by_type(mock_get):
    sb = MagicMock()
    chain = sb.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value
    chain.execute.return_value.data = [{"verdict": "x"}]
    mock_get.return_value = sb
    from review_agent.db import list_recent_reviews

    out = list_recent_reviews("conformance", limit=5)
    sb.table.return_value.select.return_value.eq.assert_called_with("review_type", "conformance")
    assert out == [{"verdict": "x"}]


@patch("review_agent.db.get_supabase")
def test_reviewer_memory_roundtrip(mock_get):
    sb = MagicMock()
    sb.table.return_value.upsert.return_value.execute.return_value.data = [{"namespace": "global"}]
    sb.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = {"value": {"k": 1}}
    mock_get.return_value = sb
    from review_agent.db import write_reviewer_memory, read_reviewer_memory

    write_reviewer_memory("global", {"k": 1})
    sb.table.return_value.upsert.assert_called()
    assert read_reviewer_memory("global") == {"value": {"k": 1}}
