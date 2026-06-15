from unittest.mock import patch


@patch("review_agent.review_memory.list_recent_reviews")
@patch("review_agent.review_memory.read_reviewer_memory")
def test_load_context_includes_only_current_task_detail(mock_read, mock_recent):
    def fake_read(ns):
        return {
            "index": {"value": {"conformance": "clean 5 runs", "efficacy": "flagged 3x"}},
            "conformance:detail": {"value": {"patterns": ["anti-churn respected"]}},
            "global": {"value": {"bias": "over-bullish in low VIX"}},
        }.get(ns)
    mock_read.side_effect = fake_read
    mock_recent.return_value = [{"created_at": "2026-06-07", "severity": "pass", "verdict": "ok"}]
    from review_agent.review_memory import load_review_context

    ctx = load_review_context("conformance")
    assert "anti-churn respected" in ctx          # current task detail loaded
    assert "over-bullish in low VIX" in ctx        # global always loaded
    assert "efficacy" in ctx                        # index one-liner present
    assert "flagged 3x" in ctx                      # other task's index entry...
    # ...but NOT other task's *detail* (we never read efficacy:detail)
    assert "efficacy:detail" not in [c.args[0] for c in mock_read.call_args_list]


@patch("review_agent.review_memory.list_recent_reviews")
@patch("review_agent.review_memory.read_reviewer_memory")
def test_load_context_fresh_when_no_namespace(mock_read, mock_recent):
    mock_read.return_value = None
    mock_recent.return_value = []
    from review_agent.review_memory import load_review_context

    ctx = load_review_context("brand_new_type")
    assert "fresh" in ctx.lower()
