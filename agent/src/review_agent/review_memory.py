"""Bounded context loader for a review run.

Loads ONLY: the index (all tasks, one-liners) + the CURRENT task's detail +
global insights + the last K verdicts of this type. Never loads other tasks'
detail (kept isolated for objectivity). Context stays flat over time.
"""
import json

from review_agent.db import list_recent_reviews, read_reviewer_memory

K_RECENT = 5


def _fmt(mem: dict | None) -> str:
    if not mem or not mem.get("value"):
        return "(none yet — fresh)"
    return json.dumps(mem["value"], indent=2)


def load_review_context(review_type: str) -> str:
    """Assemble the bounded memory block for a review of `review_type`."""
    index = read_reviewer_memory("index")
    detail = read_reviewer_memory(f"{review_type}:detail")
    glob = read_reviewer_memory("global")
    recent = list_recent_reviews(review_type, limit=K_RECENT)

    parts = [
        "## Reviewer memory (PRIORS only — always re-read ground-truth evidence; "
        "memory never determines a verdict)",
        "",
        "### Index — all review tasks (headlines + links)",
        _fmt(index),
        "",
        "### Global insights (apply to every task)",
        _fmt(glob),
        "",
        f"### Standing detail for '{review_type}'",
        _fmt(detail),
        "",
        f"### Last {len(recent)} '{review_type}' verdicts",
    ]
    if recent:
        for r in recent:
            parts.append(f"- [{r['created_at']}] {r['severity']}: {r['verdict']}")
    else:
        parts.append("(none yet — fresh)")
    return "\n".join(parts)
