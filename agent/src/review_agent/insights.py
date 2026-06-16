"""Provenance-stamped insight entries for reviewer standing memory.

A standing-memory value holds {"patterns": [insight, ...]} where each insight carries
its provenance (which reviews produced it, how often, when). `stamp_insight` is a PURE
merge — no DB, no clock (caller passes `now`)."""


def stamp_insight(
    patterns: list[dict],
    text: str,
    source_review_ids: list[str],
    confidence: str,
    now: str,
) -> list[dict]:
    """Merge an observation into `patterns` (mutates + returns it).

    If an entry with the same `text` exists: increment count, union source_review_ids,
    update last_seen + confidence. Otherwise append a new entry (count=1, first_seen=last_seen=now).
    """
    for p in patterns:
        if p["text"] == text:
            p["count"] += 1
            p["source_review_ids"] = sorted(set(p["source_review_ids"]) | set(source_review_ids))
            p["last_seen"] = now
            p["confidence"] = confidence
            return patterns
    patterns.append(
        {
            "text": text,
            "source_review_ids": sorted(set(source_review_ids)),
            "confidence": confidence,
            "first_seen": now,
            "last_seen": now,
            "count": 1,
        }
    )
    return patterns
