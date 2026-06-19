from review_agent.operation_success import OPERATION_SPECS, READ_ONLY_TOOLS
from stock_agent.tools import AUTONOMOUS_TOOLS


def _tool_name(t):
    return getattr(t, "name", getattr(t, "__name__", ""))


def test_every_trader_tool_is_classified():
    """Coverage guarantee: each autonomous tool is either a known operation or a known
    read. Adding a new trader tool breaks this until someone classifies it."""
    names = {_tool_name(t) for t in AUTONOMOUS_TOOLS}
    classified = set(OPERATION_SPECS) | READ_ONLY_TOOLS
    assert names == classified, (
        f"unclassified trader tools: {names - classified}; "
        f"stale registry entries: {classified - names}"
    )


def test_db_specs_have_required_shape():
    for tool, spec in OPERATION_SPECS.items():
        assert spec["kind"] in ("db", "trace_only"), tool
        if spec["kind"] == "db":
            assert "verify" in spec and "table" in spec and "match" in spec, tool
            m = spec["match"]
            assert m["src"] in ("output", "input", "const") and m["col"] and m["field"], tool
