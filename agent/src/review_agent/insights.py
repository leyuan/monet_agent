"""Provenance-stamped insight entries for reviewer standing memory.

A standing-memory value holds {"patterns": [insight, ...]} where each insight carries
its provenance (which reviews produced it, how often, when). `stamp_insight` is a PURE
merge — no DB, no clock (caller passes `now`)."""

CONFIRM_THRESHOLD = 3


def _confidence_for(count: int) -> str:
    return "established" if count >= CONFIRM_THRESHOLD else "low"


def stamp_insight(patterns: list[dict], text: str, source_review_ids: list[str], now: str) -> list[dict]:
    """Merge an observation into `patterns`. Confidence is derived from corroboration
    count: 'low' until seen CONFIRM_THRESHOLD (3) times, then 'established'."""
    for p in patterns:
        if p["text"] == text:
            p["count"] += 1
            p["source_review_ids"] = sorted(set(p["source_review_ids"]) | set(source_review_ids))
            p["last_seen"] = now
            p["confidence"] = _confidence_for(p["count"])
            return patterns
    patterns.append({
        "text": text,
        "source_review_ids": sorted(set(source_review_ids)),
        "confidence": _confidence_for(1),
        "first_seen": now,
        "last_seen": now,
        "count": 1,
    })
    return patterns
