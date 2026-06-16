from unittest.mock import patch


@patch("review_agent.tools._write_rm")
@patch("review_agent.tools._read_rm")
def test_rejects_with_fewer_than_two_corroborating(mock_read, mock_write):
    from review_agent.tools import promote_to_global
    out = promote_to_global("agent rationalizes momentum", "applies everywhere", ["r1"])
    assert out["status"] == "rejected"
    mock_write.assert_not_called()   # nothing written


@patch("review_agent.tools._write_rm")
@patch("review_agent.tools._read_rm")
def test_promotes_with_two_corroborating(mock_read, mock_write):
    mock_read.return_value = {"value": {"patterns": []}}
    from review_agent.tools import promote_to_global
    out = promote_to_global("agent rationalizes momentum", "applies everywhere", ["r1", "r2"])
    assert out["status"] == "promoted"
    mock_write.assert_called_once()
    ns, value = mock_write.call_args[0][0], mock_write.call_args[0][1]
    assert ns == "global"
    entry = next(p for p in value["patterns"] if p["text"] == "agent rationalizes momentum")
    assert entry["source_review_ids"] == ["r1", "r2"]
    assert entry["justification"] == "applies everywhere"
