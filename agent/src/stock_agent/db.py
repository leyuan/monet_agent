"""Database CRUD operations for agent state."""

import logging

from stock_agent.supabase_client import get_supabase

logger = logging.getLogger(__name__)


# --- Agent Memory ---

def read_memory(key: str) -> dict | None:
    """Read a memory entry by key."""
    try:
        sb = get_supabase()
        result = sb.table("agent_memory").select("*").eq("key", key).maybe_single().execute()
        return result.data if result else None
    except Exception:
        logger.warning("Failed to read memory key=%s", key)
        return None


def read_all_memory() -> list[dict]:
    """Read all memory entries."""
    try:
        sb = get_supabase()
        result = sb.table("agent_memory").select("*").execute()
        return result.data if result else []
    except Exception:
        logger.warning("Failed to read all memory")
        return []


def write_memory(key: str, value: dict) -> dict:
    """Upsert a memory entry."""
    sb = get_supabase()
    result = (
        sb.table("agent_memory")
        .upsert({"key": key, "value": value, "updated_at": "now()"}, on_conflict="key")
        .execute()
    )
    return result.data[0]


def delete_memory(key: str) -> bool:
    """Delete a memory entry."""
    sb = get_supabase()
    result = sb.table("agent_memory").delete().eq("key", key).execute()
    return len(result.data) > 0


# --- Agent Journal ---

def write_journal(
    entry_type: str,
    title: str,
    content: str,
    symbols: list[str] | None = None,
    metadata: dict | None = None,
) -> dict:
    """Create a journal entry."""
    sb = get_supabase()
    result = (
        sb.table("agent_journal")
        .insert({
            "entry_type": entry_type,
            "title": title,
            "content": content,
            "symbols": symbols or [],
            "metadata": metadata or {},
        })
        .execute()
    )
    return result.data[0]


def read_journal(
    entry_type: str | None = None,
    limit: int = 10,
    symbols: list[str] | None = None,
) -> list[dict]:
    """Read recent journal entries with optional filters."""
    try:
        sb = get_supabase()
        query = sb.table("agent_journal").select("*").order("created_at", desc=True).limit(limit)
        if entry_type:
            query = query.eq("entry_type", entry_type)
        if symbols:
            query = query.overlaps("symbols", symbols)
        result = query.execute()
        return result.data if result else []
    except Exception:
        logger.warning("Failed to read journal")
        return []


# --- Trades ---

def create_trade(
    symbol: str,
    side: str,
    quantity: float,
    order_type: str = "market",
    limit_price: float | None = None,
    thesis: str | None = None,
    confidence: float | None = None,
    journal_id: str | None = None,
    take_profit_price: float | None = None,
    stop_loss_price: float | None = None,
    order_class: str = "simple",
    parent_order_id: str | None = None,
    portfolio: str = "quant",
) -> dict:
    """Record a trade.

    portfolio: which book the trade belongs to ("quant" = Quant Core systematic
    strategy, "conviction" = concentrated cyclical book). Defaults to "quant".
    """
    sb = get_supabase()
    row: dict = {
        "symbol": symbol,
        "side": side,
        "order_type": order_type,
        "quantity": quantity,
        "thesis": thesis,
        "confidence": confidence,
        "journal_id": journal_id,
        "order_class": order_class,
        "portfolio": portfolio,
    }
    if limit_price is not None:
        row["limit_price"] = limit_price
    if take_profit_price is not None:
        row["take_profit_price"] = take_profit_price
    if stop_loss_price is not None:
        row["stop_loss_price"] = stop_loss_price
    if parent_order_id is not None:
        row["parent_order_id"] = parent_order_id
    result = sb.table("trades").insert(row).execute()
    return result.data[0]


def update_trade(trade_id: str, updates: dict) -> dict:
    """Update trade with fill info or status."""
    sb = get_supabase()
    result = sb.table("trades").update(updates).eq("id", trade_id).execute()
    return result.data[0]


def get_trades(
    limit: int = 20,
    symbol: str | None = None,
    portfolio: str | None = None,
) -> list[dict]:
    """Get recent trades, optionally filtered by symbol and/or portfolio."""
    sb = get_supabase()
    query = sb.table("trades").select("*").order("created_at", desc=True).limit(limit)
    if symbol:
        query = query.eq("symbol", symbol)
    if portfolio:
        query = query.eq("portfolio", portfolio)
    result = query.execute()
    return result.data


