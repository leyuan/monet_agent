"""Stock Agent tools — autonomous-mode and chat-mode."""

import logging
import os
from typing import Literal

from alpaca.trading.requests import MarketOrderRequest, LimitOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from tavily import TavilyClient
import yfinance as yf

from stock_agent.alpaca_client import get_trading_client
from stock_agent.db import (
    add_to_watchlist,
    create_trade,
    get_trades,
    get_watchlist,
    read_journal,
    read_memory,
    remove_from_watchlist,
    update_trade,
    write_journal as db_write_journal,
    write_memory as db_write_memory,
    read_all_memory,
)
from stock_agent.market_data import get_historical_bars, get_historical_data_dict, get_portfolio, get_quote
from stock_agent.risk import check_risk
from stock_agent.supabase_client import get_supabase
from stock_agent.technical import compute_indicators

logger = logging.getLogger(__name__)


# ============================================================
# Shared tools (both modes)
# ============================================================

def internet_search(
    query: str,
    *,
    topic: Literal["general", "news", "finance"] = "general",
    max_results: int = 5,
) -> list[dict]:
    """Search the internet for news, analysis, and financial information.

    Args:
        query: The search query string.
        topic: Category - "general", "news", or "finance".
        max_results: Maximum number of results (1-10).

    Returns:
        List of search results with title, url, and content snippet.
    """
    client = TavilyClient(api_key=os.environ.get("TAVILY_API_KEY"))
    response = client.search(
        query=query,
        topic=topic,
        max_results=max_results,
    )
    return response.get("results", [])


def get_stock_quote(symbol: str) -> dict:
    """Get the latest quote for a stock symbol.

    Args:
        symbol: Stock ticker symbol (e.g. "AAPL").

    Returns:
        Dict with ask_price, bid_price, and timestamp.
    """
    return get_quote(symbol)


# ============================================================
# Autonomous-mode tools (used in autonomy.py)
# ============================================================

def get_historical_data(symbol: str, days: int = 90) -> dict:
    """Get historical OHLCV data for a stock.

    Args:
        symbol: Stock ticker symbol.
        days: Number of days of history (default 90).

    Returns:
        Dict with bars (date, OHLCV), count, and latest close.
    """
    return get_historical_data_dict(symbol, days=days)


def technical_analysis(symbol: str, days: int = 90) -> dict:
    """Run technical analysis on a stock — RSI, MACD, Bollinger, SMA, volume, ATR.

    Args:
        symbol: Stock ticker symbol.
        days: Number of days of data to analyze.

    Returns:
        Dict of indicators and signals.
    """
    df = get_historical_bars(symbol, days=days)
    return {"symbol": symbol, **compute_indicators(df)}


def fundamental_analysis(symbol: str) -> dict:
    """Get fundamental data for a stock using yfinance.

    Args:
        symbol: Stock ticker symbol.

    Returns:
        Dict with P/E, market cap, revenue, earnings, and other fundamentals.
    """
    ticker = yf.Ticker(symbol)
    info = ticker.info

    return {
        "symbol": symbol,
        "name": info.get("longName", symbol),
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "market_cap": info.get("marketCap"),
        "pe_ratio": info.get("trailingPE"),
        "forward_pe": info.get("forwardPE"),
        "peg_ratio": info.get("pegRatio"),
        "price_to_book": info.get("priceToBook"),
        "revenue": info.get("totalRevenue"),
        "revenue_growth": info.get("revenueGrowth"),
        "earnings_growth": info.get("earningsGrowth"),
        "profit_margin": info.get("profitMargins"),
        "debt_to_equity": info.get("debtToEquity"),
        "current_ratio": info.get("currentRatio"),
        "dividend_yield": info.get("dividendYield"),
        "beta": info.get("beta"),
        "fifty_two_week_high": info.get("fiftyTwoWeekHigh"),
        "fifty_two_week_low": info.get("fiftyTwoWeekLow"),
        "analyst_target": info.get("targetMeanPrice"),
        "recommendation": info.get("recommendationKey"),
    }


