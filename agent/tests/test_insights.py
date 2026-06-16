from review_agent.insights import stamp_insight


def test_new_insight_appended():
    out = stamp_insight([], "agent over-bullish in low VIX", ["r1"], "2026-06-15")
    assert len(out) == 1
    e = out[0]
    assert e == {
        "text": "agent over-bullish in low VIX",
        "source_review_ids": ["r1"],
        "confidence": "low",
        "first_seen": "2026-06-15",
        "last_seen": "2026-06-15",
        "count": 1,
    }


def test_new_insight_confidence_is_low():
    """New insights always start at low confidence — caller cannot supply it."""
    out = stamp_insight([], "some pattern", ["r1"], "2026-06-15")
    assert out[0]["confidence"] == "low"


def test_same_text_merges_not_duplicates():
    patterns = stamp_insight([], "rationalized momentum", ["r1"], "2026-06-15")
    out = stamp_insight(patterns, "rationalized momentum", ["r2"], "2026-06-16")
    assert len(out) == 1
    e = out[0]
    assert e["count"] == 2
    assert e["source_review_ids"] == ["r1", "r2"]   # unioned + sorted
    assert e["first_seen"] == "2026-06-15"           # unchanged
    assert e["last_seen"] == "2026-06-16"            # updated
    assert e["confidence"] == "low"                  # still low at count=2


def test_promotes_to_established_after_threshold():
    """Confidence is 'low' until seen ≥3 times (CONFIRM_THRESHOLD), then 'established'."""
    patterns = []
    patterns = stamp_insight(patterns, "anti-churn respected", ["r1"], "2026-06-01")
    assert patterns[0]["confidence"] == "low"
    assert patterns[0]["count"] == 1

    patterns = stamp_insight(patterns, "anti-churn respected", ["r2"], "2026-06-07")
    assert patterns[0]["confidence"] == "low"
    assert patterns[0]["count"] == 2

    patterns = stamp_insight(patterns, "anti-churn respected", ["r3"], "2026-06-14")
    assert patterns[0]["confidence"] == "established"
    assert patterns[0]["count"] == 3


def test_distinct_texts_kept_separate():
    patterns = stamp_insight([], "A", ["r1"], "2026-06-15")
    out = stamp_insight(patterns, "B", ["r2"], "2026-06-15")
    assert {e["text"] for e in out} == {"A", "B"}


def test_duplicate_source_ids_deduped():
    patterns = stamp_insight([], "A", ["r1"], "d1")
    out = stamp_insight(patterns, "A", ["r1", "r2"], "d2")
    assert out[0]["source_review_ids"] == ["r1", "r2"]
