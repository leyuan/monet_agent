"""Memory + journal tools: structured beliefs, decisions, watchlist, regime, ad-hoc DB queries."""

import logging
from datetime import datetime
from typing import Literal

from stock_agent.db import (
    add_to_watchlist,
    get_watchlist,
    read_all_memory,
    read_memory,
    remove_from_watchlist,
    write_journal as db_write_journal,
    write_memory as db_write_memory,
)
from stock_agent.supabase_client import get_supabase

logger = logging.getLogger(__name__)

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



def read_all_agent_memory() -> dict:
    """Read all persistent memory entries at once.

    Use this at the start of each loop to load full context efficiently,
    instead of reading keys one at a time.

    Returns:
        Dict mapping memory keys to their values and timestamps.
    """
    rows = read_all_memory()
    return {
        "memories": {
            row["key"]: {"value": row["value"], "updated_at": row.get("updated_at")}
            for row in rows
        },
        "count": len(rows),
    }



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
    run_source: str | None = None,
) -> dict:
    """Write a journal entry recording the agent's activity or thoughts.

    Args:
        entry_type: Category of the entry.
        title: Brief title (keep under 80 characters).
        content: Full markdown content.
        symbols: Related ticker symbols.
        run_source: What triggered this run — e.g. "morning_research", "midday_analysis",
            "eod_execution", "weekend_research", "weekly_review", or "ad_hoc".

    Returns:
        The created journal entry.
    """
    metadata = {}
    if run_source:
        metadata["run_source"] = run_source
    result = db_write_journal(entry_type, title, content, symbols=symbols, metadata=metadata or None)
    return {"journal_id": result["id"], "status": "created"}



def update_market_regime(
    vix: float,
    breadth_pct: float,
    rotation_signal: str,
    regime_label: str,
    confidence: float,
) -> dict:
    """Update the structured market regime memory.

    Call this at the end of Step 1 (Market Health Check) in the trading loop
    to persist a typed snapshot of current market conditions.

    Args:
        vix: Current VIX level.
        breadth_pct: Percentage of stocks above 50-day SMA (from market_breadth).
        rotation_signal: "risk-on", "risk-off", or "mixed".
        regime_label: "healthy-bull", "broad-weakness", "transitional", or "risk-off".
        confidence: Your confidence in this regime assessment (0.0–1.0).

    Returns:
        Confirmation of the write.
    """
    value = {
        "vix": round(vix, 2),
        "breadth_pct": round(breadth_pct, 1),
        "rotation_signal": rotation_signal,
        "regime_label": regime_label,
        "confidence": round(confidence, 2),
        "as_of": datetime.now().strftime("%Y-%m-%d %I:%M %p"),
    }
    result = db_write_memory("market_regime", value)
    return {"key": "market_regime", "status": "saved", "value": value, "updated_at": result["updated_at"]}



