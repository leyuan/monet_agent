"""Pure operation-success logic: the operation registry, the read-only allowlist, and the
trace × DB classification. No I/O — every function takes plain dicts (the trace tool call +
the DB rows the I/O layer fetched) so it unit-tests without LangSmith or Supabase.
"""

import re

# Operations the trader can perform, and how to verify each one's durable effect landed.
#   kind="db"        : a row should appear/change in `table`; matched by `match`.
#       match.src    : "output" (the tool's return payload) or "input" (its call args)
#       match.field  : key in that payload holding the identifier
#       match.col    : the DB column to match it against
#       verify       : which landing rule classify_operation applies (see VERIFY_RULES)
#       critical     : a silent failure here is a `fail` (else `warn`)
#   kind="trace_only": no clean DB row (external / conditional multi-write) — judged from
#                      the tool's own output (error flag / reported failure).
OPERATION_SPECS: dict[str, dict] = {
    # --- db-backed -----------------------------------------------------------
    "place_order": {"kind": "db", "verify": "order_status", "table": "trades",
                    "match": {"src": "output", "field": "trade_id", "col": "id"},
                    "critical": True, "expected_fail_prefix": "Risk check failed"},
    "cancel_order": {"kind": "db", "verify": "order_cancelled", "table": "trades",
                     "match": {"src": "output", "field": "trade_id", "col": "id"}},
    "write_journal_entry": {"kind": "db", "verify": "row_exists", "table": "agent_journal",
                            "match": {"src": "output", "field": "journal_id", "col": "id"}},
    "write_agent_memory": {"kind": "db", "verify": "fresh_memory", "table": "agent_memory",
                           "match": {"src": "output", "field": "key", "col": "key"}},
    "update_market_regime": {"kind": "db", "verify": "fresh_memory", "table": "agent_memory",
                             "match": {"src": "output", "field": "key", "col": "key"}},
    "record_decision": {"kind": "db", "verify": "fresh_memory", "table": "agent_memory",
                        "match": {"src": "output", "field": "key", "col": "key"}},
    "update_stock_analysis": {"kind": "db", "verify": "fresh_memory", "table": "agent_memory",
                              "match": {"src": "output", "field": "key", "col": "key"}},
    "manage_watchlist": {"kind": "db", "verify": "row_exists", "table": "watchlist",
                         "match": {"src": "input", "field": "symbol", "col": "symbol"}},
    "record_daily_snapshot": {"kind": "db", "verify": "snapshot", "table": "equity_snapshots",
                              "match": {"src": "output", "field": "date", "col": "snapshot_date"},
                              "critical": True},
    "audit_factor_ic": {"kind": "db", "verify": "fresh_memory", "table": "agent_memory",
                        "match": {"src": "const", "field": "strategy_health", "col": "key"}},
    "check_live_vs_backtest_divergence": {"kind": "db", "verify": "fresh_memory", "table": "agent_memory",
                                          "match": {"src": "const", "field": "strategy_divergence", "col": "key"}},
    # --- trace-only (external / conditional multi-write) ----------------------
    "attach_bracket_to_position": {"kind": "trace_only"},
    "reconcile_positions": {"kind": "trace_only"},
    "send_daily_recap": {"kind": "trace_only"},
    "send_daily_subscription_emails": {"kind": "trace_only"},
    "send_weekly_cycle_report": {"kind": "trace_only"},
}

CRITICAL_OPS = {t for t, s in OPERATION_SPECS.items() if s.get("critical")}

# Tools with no durable operation to verify here: pure reads, plus tools whose only write
# is an incidental cache/perf detail (score_universe → agent_memory.factor_cache) that is
# not a meaningful "did the operation land" signal. The complement of OPERATION_SPECS.
READ_ONLY_TOOLS: set[str] = {
    "internet_search", "get_stock_quote", "get_historical_data", "technical_analysis",
    "fundamental_analysis", "screen_stocks", "company_profile", "sector_analysis",
    "peer_comparison", "earnings_calendar", "eps_estimates", "market_breadth",
    "get_open_orders", "get_portfolio_state", "check_trade_risk", "read_agent_memory",
    "read_all_agent_memory", "query_database", "get_performance_comparison",
    "position_health_check", "check_watchlist_alerts", "score_universe",
    "enrich_eps_revisions", "generate_factor_rankings", "discover_catalysts",
    "get_earnings_results", "assess_ai_bubble_risk", "assess_ai_cycle_durability",
    "suggest_factor_weight_adjustment",
}


def _unwrap_output(outputs) -> dict:
    """LangSmith stores a tool's return under varying shapes. Normalize to the return dict:
    a bare {"output": <dict>} wrapper is unwrapped; anything non-dict becomes {}."""
    if isinstance(outputs, dict):
        if set(outputs.keys()) == {"output"} and isinstance(outputs["output"], dict):
            return outputs["output"]
        return outputs
    return {}


def extract_operations(run: dict) -> list[dict]:
    """Enumerate the run's operations from its trace. Reads are dropped; operations and
    unknown (unclassified) tools are returned for verification/surfacing."""
    ops = []
    for c in run.get("tool_calls", []):
        name = c.get("name")
        if name in READ_ONLY_TOOLS:
            continue
        spec = OPERATION_SPECS.get(name)
        bucket = spec["kind"] if spec else "unclassified"
        ops.append({
            "tool": name,
            "bucket": bucket,
            "inputs": c.get("inputs") or {},
            "output": _unwrap_output(c.get("outputs")),
            "error": c.get("error"),
        })
    return ops


_SAFE_VALUE = re.compile(r"^[A-Za-z0-9 :._\-]+$")  # ids, keys, symbols, dates — no quotes


def _match_value(op: dict, match: dict) -> str | None:
    """Resolve the identifier for the probe from the op's output / input / a constant."""
    if match["src"] == "const":
        return match["field"]
    # OPERATION_SPECS uses "input"/"output" as src, but op dict stores as "inputs"/"output"
    src_key = "inputs" if match["src"] == "input" else match["src"]
    payload = op.get(src_key) or {}
    return payload.get(match["field"])


def build_probe_sql(op: dict) -> str | None:
    """A single read-only SELECT to confirm the operation's row landed, or None when there
    is nothing safe to probe (trace-only/unclassified, missing identifier, unsafe value)."""
    spec = OPERATION_SPECS.get(op["tool"])
    if not spec or spec["kind"] != "db":
        return None
    match = spec["match"]
    value = _match_value(op, match)
    if not value or not _SAFE_VALUE.match(str(value)):
        return None
    return f"SELECT * FROM {spec['table']} WHERE {match['col']} = '{value}' LIMIT 5"
