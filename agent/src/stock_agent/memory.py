"""Persistent memory interface for the agent's beliefs and state."""

from stock_agent.db import read_memory, write_memory, read_all_memory, read_journal


def load_agent_context() -> str:
    """Load the agent's persistent context for chat mode.

    Returns a markdown string with market regime, stock analyses, recent decisions,
    and core beliefs. Reads structured memory (stock:*, decision:*, market_regime)
    and falls back to legacy keys gracefully.
    """
    try:
        return _load_agent_context_inner()
    except Exception:
        return "No persistent memory yet. This is a fresh start."


def _load_agent_context_inner() -> str:
    sections = []
    all_mem = read_all_memory()
    mem_by_key = {m["key"]: m for m in all_mem}

    # --- Market Regime (structured) ---
    regime_mem = mem_by_key.get("market_regime")
    if regime_mem:
        v = regime_mem["value"]
        if isinstance(v, dict) and "regime_label" in v:
            regime_line = (
                f"VIX: {v.get('vix', '?')} | "
                f"Breadth: {v.get('breadth_pct', '?')}% | "
                f"Regime: {v.get('regime_label', '?')} | "
                f"Rotation: {v.get('rotation_signal', '?')} | "
                f"Confidence: {v.get('confidence', '?')} "
                f"(as of {v.get('as_of', '?')})"
            )
            sections.append(f"## Market Regime\n{regime_line}")
        else:
            sections.append(f"## Market Regime\n{_format_value(v)}")
    else:
        # Legacy fallback
        outlook = mem_by_key.get("market_outlook")
        if outlook:
            sections.append(f"## Current Market Outlook\n{_format_value(outlook['value'])}")

    # --- Core beliefs ---
    strategy = mem_by_key.get("strategy")
    if strategy:
        sections.append(f"## Trading Strategy\n{_format_value(strategy['value'])}")

    risk_appetite = mem_by_key.get("risk_appetite")
    if risk_appetite:
        sections.append(f"## Risk Appetite\n{_format_value(risk_appetite['value'])}")

    # --- Factor Rankings (latest snapshot) ---
    factor_mem = mem_by_key.get("factor_rankings")
    if factor_mem and isinstance(factor_mem.get("value"), dict):
        fv = factor_mem["value"]
        scored_at = fv.get("scored_at", "?")
        rankings = fv.get("top_10", fv.get("rankings", []))[:10]
        if rankings:
            lines = [f"Scored at: {scored_at} | Weights: {fv.get('factor_weights', {})}"]
            for r in rankings:
                lines.append(
                    f"  #{r.get('rank', '?')} {r.get('symbol', '?')} "
                    f"(C:{r.get('composite_score', '?')} M:{r.get('momentum_score', '?')} "
                    f"Q:{r.get('quality_score', '?')} V:{r.get('value_score', '?')} "
                    f"E:{r.get('eps_revision_score', '?')})"
                )
            sections.append("## Factor Rankings\n" + "\n".join(lines))

    # --- Factor Weights ---
    fw_mem = mem_by_key.get("factor_weights")
    if fw_mem and isinstance(fw_mem.get("value"), dict):
        fw = fw_mem["value"]
        sections.append(
            f"## Factor Weights\n"
            f"Momentum: {fw.get('momentum', 0.35)} | Quality: {fw.get('quality', 0.30)} | "
            f"Value: {fw.get('value', 0.20)} | EPS Revision: {fw.get('eps_revision', 0.15)}"
        )

    # --- Stock Analyses (structured: stock:* keys) ---
    stock_mems = sorted(
        [m for m in all_mem if m["key"].startswith("stock:")],
        key=lambda m: m.get("updated_at", ""),
        reverse=True,
    )
    if stock_mems:
        items = []
        for m in stock_mems:
            v = m["value"]
            if isinstance(v, dict):
                symbol = v.get("symbol", m["key"].replace("stock:", ""))
                conf = v.get("confidence", "?")
                last = v.get("last_analyzed", m.get("updated_at", "?"))
                if isinstance(last, str) and len(last) > 10:
                    last = last[:10]
                thesis = v.get("thesis", "No thesis")
                entry = v.get("target_entry", "?")
                exit_ = v.get("target_exit", "?")
                status = v.get("status", "watching")
                # Include factor scores if present
                composite = v.get("composite_score")
                factor_line = ""
                if composite is not None:
                    factor_line = (
                        f" | Composite: {composite}"
                        f" M:{v.get('momentum_score', '?')}"
                        f" Q:{v.get('quality_score', '?')}"
                        f" V:{v.get('value_score', '?')}"
                        f" E:{v.get('eps_revision_score', '?')}"
                    )
                items.append(
                    f"### {symbol} (confidence: {conf}, last: {last})\n"
                    f"Thesis: {thesis} | Entry: ${entry} | Exit: ${exit_} | Status: {status}{factor_line}"
                )
            else:
                items.append(f"### {m['key'].replace('stock:', '')}\n{_format_value(v)}")
        sections.append("## Stock Analyses\n" + "\n\n".join(items))
    else:
        # Legacy fallback: watchlist_rationale_* keys
        watchlist_mems = [m for m in all_mem if m["key"].startswith("watchlist_rationale_")]
        if watchlist_mems:
            items = []
            for m in watchlist_mems:
                symbol = m["key"].replace("watchlist_rationale_", "")
                items.append(f"- **{symbol}**: {_format_value(m['value'])}")
            sections.append("## Watchlist Rationale\n" + "\n".join(items))

    # --- Recent Decisions (decision:* keys, last 7 days) ---
    from datetime import datetime, timedelta
    cutoff = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    decision_mems = sorted(
        [m for m in all_mem if m["key"].startswith("decision:")],
        key=lambda m: m.get("updated_at", ""),
        reverse=True,
    )
    if decision_mems:
        items = []
        for m in decision_mems:
            v = m["value"]
            if isinstance(v, dict):
                decided = v.get("decided_at", "")
                # Only show decisions from last 7 days
                if isinstance(decided, str) and decided[:10] < cutoff:
                    continue
                symbol = v.get("symbol", "?")
                action = v.get("action", "?")
                conf = v.get("confidence", "?")
                price = v.get("price_at_decision", "?")
                reasoning = v.get("reasoning", "")
                # Truncate reasoning for context display
                short_reason = reasoning[:80] + "..." if len(reasoning) > 80 else reasoning
                items.append(f"- {decided[:10] if decided else '?'} {symbol}: {action} ({conf}) @ ${price} — {short_reason}")
            if len(items) >= 15:
                break
        if items:
            sections.append("## Recent Decisions\n" + "\n".join(items))

    # --- Performance vs Benchmark ---
    try:
        from stock_agent.db import get_equity_snapshots
        snapshots = get_equity_snapshots(days=7)
        if snapshots:
            latest = snapshots[0]  # newest first
            port_ret = latest.get("portfolio_cumulative_return", 0)
            spy_ret = latest.get("spy_cumulative_return", 0)
            alpha = latest.get("alpha", 0)
            sections.append(
                f"## Performance vs Benchmark\n"
                f"Portfolio: {port_ret:+.2f}% | SPY: {spy_ret:+.2f}% | Alpha: {alpha:+.2f}% "
                f"(as of {latest.get('snapshot_date', '?')})"
            )
    except Exception:
        pass  # No snapshots yet, skip

    # --- Recent journal entries ---
    recent = read_journal(limit=5)
    if recent:
        entries = []
        for j in recent:
            entries.append(f"- **[{j['entry_type']}]** {j['title']} ({j['created_at'][:10]})")
        sections.append("## Recent Activity\n" + "\n".join(entries))

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
