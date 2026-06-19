# Capability boundary for the reviewer agent.
#
# PRIMARY guard = ALLOWLIST: REVIEW_TOOLS must be EXACTLY this set. Any tool
# added or removed (especially a trading/mutation tool) fails this test, forcing
# a deliberate, reviewed decision. An allowlist is strictly stronger than a
# denylist for a security boundary — it cannot be bypassed by a tool we forgot
# to denylist.
ALLOWED = {
    # read-only evidence
    "query_database",
    "read_agent_memory",
    "read_all_agent_memory",
    "get_performance_comparison",
    "read_run_trace",
    # the reviewer's own stores (its only write capability)
    "begin_review",
    "write_review",
    "read_reviewer_memory",
    "write_reviewer_memory",
    "promote_to_global",
    "record_insight",
    "get_tool_fidelity_runs",
    "mark_run_reviewed",
    "get_operation_success_runs",
}

# SECONDARY guard = explicit denylist of the most dangerous trader-mutating /
# trading tools. Redundant with the allowlist, but documents intent and gives a
# readable failure if one ever leaks in.
FORBIDDEN = {
    "place_order", "cancel_order", "attach_bracket_to_position",
    "write_agent_memory", "write_journal_entry", "manage_watchlist",
    "update_market_regime", "update_stock_analysis", "record_decision",
    "reconcile_positions", "record_daily_snapshot", "send_daily_recap",
    "send_daily_subscription_emails", "send_weekly_cycle_report",
    "submit_user_insight", "audit_factor_ic",
}


def test_review_tools_are_exactly_the_allowlist():
    """The reviewer's tool surface must equal the allowlist — nothing added, nothing removed."""
    from review_agent.tools import REVIEW_TOOLS
    names = {t.__name__ for t in REVIEW_TOOLS}
    assert names == ALLOWED, f"REVIEW_TOOLS drifted from the allowlist: {names ^ ALLOWED}"


def test_review_tools_contain_no_trading_or_trader_mutation():
    """Defense-in-depth: no known trading/mutation tool may appear in REVIEW_TOOLS."""
    from review_agent.tools import REVIEW_TOOLS
    names = {t.__name__ for t in REVIEW_TOOLS}
    leaked = names & FORBIDDEN
    assert not leaked, f"reviewer must not have these capabilities: {leaked}"
