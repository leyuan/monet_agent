"""Stock Agent tools — autonomous-mode and chat-mode.

Public surface preserved from the pre-split tools.py: AUTONOMOUS_TOOLS,
CHAT_TOOLS, and the individual tool functions (importable directly from
stock_agent.tools). Implementations live in the category submodules.
"""

# Re-exported for external callers that import it through this package
# (e.g. backtest/data.py).
from stock_agent.market_data import get_sp500_sp400_tickers  # noqa: F401

from stock_agent.tools.market import (
    internet_search,
    get_stock_quote,
    get_historical_data,
    technical_analysis,
    fundamental_analysis,
    screen_stocks,
    company_profile,
    sector_analysis,
    peer_comparison,
    earnings_calendar,
    eps_estimates,
    market_breadth,
)
from stock_agent.tools.trading import (
    place_order,
    cancel_order,
    get_open_orders,
    get_portfolio_state,
    reconcile_positions,
    check_trade_risk,
    get_my_portfolio,
    attach_bracket_to_position,
)
from stock_agent.tools.research import assess_ai_bubble_risk, assess_ai_cycle_durability
from stock_agent.tools.strategy_health import (
    audit_factor_ic,
    check_live_vs_backtest_divergence,
    suggest_factor_weight_adjustment,
)
from stock_agent.tools.reports import (
    send_daily_recap,
    send_daily_subscription_emails,
    send_weekly_cycle_report,
    record_daily_snapshot,
    get_performance_comparison,
    position_health_check,
)
from stock_agent.tools.memory import (
    read_agent_memory,
    read_all_agent_memory,
    write_agent_memory,
    write_journal_entry,
    update_market_regime,
    update_stock_analysis,
    record_decision,
    manage_watchlist,
    query_database,
    submit_user_insight,
)
from stock_agent.tools.factors import (
    score_universe,
    enrich_eps_revisions,
    generate_factor_rankings,
    check_watchlist_alerts,
    discover_catalysts,
    get_earnings_results,
)

AUTONOMOUS_TOOLS = [
    internet_search,
    get_stock_quote,
    get_historical_data,
    technical_analysis,
    fundamental_analysis,
    screen_stocks,
    company_profile,
    sector_analysis,
    peer_comparison,
    earnings_calendar,
    eps_estimates,
    market_breadth,
    place_order,
    cancel_order,
    get_open_orders,
    attach_bracket_to_position,
    read_agent_memory,
    read_all_agent_memory,
    write_agent_memory,
    write_journal_entry,
    manage_watchlist,
    get_portfolio_state,
    reconcile_positions,
    check_trade_risk,
    query_database,
    send_daily_recap,
    send_daily_subscription_emails,
    update_market_regime,
    update_stock_analysis,
    record_decision,
    record_daily_snapshot,
    get_performance_comparison,
    position_health_check,
    check_watchlist_alerts,
    # Factor-based scoring tools
    score_universe,
    enrich_eps_revisions,
    generate_factor_rankings,
    # Catalyst discovery
    discover_catalysts,
    # Earnings intelligence
    get_earnings_results,
    # AI bubble / concentration risk
    assess_ai_bubble_risk,
    # AI cycle durability
    assess_ai_cycle_durability,
    send_weekly_cycle_report,
    # Tier 1 strategy health monitoring
    audit_factor_ic,
    check_live_vs_backtest_divergence,
    suggest_factor_weight_adjustment,
]

CHAT_TOOLS = [
    internet_search,
    get_stock_quote,
    get_my_portfolio,
    query_database,
    company_profile,
    sector_analysis,
    peer_comparison,
    market_breadth,
    eps_estimates,
    submit_user_insight,
    get_performance_comparison,
]