def screen_stocks(
    criteria: str = "trending",
    sector: str | None = None,
) -> dict:
    """Screen the market for stock candidates based on criteria.

    Args:
        criteria: Screening strategy — "trending", "value", "momentum", "oversold".
        sector: Optional sector filter (e.g. "Technology").

    Returns:
        Dict with list of candidate symbols and brief descriptions.
    """
    # Use Tavily to find trending/notable stocks
    query_map = {
        "trending": "most actively traded stocks today market movers",
        "value": "undervalued stocks good value investing opportunities",
        "momentum": "stocks with strong momentum breakout candidates",
        "oversold": "oversold stocks potential bounce recovery plays",
    }
    query = query_map.get(criteria, query_map["trending"])
    if sector:
        query += f" {sector} sector"

    results = internet_search(query, topic="finance", max_results=5)
    return {
        "criteria": criteria,
        "sector": sector,
        "results": results,
    }


def place_order(
    symbol: str,
    side: Literal["buy", "sell"],
    quantity: float,
    order_type: Literal["market", "limit"] = "market",
    limit_price: float | None = None,
    thesis: str | None = None,
    confidence: float | None = None,
) -> dict:
    """Place a trade order via Alpaca paper trading.

    IMPORTANT: Always run check_trade_risk first. This tool should only be called
    from the autonomous loop, never from chat mode.

    Args:
        symbol: Stock ticker symbol.
        side: "buy" or "sell".
        quantity: Number of shares.
        order_type: "market" or "limit".
        limit_price: Required if order_type is "limit".
        thesis: The reasoning behind this trade.
        confidence: Confidence score 0.0-1.0.

    Returns:
        Dict with order details and trade record.
    """
    # Risk check
    risk = check_risk(symbol, side, quantity, limit_price)
    if not risk["approved"]:
        return {"error": f"Risk check failed: {risk['reason']}", "risk": risk}

    # Place order with Alpaca
    client = get_trading_client()
    order_side = OrderSide.BUY if side == "buy" else OrderSide.SELL

    if order_type == "limit" and limit_price is not None:
        request = LimitOrderRequest(
            symbol=symbol,
            qty=quantity,
            side=order_side,
            time_in_force=TimeInForce.DAY,
            limit_price=limit_price,
        )
    else:
        request = MarketOrderRequest(
            symbol=symbol,
            qty=quantity,
            side=order_side,
            time_in_force=TimeInForce.DAY,
        )

    order = client.submit_order(request)

    # Record in database
    trade = create_trade(
        symbol=symbol,
        side=side,
        quantity=quantity,
        order_type=order_type,
        limit_price=limit_price,
        thesis=thesis,
        confidence=confidence,
    )

    # Update with broker order ID
    update_trade(trade["id"], {
        "broker_order_id": str(order.id),
        "status": str(order.status),
    })

    return {
        "trade_id": trade["id"],
        "broker_order_id": str(order.id),
        "symbol": symbol,
        "side": side,
        "quantity": quantity,
        "order_type": order_type,
        "status": str(order.status),
        "risk_metrics": risk.get("metrics", {}),
    }


def read_agent_memory(key: str) -> dict:
    """Read a specific memory entry by key.

    Args:
        key: Memory key (e.g. 'market_outlook', 'strategy', 'watchlist_rationale_AAPL').

    Returns:
        The memory value or None if not found.
    """
    result = read_memory(key)
    if result:
        return {"key": key, "value": result["value"], "updated_at": result["updated_at"]}
    return {"key": key, "value": None}


def write_agent_memory(key: str, value: dict) -> dict:
    """Write or update a persistent memory entry.

    Args:
        key: Memory key.
        value: Dict of data to store.

    Returns:
        Confirmation of the write.
    """
    result = db_write_memory(key, value)
    return {"key": key, "status": "saved", "updated_at": result["updated_at"]}


