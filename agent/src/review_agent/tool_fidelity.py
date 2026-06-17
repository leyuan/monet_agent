"""Pure tool-fidelity logic: phase identification, per-phase invariants, deterministic
fact extraction from a run trace, and the watermark cursor. No I/O — all functions take
plain dicts and return plain dicts so they unit-test without LangSmith or Supabase.
"""

# Per-phase process invariants for the trader (autonomous_loop).
#   required  : tools that MUST appear at least once (unconditional steps only —
#               conditional tools like place_order are covered by `order`, not `required`).
#   forbidden : tools that must NOT appear in this phase.
#   order     : (A, B) pairs — if both present, every A must precede every B.
#   terminal  : tools the run should end with (the last tool call should be one of these).
PHASE_INVARIANTS = {
    "factor_loop_weekday": {
        "required": ["score_universe", "generate_factor_rankings"],
        "forbidden": [],
        "order": [("generate_factor_rankings", "place_order"), ("place_order", "record_decision")],
        "terminal": ["write_journal_entry", "record_daily_snapshot"],
    },
    "factor_loop_weekend": {
        "required": ["score_universe", "generate_factor_rankings", "write_journal_entry"],
        "forbidden": ["place_order"],
        "order": [],
        "terminal": ["write_journal_entry"],
    },
    "reflection": {
        "required": ["write_journal_entry"],
        "forbidden": ["place_order", "score_universe"],
        "order": [],
        "terminal": ["write_journal_entry"],
    },
    "weekly_review": {
        "required": ["audit_factor_ic", "write_journal_entry"],
        "forbidden": ["place_order"],
        "order": [],
        "terminal": ["write_journal_entry"],
    },
    "unknown": {"required": [], "forbidden": [], "order": [], "terminal": []},
}


def identify_phase(run: dict, *, weekend: bool) -> str:
    """Deterministic heuristic from the tool calls + weekday/weekend. Returns 'unknown'
    when no signature matches (which limits checks to generic ones — honest degradation)."""
    names = {c.get("name") for c in run.get("tool_calls", [])}
    if "audit_factor_ic" in names:
        return "weekly_review"
    if "score_universe" in names:
        return "factor_loop_weekend" if weekend else "factor_loop_weekday"
    if "check_live_vs_backtest_divergence" in names or (
        "write_journal_entry" in names and "place_order" not in names
    ):
        return "reflection"
    return "unknown"


from collections import Counter

# Tools that legitimately repeat within a run (don't flag as redundant).
_REPEATABLE = {"place_order", "record_decision", "update_stock_analysis", "get_quote"}
_REDUNDANT_THRESHOLD = 2  # a non-repeatable tool called > this many times is wasteful


def _parse_ms(start: str | None, end: str | None) -> int | None:
    if not start or not end:
        return None
    from datetime import datetime
    try:
        return int((datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds() * 1000)
    except (ValueError, TypeError):
        return None


def analyze_tool_fidelity(run: dict, phase: str) -> dict:
    calls = run.get("tool_calls", [])
    names = [c.get("name") for c in calls]
    inv = PHASE_INVARIANTS.get(phase, PHASE_INVARIANTS["unknown"])
    present = set(names)

    violations = []
    for req in inv["required"]:
        if req not in present:
            violations.append({"type": "missing_required", "detail": req})
    for fb in inv["forbidden"]:
        if fb in present:
            violations.append({"type": "forbidden_present", "detail": fb})
    for a, b in inv["order"]:
        if a in present and b in present:
            # every A must precede every B → last A index must be < first B index
            if max(i for i, n in enumerate(names) if n == a) > min(i for i, n in enumerate(names) if n == b):
                violations.append({"type": "order_violation", "detail": f"{a} must precede {b}"})
    if inv["terminal"] and names and names[-1] not in inv["terminal"]:
        violations.append({"type": "missing_terminal",
                           "detail": f"run ended with {names[-1]}, expected one of {inv['terminal']}"})

    total = len(calls)
    failed = sum(1 for c in calls if c.get("error"))
    per_tool_errors = [{"tool": t, "error": "see trace", "count": n}
                       for t, n in Counter(c.get("name") for c in calls if c.get("error")).items()]

    # recovery: for each errored call, did a later same-tool call succeed / fail / never happen?
    recovery = []
    for idx, c in enumerate(calls):
        if not c.get("error"):
            continue
        later = [x for x in calls[idx + 1:] if x.get("name") == c.get("name")]
        if not later:
            recovery.append({"tool": c.get("name"), "action": "swallowed"})
        elif any(not x.get("error") for x in later):
            recovery.append({"tool": c.get("name"), "action": "retried_ok"})
        else:
            recovery.append({"tool": c.get("name"), "action": "retried_failed"})

    redundant = [{"tool": t, "count": n} for t, n in Counter(names).items()
                 if t not in _REPEATABLE and n > _REDUNDANT_THRESHOLD]

    durations = [d for d in (_parse_ms(c.get("start_time"), c.get("end_time")) for c in calls) if d]
    return {
        "phase": phase,
        "run_completed": run.get("error") is None,
        "total_calls": total,
        "failed_calls": failed,
        "success_rate": (total - failed) / total if total else 1.0,
        "invariant_violations": violations,
        "per_tool_errors": per_tool_errors,
        "recovery": recovery,
        "redundant_calls": redundant,
        "runtime_ms": sum(durations) if durations else None,
        "token_usage": run.get("total_tokens"),
    }
