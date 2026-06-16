from review_agent.insights import stamp_insight


def test_new_insight_appended():
    out = stamp_insight([], "agent over-bullish in low VIX", ["r1"], "low", "2026-06-15")
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


def test_same_text_merges_not_duplicates():
    patterns = stamp_insight([], "rationalized momentum", ["r1"], "low", "2026-06-15")
    out = stamp_insight(patterns, "rationalized momentum", ["r2"], "established", "2026-06-16")
    assert len(out) == 1
    e = out[0]
    assert e["count"] == 2
    assert e["source_review_ids"] == ["r1", "r2"]   # unioned + sorted
    assert e["first_seen"] == "2026-06-15"           # unchanged
    assert e["last_seen"] == "2026-06-16"            # updated
    assert e["confidence"] == "established"          # updated


def test_distinct_texts_kept_separate():
    patterns = stamp_insight([], "A", ["r1"], "low", "2026-06-15")
    out = stamp_insight(patterns, "B", ["r2"], "low", "2026-06-15")
    assert {e["text"] for e in out} == {"A", "B"}


def test_duplicate_source_ids_deduped():
    patterns = stamp_insight([], "A", ["r1"], "low", "d1")
    out = stamp_insight(patterns, "A", ["r1", "r2"], "low", "d2")
    assert out[0]["source_review_ids"] == ["r1", "r2"]
