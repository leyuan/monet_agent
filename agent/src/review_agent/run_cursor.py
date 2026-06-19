"""Generic, graph-agnostic run-selection + watermark cursor for trace-native reviews.

Pure — no I/O. Shared by review-tool-fidelity and review-operation-success so neither
skill depends on the other. Moved here verbatim from tool_fidelity.py.
"""

_GRAPH = "autonomous_loop"


def is_finished(run: dict) -> bool:
    """A LangSmith run has terminated iff it has an `end_time` (whether it succeeded or
    errored). A still-running run has end_time=None — auditing it yields a partial,
    misleading trace, so callers must skip it."""
    return run.get("end_time") is not None


def select_unreviewed(roots: list[dict], cursor: dict | None, *, cold_start_n: int) -> list[dict]:
    """roots newest-first. Returns runs to review, OLDEST-first (so the watermark advances
    monotonically as each is processed)."""
    if cursor is None:
        chosen = roots[:cold_start_n]
    else:
        seen = set(cursor.get("reviewed_run_ids", []))
        chosen = [r for r in roots if r["run_id"] not in seen]
    return list(reversed(chosen))


def advance_cursor(cursor: dict | None, run_id: str, start_time: str, *,
                   baseline: dict | None = None, cap: int = 50) -> dict:
    cursor = dict(cursor or {})
    ids = [run_id, *cursor.get("reviewed_run_ids", [])][:cap]
    return {
        "graph": _GRAPH,
        "last_reviewed_start_time": start_time,
        "reviewed_run_ids": ids,
        "baseline": {**cursor.get("baseline", {}), **(baseline or {})},
    }
