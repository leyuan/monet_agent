from review_agent.run_cursor import is_finished, select_unreviewed, advance_cursor


def test_is_finished_requires_end_time():
    assert is_finished({"end_time": "2026-06-19T14:05:00"}) is True
    assert is_finished({"end_time": None}) is False
    assert is_finished({}) is False


def test_select_unreviewed_cold_start_takes_most_recent_n():
    roots = [{"run_id": "r3"}, {"run_id": "r2"}, {"run_id": "r1"}]  # newest-first
    out = select_unreviewed(roots, None, cold_start_n=2)
    assert [r["run_id"] for r in out] == ["r2", "r3"]  # returned oldest-first


def test_select_unreviewed_skips_seen():
    roots = [{"run_id": "r3"}, {"run_id": "r2"}, {"run_id": "r1"}]
    cursor = {"reviewed_run_ids": ["r1", "r2"]}
    out = select_unreviewed(roots, cursor, cold_start_n=5)
    assert [r["run_id"] for r in out] == ["r3"]


def test_advance_cursor_prepends_and_caps():
    cur = advance_cursor(None, "r1", "2026-06-19T10:00:00")
    cur = advance_cursor(cur, "r2", "2026-06-19T11:00:00", baseline={"x": 1})
    assert cur["reviewed_run_ids"][0] == "r2"
    assert cur["graph"] == "autonomous_loop"
    assert cur["baseline"]["x"] == 1