# --- Watchlist ---

def get_watchlist() -> list[dict]:
    """Get all watchlist items."""
    sb = get_supabase()
    result = sb.table("watchlist").select("*").order("added_at", desc=True).execute()
    return result.data


def add_to_watchlist(
    symbol: str,
    thesis: str | None = None,
    target_entry: float | None = None,
    target_exit: float | None = None,
) -> dict:
    """Add or update a watchlist item."""
    sb = get_supabase()
    row: dict = {"symbol": symbol}
    if thesis is not None:
        row["thesis"] = thesis
    if target_entry is not None:
        row["target_entry"] = target_entry
    if target_exit is not None:
        row["target_exit"] = target_exit
    result = sb.table("watchlist").upsert(row, on_conflict="symbol").execute()
    return result.data[0]


def remove_from_watchlist(symbol: str) -> bool:
    """Remove a symbol from the watchlist."""
    sb = get_supabase()
    result = sb.table("watchlist").delete().eq("symbol", symbol).execute()
    return len(result.data) > 0


# --- Equity Snapshots ---

def record_equity_snapshot(
    snapshot_date: str,
    portfolio_equity: float,
    portfolio_cash: float,
    spy_close: float,
    portfolio: str = "quant",
) -> dict:
    """Record a daily equity snapshot for benchmark tracking.

    Each portfolio ("quant" = Quant Core, "conviction" = Conviction) keeps its
    own equity curve. Cumulative returns are computed from that portfolio's own
    inception snapshot.

    Alpha is only meaningful when >50% of portfolio is deployed.
    When mostly cash, alpha is stored as None to avoid misleading numbers.
    """
    sb = get_supabase()

    # Get this portfolio's inception snapshot to compute cumulative returns
    first = (
        sb.table("equity_snapshots")
        .select("portfolio_equity, spy_close")
        .eq("portfolio", portfolio)
        .order("snapshot_date")
        .limit(1)
        .execute()
    )

    deployed_pct = round(
        (portfolio_equity - portfolio_cash) / portfolio_equity * 100, 1
    ) if portfolio_equity > 0 else 0.0

    if first.data:
        inception_equity = float(first.data[0]["portfolio_equity"]) or 1
        inception_spy = float(first.data[0]["spy_close"]) or 1
        portfolio_return = round((portfolio_equity / inception_equity - 1) * 100, 4)
        spy_return = round((spy_close / inception_spy - 1) * 100, 4)
        # Alpha is only meaningful when >50% deployed
        alpha = round(portfolio_return - spy_return, 4) if deployed_pct > 50 else None
    else:
        # This IS the first snapshot
        portfolio_return = 0.0
        spy_return = 0.0
        alpha = None

    result = (
        sb.table("equity_snapshots")
        .upsert({
            "portfolio": portfolio,
            "snapshot_date": snapshot_date,
            "portfolio_equity": portfolio_equity,
            "portfolio_cash": portfolio_cash,
            "spy_close": spy_close,
            "portfolio_cumulative_return": portfolio_return,
            "spy_cumulative_return": spy_return,
            "alpha": alpha,
            "deployed_pct": deployed_pct,
        }, on_conflict="portfolio,snapshot_date")
        .execute()
    )
    return result.data[0]


def get_equity_snapshots(days: int = 30, portfolio: str = "quant") -> list[dict]:
    """Get recent equity snapshots for a portfolio (default Quant Core)."""
    try:
        sb = get_supabase()
        result = (
            sb.table("equity_snapshots")
            .select("*")
            .eq("portfolio", portfolio)
            .order("snapshot_date", desc=True)
            .limit(days)
            .execute()
        )
        return result.data if result else []
    except Exception:
        logger.warning("Failed to read equity snapshots")
        return []


# --- Risk Settings ---

def get_risk_settings() -> dict:
    """Get the singleton risk settings row."""
    try:
        sb = get_supabase()
        result = sb.table("risk_settings").select("*").limit(1).single().execute()
        return result.data if result else _default_risk_settings()
    except Exception:
        logger.warning("Failed to read risk settings, using defaults")
        return _default_risk_settings()


def _default_risk_settings() -> dict:
    return {
        "max_position_pct": 10.0,
        "max_daily_loss": 500.0,
        "max_total_exposure_pct": 80.0,
        "default_stop_loss_pct": 5.0,
    }
