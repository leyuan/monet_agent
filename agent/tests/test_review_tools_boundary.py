FORBIDDEN = {
    "place_order", "cancel_order", "attach_bracket_to_position",
    "write_agent_memory", "write_journal_entry", "manage_watchlist",
    "update_market_regime", "update_stock_analysis", "record_decision",
}


def test_review_tools_contain_no_trading_or_trader_mutation():
    from review_agent.tools import REVIEW_TOOLS
    names = {t.__name__ for t in REVIEW_TOOLS}
    leaked = names & FORBIDDEN
    assert not leaked, f"reviewer must not have these capabilities: {leaked}"


def test_review_tools_include_evidence_and_own_writers():
    from review_agent.tools import REVIEW_TOOLS
    names = {t.__name__ for t in REVIEW_TOOLS}
    assert {"query_database", "read_run_trace", "write_review",
            "read_reviewer_memory", "write_reviewer_memory"} <= names
