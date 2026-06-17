from review_agent.tool_fidelity import identify_phase, PHASE_INVARIANTS


def _run(tool_names):
    return {"run_id": "r", "name": "autonomous_loop", "start_time": "2026-06-17T14:00:00",
            "error": None, "tool_calls": [{"name": n, "error": None} for n in tool_names]}


def test_weekly_review_identified_by_audit_factor_ic():
    assert identify_phase(_run(["audit_factor_ic", "write_journal_entry"]), weekend=False) == "weekly_review"


def test_weekend_factor_loop():
    assert identify_phase(_run(["score_universe", "generate_factor_rankings"]), weekend=True) == "factor_loop_weekend"


def test_weekday_factor_loop():
    assert identify_phase(_run(["score_universe", "generate_factor_rankings", "place_order"]), weekend=False) == "factor_loop_weekday"


def test_reflection_no_scoring():
    assert identify_phase(_run(["check_live_vs_backtest_divergence", "write_journal_entry"]), weekend=False) == "reflection"


def test_unknown_when_no_signature():
    assert identify_phase(_run(["read_agent_memory"]), weekend=False) == "unknown"


def test_every_phase_has_an_invariant_entry():
    for p in ["factor_loop_weekday", "factor_loop_weekend", "reflection", "weekly_review", "unknown"]:
        assert p in PHASE_INVARIANTS
        entry = PHASE_INVARIANTS[p]
        assert set(entry) == {"required", "forbidden", "order", "terminal"}