def write_journal_entry(
    entry_type: Literal["research", "analysis", "trade", "reflection", "market_scan"],
    title: str,
    content: str,
    symbols: list[str] | None = None,
) -> dict:
    """Write a journal entry recording the agent's activity or thoughts.

    Args:
        entry_type: Category of the entry.
        title: Brief title.
        content: Full markdown content.
        symbols: Related ticker symbols.

    Returns:
        The created journal entry.
    """
    result = db_write_journal(entry_type, title, content, symbols=symbols)
    return {"journal_id": result["id"], "status": "created"}


def manage_watchlist(
    action: Literal["add", "remove", "list"],
    symbol: str | None = None,
    thesis: str | None = None,
    target_entry: float | None = None,
    target_exit: float | None = None,
) -> dict:
    """Manage the agent's watchlist.

    Args:
        action: "add", "remove", or "list".
        symbol: Required for add/remove.
        thesis: Why watching this symbol (for add).
        target_entry: Target entry price (for add).
        target_exit: Target exit price (for add).

    Returns:
        Watchlist item or full list.
    """
    if action == "list":
        return {"watchlist": get_watchlist()}
    if not symbol:
        return {"error": "Symbol required for add/remove"}
    if action == "add":
        item = add_to_watchlist(symbol, thesis=thesis, target_entry=target_entry, target_exit=target_exit)
        return {"action": "added", "item": item}
    if action == "remove":
        removed = remove_from_watchlist(symbol)
        return {"action": "removed", "symbol": symbol, "success": removed}
    return {"error": f"Unknown action: {action}"}


def get_portfolio_state() -> dict:
    """Get the current portfolio state from Alpaca.

    Returns:
        Dict with equity, cash, positions, and P&L.
    """
    return get_portfolio()


def check_trade_risk(
    symbol: str,
    side: Literal["buy", "sell"],
    quantity: float,
    limit_price: float | None = None,
) -> dict:
    """Check if a proposed trade passes risk management rules.

    Args:
        symbol: Stock ticker.
        side: "buy" or "sell".
        quantity: Number of shares.
        limit_price: Optional limit price.

    Returns:
        Dict with 'approved' bool and risk metrics.
    """
    return check_risk(symbol, side, quantity, limit_price)


# ============================================================
# Chat-mode tools (read-only access to agent's brain)
# ============================================================

def get_my_portfolio() -> dict:
    """Show the agent's current portfolio holdings and P&L from Alpaca.

    Returns:
        Portfolio with equity, cash, positions.
    """
    return get_portfolio()


def query_database(sql: str) -> dict:
    """Execute a read-only SQL query against the agent's Supabase database.

    Use this to answer questions about watchlist, trades, journal entries, memory,
    and risk settings. Read the /skills/database-guide/SKILL.md for the full schema.

    Only SELECT queries are allowed. Any INSERT/UPDATE/DELETE will be rejected.

    Args:
        sql: A SELECT SQL query.

    Returns:
        Dict with rows (list of dicts) or an error message.
    """
    normalized = sql.strip().rstrip(";").strip()
    if not normalized.upper().startswith("SELECT"):
        return {"error": "Only SELECT queries are allowed in chat mode."}

    try:
        sb = get_supabase()
        result = sb.rpc("exec_readonly_sql", {"query": normalized}).execute()
        return {"rows": result.data}
    except Exception as e:
        return {"error": str(e)}


# ============================================================
# Tool collections for each mode
# ============================================================

AUTONOMOUS_TOOLS = [
    internet_search,
    get_stock_quote,
    get_historical_data,
    technical_analysis,
    fundamental_analysis,
    screen_stocks,
    place_order,
    read_agent_memory,
    write_agent_memory,
    write_journal_entry,
    manage_watchlist,
    get_portfolio_state,
    check_trade_risk,
]

CHAT_TOOLS = [
    internet_search,
    get_stock_quote,
    get_my_portfolio,
    query_database,
]
