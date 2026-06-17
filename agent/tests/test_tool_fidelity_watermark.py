from review_agent.tool_fidelity import select_unreviewed, advance_cursor


def _roots(ids):  # newest-first
    return [{"run_id": i, "start_time": f"2026-06-17T1{n}:00:00"} for n, i in enumerate(ids)]


def test_cold_start_returns_most_recent_n_oldest_first():
    roots = _roots(["c", "b", "a"])  # c newest
    out = select_unreviewed(roots, None, cold_start_n=2)
    assert [r["run_id"] for r in out] == ["b", "c"]  # 2 most recent, oldest-first


def test_skips_already_reviewed():
    roots = _roots(["c", "b", "a"])
    cursor = {"reviewed_run_ids": ["a", "b"]}
    out = select_unreviewed(roots, cursor, cold_start_n=5)
    assert [r["run_id"] for r in out] == ["c"]


def test_late_arrival_older_run_still_reviewed_if_unseen():
    # 'a' arrives late (older start_time) but was never reviewed → still selected
    roots = _roots(["c", "b", "a"])
    cursor = {"reviewed_run_ids": ["c", "b"], "last_reviewed_start_time": "2026-06-17T11:00:00"}
    out = select_unreviewed(roots, cursor, cold_start_n=5)
    assert [r["run_id"] for r in out] == ["a"]


def test_advance_prepends_and_caps():
    cur = advance_cursor(None, "r1", "2026-06-17T10:00:00")
    cur = advance_cursor(cur, "r2", "2026-06-17T11:00:00", baseline={"runtime_ms_p50": 100})
    assert cur["reviewed_run_ids"][0] == "r2"
    assert cur["graph"] == "autonomous_loop"
    assert cur["last_reviewed_start_time"] == "2026-06-17T11:00:00"
    assert cur["baseline"]["runtime_ms_p50"] == 100


def test_advance_respects_cap():
    cur = None
    for n in range(60):
        cur = advance_cursor(cur, f"r{n}", "2026-06-17T10:00:00", cap=50)
    assert len(cur["reviewed_run_ids"]) == 50
    assert cur["reviewed_run_ids"][0] == "r59"
