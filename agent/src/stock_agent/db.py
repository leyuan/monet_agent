"""Database CRUD operations for agent state."""

import logging

from stock_agent.supabase_client import get_supabase

logger = logging.getLogger(__name__)


# --- Agent Memory ---

def read_memory(key: str) -> dict | None:
    """Read a memory entry by key."""
    sb = get_supabase()
    result = sb.table("agent_memory").select("*").eq("key", key).maybe_single().execute()
    return result.data


def read_all_memory() -> list[dict]:
    """Read all memory entries."""
    sb = get_supabase()
    result = sb.table("agent_memory").select("*").execute()
    return result.data


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
    sb = get_supabase()
    query = sb.table("agent_journal").select("*").order("created_at", desc=True).limit(limit)
    if entry_type:
        query = query.eq("entry_type", entry_type)
    if symbols:
        query = query.overlaps("symbols", symbols)
    result = query.execute()
    return result.data


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
) -> dict:
    """Record a trade."""
    sb = get_supabase()
    row: dict = {
        "symbol": symbol,
        "side": side,
        "order_type": order_type,
        "quantity": quantity,
        "thesis": thesis,
        "confidence": confidence,
        "journal_id": journal_id,
    }
    if limit_price is not None:
        row["limit_price"] = limit_price
    result = sb.table("trades").insert(row).execute()
    return result.data[0]


def update_trade(trade_id: str, updates: dict) -> dict:
    """Update trade with fill info or status."""
    sb = get_supabase()
    result = sb.table("trades").update(updates).eq("id", trade_id).execute()
    return result.data[0]


def get_trades(limit: int = 20, symbol: str | None = None) -> list[dict]:
    """Get recent trades."""
    sb = get_supabase()
    query = sb.table("trades").select("*").order("created_at", desc=True).limit(limit)
    if symbol:
        query = query.eq("symbol", symbol)
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


# --- Risk Settings ---

def get_risk_settings() -> dict:
    """Get the singleton risk settings row."""
    sb = get_supabase()
    result = sb.table("risk_settings").select("*").limit(1).single().execute()
    return result.data