def update_stock_analysis(
    symbol: str,
    thesis: str,
    target_entry: float,
    target_exit: float,
    confidence: float,
    bull_case: str | None = None,
    bear_case: str | None = None,
    fundamentals_score: float | None = None,
    status: str = "watching",
    composite_score: float | None = None,
    momentum_score: float | None = None,
    quality_score: float | None = None,
    value_score: float | None = None,
    eps_revision_score: float | None = None,
) -> dict:
    """Update structured analysis for a stock in memory and sync to watchlist.

    Call this after analysis to persist stock data. Works with both factor-based
    scoring (composite_score, momentum_score, etc.) and legacy subjective analysis.

    When factor scores are provided, thesis is auto-enhanced with score summary.

    Args:
        symbol: Stock ticker (e.g. "AAPL").
        thesis: Core investment thesis (1-2 sentences).
        target_entry: Price to buy at.
        target_exit: Price to take profit at.
        confidence: Conviction level (0.0–1.0) or composite_score/100.
        bull_case: Best-case scenario description.
        bear_case: Worst-case scenario description.
        fundamentals_score: Optional 0-10 fundamentals quality score.
        status: "watching", "buying", "holding", "exited".
        composite_score: Factor composite score (0-100).
        momentum_score: Momentum factor score (0-100).
        quality_score: Quality factor score (0-100).
        value_score: Value factor score (0-100).
        eps_revision_score: EPS revision factor score (0-100).

    Returns:
        Confirmation with the stored analysis.
    """
    # Read current market regime to tag when targets were set
    regime_mem = read_memory("market_regime")
    regime_when_set = None
    if regime_mem and isinstance(regime_mem.get("value"), dict):
        regime_when_set = regime_mem["value"].get("regime_label")

    now = datetime.now().strftime("%Y-%m-%d %I:%M %p")
    value = {
        "symbol": symbol.upper(),
        "thesis": thesis,
        "target_entry": round(target_entry, 2),
        "target_exit": round(target_exit, 2),
        "confidence": round(confidence, 2),
        "status": status,
        "target_set_date": datetime.now().strftime("%Y-%m-%d"),
        "regime_when_set": regime_when_set,
        "last_analyzed": now,
    }
    if bull_case:
        value["bull_case"] = bull_case
    if bear_case:
        value["bear_case"] = bear_case
    if fundamentals_score is not None:
        value["fundamentals_score"] = round(fundamentals_score, 1)

    # Factor scores
    if composite_score is not None:
        value["composite_score"] = round(composite_score, 1)
    if momentum_score is not None:
        value["momentum_score"] = round(momentum_score, 1)
    if quality_score is not None:
        value["quality_score"] = round(quality_score, 1)
    if value_score is not None:
        value["value_score"] = round(value_score, 1)
    if eps_revision_score is not None:
        value["eps_revision_score"] = round(eps_revision_score, 1)

    key = f"stock:{symbol.upper()}"
    result = db_write_memory(key, value)

    # Sync targets to watchlist table
    add_to_watchlist(
        symbol=symbol.upper(),
        thesis=thesis,
        target_entry=target_entry,
        target_exit=target_exit,
    )

    return {"key": key, "status": "saved", "value": value, "updated_at": result["updated_at"]}



def record_decision(
    symbol: str,
    action: str,
    reasoning: str,
    confidence: float,
    price: float,
) -> dict:
    """Record a trading decision (including WAITs) to structured memory.

    Call this in Step 7 of the trading loop for EVERY stock evaluated —
    not just trades, but also WAIT decisions. This creates an audit trail
    that reflection and weekly review can analyze.

    Args:
        symbol: Stock ticker.
        action: "BUY", "SELL", "LIMIT_ORDER", "WAIT", "DCA", "TRIM".
        reasoning: Why you made this decision (2-3 sentences).
        confidence: Confidence at time of decision (0.0–1.0).
        price: Current price at time of decision.

    Returns:
        Confirmation with the stored decision.
    """
    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    key = f"decision:{symbol.upper()}:{date_str}"

    value = {
        "symbol": symbol.upper(),
        "action": action.upper(),
        "reasoning": reasoning,
        "confidence": round(confidence, 2),
        "price_at_decision": round(price, 2),
        "executed": action.upper() in ("BUY", "SELL", "DCA", "TRIM", "LIMIT_ORDER"),
        "decided_at": now.strftime("%Y-%m-%d %I:%M %p"),
    }
    result = db_write_memory(key, value)
    return {"key": key, "status": "saved", "value": value, "updated_at": result["updated_at"]}



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
# Helpers
# ============================================================


def submit_user_insight(
    title: str,
    content: str,
    symbols: list[str] | None = None,
) -> dict:
    """Flag a substantive user observation for your autonomous self to consider.

    Use this when a user raises something genuinely interesting — a thesis
    challenge, a position concern, a sector rotation observation, or contrarian
    analysis. Do NOT use for casual questions or generic market chat.

    Args:
        title: Short summary of the insight (e.g. "Thesis challenge on NVDA margins").
        content: The full observation with reasoning.
        symbols: Optional list of related ticker symbols.

    Returns:
        Confirmation dict with the journal entry ID.
    """
    result = db_write_journal(
        entry_type="user_insight",
        title=title,
        content=content,
        symbols=symbols,
        metadata={"source": "chat"},
    )
    return {"status": "submitted", "journal_id": result.get("id")}


