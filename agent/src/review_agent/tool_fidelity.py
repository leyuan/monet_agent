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
