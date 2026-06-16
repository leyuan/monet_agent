from unittest.mock import patch

CFG = {"configurable": {"thread_id": "t1"}}


@patch("review_agent.tools._write_rm")
@patch("review_agent.tools._read_rm")
@patch("review_agent.tools._get_active")
def test_record_insight_merges_into_active_detail(mock_active, mock_read, mock_write):
    mock_active.return_value = "conformance"
    mock_read.return_value = {"value": {"patterns": []}}
    from review_agent.tools import record_insight
    out = record_insight("anti-churn respected", ["r1"], config=CFG)
    assert out["namespace"] == "conformance:detail"
    ns, value = mock_write.call_args[0][0], mock_write.call_args[0][1]
    assert ns == "conformance:detail"
    entry = value["patterns"][0]
    assert entry["text"] == "anti-churn respected"
    assert entry["source_review_ids"] == ["r1"]
    assert entry["confidence"] == "low"   # count=1 → low (derived, not supplied)


@patch("review_agent.tools._get_active", return_value=None)
def test_record_insight_without_active_review_raises(mock_active):
    import pytest
    from review_agent.tools import record_insight
    with pytest.raises(ValueError):
        record_insight("x", ["r1"], config=CFG)
