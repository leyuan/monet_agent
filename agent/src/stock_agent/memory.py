"""Persistent memory interface for the agent's beliefs and state."""

from stock_agent.db import read_memory, write_memory, read_all_memory, read_journal


def load_agent_context() -> str:
    """Load the agent's persistent context for chat mode.

    Returns a markdown string with market outlook, recent journal, and core beliefs.
    """
    sections = []

    # Core beliefs
    outlook = read_memory("market_outlook")
    if outlook:
        sections.append(f"## Current Market Outlook\n{_format_value(outlook['value'])}")

    strategy = read_memory("strategy")
    if strategy:
        sections.append(f"## Trading Strategy\n{_format_value(strategy['value'])}")

    risk_appetite = read_memory("risk_appetite")
    if risk_appetite:
        sections.append(f"## Risk Appetite\n{_format_value(risk_appetite['value'])}")

    # Recent journal entries
    recent = read_journal(limit=5)
    if recent:
        entries = []
        for j in recent:
            entries.append(f"- **[{j['entry_type']}]** {j['title']} ({j['created_at'][:10]})")
        sections.append("## Recent Activity\n" + "\n".join(entries))

    # Watchlist rationale
    all_mem = read_all_memory()
    watchlist_mems = [m for m in all_mem if m["key"].startswith("watchlist_rationale_")]
    if watchlist_mems:
        items = []
        for m in watchlist_mems:
            symbol = m["key"].replace("watchlist_rationale_", "")
            items.append(f"- **{symbol}**: {_format_value(m['value'])}")
        sections.append("## Watchlist Rationale\n" + "\n".join(items))

    if not sections:
        return "No persistent memory yet. This is a fresh start."

    return "\n\n".join(sections)


def _format_value(value: dict | str) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        if "summary" in value:
            return str(value["summary"])
        return str(value)
    return str(value)
