"""Completion-awareness (Task 8 bugfix): the reviewer must NOT audit an in-progress
run as 'completed'. A LangSmith run is finished iff it has an end_time; `run_completed`
requires a clean finish (end_time present AND no error). A still-running run has
end_time=None and error=None — the old `error is None` check misread it as completed.
"""
from review_agent.tool_fidelity import analyze_tool_fidelity, is_finished


def _call(name, error=None):
    return {"name": name, "error": error, "inputs": {}, "outputs": {},
            "start_time": None, "end_time": None}


def _run(calls, end_time="2026-06-17T14:05:00", error=None):
    return {"run_id": "r", "name": "autonomous_loop", "start_time": "2026-06-17T14:00:00",
            "end_time": end_time, "error": error, "total_tokens": None, "tool_calls": calls}


def test_is_finished_requires_end_time():
    assert is_finished({"end_time": "2026-06-17T14:05:00"}) is True
    assert is_finished({"end_time": None}) is False
    assert is_finished({}) is False


def test_run_completed_false_when_still_running():
    # pending run: end_time None, error None -> still running, NOT completed (the bug)
    run = _run([_call("score_universe")], end_time=None)
    assert analyze_tool_fidelity(run, "factor_loop_weekday")["run_completed"] is False


def test_run_completed_true_when_finished_clean():
    run = _run([_call("score_universe"), _call("generate_factor_rankings"),
                _call("write_journal_entry")])
    assert analyze_tool_fidelity(run, "factor_loop_weekday")["run_completed"] is True


def test_run_completed_false_when_finished_with_error():
    run = _run([_call("score_universe")], error="GraphRecursionError")
    assert analyze_tool_fidelity(run, "factor_loop_weekday")["run_completed"] is False
