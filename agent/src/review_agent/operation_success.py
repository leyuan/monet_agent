"""Pure operation-success logic: the operation registry, the read-only allowlist, and the
trace × DB classification. No I/O — every function takes plain dicts (the trace tool call +
the DB rows the I/O layer fetched) so it unit-tests without LangSmith or Supabase.
"""

import re
from datetime import datetime

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
    "manage_watchlist": {"kind": "trace_only"},
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


_SEVERITY_ORDER = {"pass": 0, "info": 1, "warn": 2, "fail": 3}


def _result(op, status, severity, detail, evidence):
    return {"tool": op["tool"], "status": status, "severity": severity,
            "detail": detail, "evidence": evidence}


def _parse_dt(s):
    try:
        return datetime.fromisoformat(str(s))
    except (TypeError, ValueError):
        return None


def classify_operation(op: dict, rows: list[dict], run_start: str, probe_error: bool = False) -> dict:
    """Decide the operation's status + severity from its trace output and the probe rows.
    Pure: `rows` is whatever the DB probe returned ([] = none found / no probe).
    `probe_error` True = the DB query itself failed (bad column / outage)."""
    spec = OPERATION_SPECS.get(op["tool"], {"kind": "unclassified"})
    out = op.get("output") or {}

    # A failed probe can only ever be "couldn't check" — never a false silent_failure.
    if probe_error:
        return _result(op, "unverifiable", "info",
                       f"{op['tool']}: DB probe failed — cannot confirm landing.", {"output": out})

    # Unknown tool — surfaced, never silently dropped.
    if spec["kind"] == "unclassified":
        return _result(op, "unverifiable", "info",
                       f"{op['tool']} is not a known operation — registry may need updating.",
                       {"bucket": "unclassified"})

    # Trace-only: judged from the tool's own report (no DB row exists to check).
    if spec["kind"] == "trace_only":
        errs = out.get("errors")
        if op.get("error") or out.get("error"):
            return _result(op, "errored_unrecovered", "warn",
                           f"{op['tool']} errored: {op.get('error') or out.get('error')}", {"output": out})
        if errs:
            return _result(op, "partial", "warn", f"{op['tool']} reported errors: {errs}", {"output": out})
        return _result(op, "landed", "pass", f"{op['tool']} reported success.", {"output": out})

    # db-backed.
    critical = op["tool"] in CRITICAL_OPS
    verify = spec["verify"]

    # Guardrail rejection (place_order returns early before any DB write) = success.
    prefix = spec.get("expected_fail_prefix")
    if prefix and str(out.get("error", "")).startswith(prefix):
        return _result(op, "rejected_expected", "pass", out["error"], {"output": out})

    # No identifier to probe → honest unverifiable (never guess).
    if build_probe_sql(op) is None:
        return _result(op, "unverifiable", "info",
                       f"{op['tool']}: no identifier in trace output to verify landing.", {"output": out})

    if verify == "order_status":
        if not rows:
            sev = "fail" if critical else "warn"
            return _result(op, "silent_failure", sev,
                           "place_order returned a trade but no trades row landed.", {"output": out})
        status = str(rows[0].get("status", "")).lower()
        if "filled" in status and "partially" not in status:
            return _result(op, "landed", "pass", f"order {status}", {"row": rows[0]})
        if "partially_filled" in status:
            return _result(op, "partial", "warn", f"order {status}", {"row": rows[0]})
        if "rejected" in status or "canceled" in status or "cancelled" in status:
            return _result(op, "rejected_unexpected", "fail", f"order {status}", {"row": rows[0]})
        return _result(op, "unverifiable", "info", f"order pending/{status}", {"row": rows[0]})

    if verify == "order_cancelled":
        if rows and "cancel" in str(rows[0].get("status", "")).lower():
            return _result(op, "landed", "pass", "order cancelled", {"row": rows[0]})
        return _result(op, "silent_failure", "warn", "cancel did not land", {"output": out})

    if verify == "row_exists":
        if rows:
            return _result(op, "landed", "pass", f"{spec['table']} row present", {"row": rows[0]})
        return _result(op, "silent_failure", "warn",
                       f"{op['tool']} returned OK but no {spec['table']} row landed.", {"output": out})

    if verify == "fresh_memory":
        if not rows:
            return _result(op, "silent_failure", "warn",
                           f"{op['tool']}: no agent_memory row for the key.", {"output": out})
        row_dt, start_dt = _parse_dt(rows[0].get("updated_at")), _parse_dt(run_start)
        if row_dt and start_dt and row_dt < start_dt:
            return _result(op, "silent_failure", "warn",
                           "memory key exists but was not updated this run (stale).", {"row": rows[0]})
        return _result(op, "landed", "pass", "memory write landed", {"row": rows[0]})

    if verify == "snapshot":
        if not rows:
            sev = "fail" if critical else "warn"
            return _result(op, "silent_failure", sev, "no equity_snapshots row for the date.", {"output": out})
        row = rows[0]
        if not row.get("spy_close") or float(row.get("portfolio_equity") or 0) <= 0:
            return _result(op, "degraded", "warn",
                           "snapshot landed but content looks degraded (spy_close=0 or equity<=0).", {"row": row})
        return _result(op, "landed", "pass", "snapshot landed", {"row": row})

    return _result(op, "unverifiable", "info", f"no rule for verify={verify}", {"output": out})


def run_severity(classified: list[dict]) -> str:
    """The run verdict severity = the worst operation severity."""
    worst = "pass"
    for r in classified:
        if _SEVERITY_ORDER[r["severity"]] > _SEVERITY_ORDER[worst]:
            worst = r["severity"]
    return worst
