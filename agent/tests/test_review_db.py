from unittest.mock import MagicMock, call, patch


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
    sb.table.assert_called_with("agent_reviews")
    sb.table.return_value.select.return_value.eq.assert_called_with("review_type", "conformance")
    sb.table.return_value.select.return_value.eq.return_value.order.assert_called_with("created_at", desc=True)
    sb.table.return_value.select.return_value.eq.return_value.order.return_value.limit.assert_called_with(5)
    assert out == [{"verdict": "x"}]


@patch("review_agent.db.get_supabase")
def test_reviewer_memory_roundtrip(mock_get):
    sb = MagicMock()
    sb.table.return_value.upsert.return_value.execute.return_value.data = [{"namespace": "global"}]
    sb.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = {"value": {"k": 1}}
    mock_get.return_value = sb
    from review_agent.db import write_reviewer_memory, read_reviewer_memory

    write_reviewer_memory("global", {"k": 1})
    sb.table.assert_any_call("reviewer_memory")
    payload = sb.table.return_value.upsert.call_args[0][0]
    assert payload["namespace"] == "global"
    assert payload["value"] == {"k": 1}
    assert sb.table.return_value.upsert.call_args[1]["on_conflict"] == "namespace"
    assert read_reviewer_memory("global") == {"value": {"k": 1}}


@patch("review_agent.db.read_reviewer_memory")
@patch("review_agent.db.get_supabase")
def test_write_reviewer_memory_archives_prior_value(mock_get, mock_read):
    """When a namespace already has a value, write_reviewer_memory must push the
    prior value into the ':__history' namespace before writing the new one."""
    ns = "conformance:detail"
    prior_value = {"patterns": ["old"], "n": 0}
    new_value = {"patterns": ["new"], "n": 1}

    # First read_reviewer_memory call (current ns) → existing row
    # Second call (history ns) → no history yet
    mock_read.side_effect = [
        {"namespace": ns, "value": prior_value},  # current value exists
        None,                                       # no prior history
    ]

    sb = MagicMock()
    sb.table.return_value.upsert.return_value.execute.return_value.data = [{"namespace": ns}]
    mock_get.return_value = sb

    from review_agent.db import write_reviewer_memory

    write_reviewer_memory(ns, new_value)

    # Collect all upsert payloads (namespace arg of first positional arg)
    upsert_calls = sb.table.return_value.upsert.call_args_list
    namespaces_written = [c[0][0]["namespace"] for c in upsert_calls]

    # Must have written to the history namespace AND the main namespace
    assert f"{ns}:__history" in namespaces_written, "history namespace not written"
    assert ns in namespaces_written, "main namespace not written"

    # The history write must contain the prior value as the first (only) entry
    hist_call = next(c for c in upsert_calls if c[0][0]["namespace"] == f"{ns}:__history")
    assert hist_call[0][0]["value"] == [prior_value]

    # The main write must contain the new value
    main_call = next(c for c in upsert_calls if c[0][0]["namespace"] == ns)
    assert main_call[0][0]["value"] == new_value
