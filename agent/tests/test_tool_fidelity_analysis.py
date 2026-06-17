from review_agent.tool_fidelity import analyze_tool_fidelity


def _call(name, error=None, start=None, end=None, outputs=None):
    return {"name": name, "error": error, "inputs": {}, "outputs": outputs or {},
            "start_time": start, "end_time": end}


def _run(calls, run_error=None, total_tokens=None):
    return {"run_id": "r", "name": "autonomous_loop", "start_time": "2026-06-17T14:00:00",
            "error": run_error, "total_tokens": total_tokens, "tool_calls": calls}


def test_clean_factor_loop_passes_all_invariants():
    run = _run([_call("score_universe"), _call("generate_factor_rankings"),
                _call("place_order"), _call("record_decision"), _call("write_journal_entry")])
    f = analyze_tool_fidelity(run, "factor_loop_weekday")
    assert f["invariant_violations"] == []
    assert f["success_rate"] == 1.0
    assert f["run_completed"] is True


def test_missing_required_step_flagged():
    run = _run([_call("place_order"), _call("write_journal_entry")])  # no score_universe/rankings
    f = analyze_tool_fidelity(run, "factor_loop_weekday")
    types = {v["type"] for v in f["invariant_violations"]}
    assert "missing_required" in types


def test_forbidden_tool_on_weekend():
    run = _run([_call("score_universe"), _call("generate_factor_rankings"),
                _call("place_order"), _call("write_journal_entry")])
    f = analyze_tool_fidelity(run, "factor_loop_weekend")
    assert any(v["type"] == "forbidden_present" and "place_order" in v["detail"]
               for v in f["invariant_violations"])


def test_order_violation_place_before_rankings():
    run = _run([_call("score_universe"), _call("place_order"),
                _call("generate_factor_rankings"), _call("write_journal_entry")])
    f = analyze_tool_fidelity(run, "factor_loop_weekday")
    assert any(v["type"] == "order_violation" for v in f["invariant_violations"])


def test_benign_reorder_not_flagged():
    # enrich before score (both independent reads) — no ordering invariant between them
    run = _run([_call("enrich_eps_revisions"), _call("score_universe"),
                _call("generate_factor_rankings"), _call("write_journal_entry")])
    f = analyze_tool_fidelity(run, "factor_loop_weekday")
    assert f["invariant_violations"] == []


def test_success_rate_and_per_tool_errors():
    run = _run([_call("get_quote", error="timeout"), _call("get_quote"),
                _call("score_universe"), _call("generate_factor_rankings"),
                _call("write_journal_entry")])
    f = analyze_tool_fidelity(run, "factor_loop_weekday")
    assert f["total_calls"] == 5 and f["failed_calls"] == 1
    assert abs(f["success_rate"] - 0.8) < 1e-9
    assert any(e["tool"] == "get_quote" and e["count"] == 1 for e in f["per_tool_errors"])


def test_recovery_retried_ok():
    run = _run([_call("get_quote", error="timeout"), _call("get_quote"),
                _call("score_universe"), _call("generate_factor_rankings"),
                _call("write_journal_entry")])
    f = analyze_tool_fidelity(run, "factor_loop_weekday")
    assert {"tool": "get_quote", "action": "retried_ok"} in f["recovery"]


def test_recovery_swallowed_when_no_retry():
    run = _run([_call("score_universe"), _call("generate_factor_rankings"),
                _call("place_order", error="broker 500"), _call("write_journal_entry")])
    f = analyze_tool_fidelity(run, "factor_loop_weekday")
    assert {"tool": "place_order", "action": "swallowed"} in f["recovery"]


def test_run_not_completed_when_root_errored():
    run = _run([_call("score_universe")], run_error="GraphRecursionError")
    f = analyze_tool_fidelity(run, "factor_loop_weekday")
    assert f["run_completed"] is False


def test_redundant_calls_flagged():
    run = _run([_call("score_universe"), _call("score_universe"), _call("score_universe"),
                _call("generate_factor_rankings"), _call("write_journal_entry")])
    f = analyze_tool_fidelity(run, "factor_loop_weekday")
    assert any(r["tool"] == "score_universe" and r["count"] == 3 for r in f["redundant_calls"])


def test_empty_trace_zero_calls_no_crash():
    f = analyze_tool_fidelity(_run([]), "unknown")
    assert f["total_calls"] == 0 and f["success_rate"] == 1.0
