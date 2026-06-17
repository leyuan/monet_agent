from review_agent.trace import select_roots_by_name


class _Root:
    def __init__(self, name, rid):
        self.name = name; self.id = rid


def test_filters_to_trader_graph_excludes_reviewer():
    roots = [_Root("review_agent", "x"), _Root("autonomous_loop", "a"),
             _Root("monet_agent", "m"), _Root("autonomous_loop", "b")]
    out = select_roots_by_name(roots, "autonomous_loop", limit=5)
    assert [r.id for r in out] == ["a", "b"]


def test_limit_applied_after_filter():
    roots = [_Root("autonomous_loop", "a"), _Root("review_agent", "x"),
             _Root("autonomous_loop", "b"), _Root("autonomous_loop", "c")]
    out = select_roots_by_name(roots, "autonomous_loop", limit=2)
    assert [r.id for r in out] == ["a", "b"]
