from unittest.mock import patch


@patch("review_agent.review_memory.list_recent_reviews")
@patch("review_agent.review_memory.read_reviewer_memory")
def test_load_context_includes_only_current_task_detail(mock_read, mock_recent):
    def fake_read(ns):
        return {
            "index": {"value": {"conformance": "clean 5 runs", "efficacy": "flagged 3x"}},
            "conformance:detail": {"value": {"patterns": [
                {"text": "anti-churn respected", "confidence": "established", "count": 6,
                 "first_seen": "2026-06-01", "last_seen": "2026-06-14", "source_review_ids": ["r1"]},
                {"text": "near 10% cap on NVDA", "confidence": "low", "count": 1,
                 "first_seen": "2026-06-14", "last_seen": "2026-06-14", "source_review_ids": ["r2"]},
            ]}},
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

    # low-confidence insight is tagged (unconfirmed)
    assert "(unconfirmed)" in ctx
    assert "near 10% cap on NVDA (unconfirmed)" in ctx

    # established insight is NOT tagged
    assert "anti-churn respected (unconfirmed)" not in ctx


@patch("review_agent.review_memory.list_recent_reviews")
@patch("review_agent.review_memory.read_reviewer_memory")
def test_load_context_fresh_when_no_namespace(mock_read, mock_recent):
    mock_read.return_value = None
    mock_recent.return_value = []
    from review_agent.review_memory import load_review_context

    ctx = load_review_context("brand_new_type")
    assert "fresh" in ctx.lower()
