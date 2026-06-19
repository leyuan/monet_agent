from review_agent.operation_success import extract_operations


def _call(name, outputs=None, inputs=None, error=None):
    return {"name": name, "inputs": inputs or {}, "outputs": outputs or {}, "error": error}


def test_reads_are_dropped_operations_kept():
    run = {"tool_calls": [
        _call("score_universe"),                                  # read → dropped
        _call("get_quote"),                                       # unknown read-ish? not in any set → unclassified
        _call("write_journal_entry", outputs={"journal_id": "j1"}),
        _call("send_daily_recap", outputs={"status": "queued"}),
    ]}
    ops = extract_operations(run)
    by_tool = {o["tool"]: o for o in ops}
    assert "score_universe" not in by_tool                        # known read dropped
    assert by_tool["write_journal_entry"]["bucket"] == "db"
    assert by_tool["send_daily_recap"]["bucket"] == "trace_only"
    assert by_tool["get_quote"]["bucket"] == "unclassified"       # unknown surfaced


def test_output_is_unwrapped_from_langsmith_wrapper():
    run = {"tool_calls": [_call("write_agent_memory",
                                outputs={"output": {"key": "k1", "updated_at": "t"}})]}
    op = extract_operations(run)[0]
    assert op["output"] == {"key": "k1", "updated_at": "t"}       # {"output": ...} unwrapped
