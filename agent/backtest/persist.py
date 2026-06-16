"""Persist backtest results to Supabase."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from datetime import datetime

import pandas as pd

from stock_agent.factor_scoring import FactorVariant
from common.supabase_client import get_supabase

logger = logging.getLogger(__name__)


def _variant_to_jsonable(variant: FactorVariant) -> dict:
    """Convert a FactorVariant dataclass to a JSON-serializable dict."""
    d = asdict(variant)
    # lookbacks is list of tuples — convert to list of lists for JSON
    d["momentum_lookbacks"] = [list(lb) for lb in d["momentum_lookbacks"]]
    return d


def persist_run(
    variant: FactorVariant,
    rules_dict: dict,
    start: str,
    end: str,
    starting_equity: float,
    equity_curve: pd.Series,
    cash_curve: pd.Series,
    spy_curve: pd.Series,
    trades: list[dict],
    metrics: dict,
    notes: str | None = None,
) -> str:
    """Write a complete backtest run to Supabase. Returns run_id."""
    sb = get_supabase()

    # 1. Insert run header
    run_row = {
        "variant_name": variant.name,
        "variant_config": _variant_to_jsonable(variant),
        "start_date": start,
        "end_date": end,
        "starting_equity": starting_equity,
        "final_equity": float(equity_curve.iloc[-1]) if len(equity_curve) > 0 else None,
        "total_return_pct": metrics.get("total_return_pct"),
        "spy_return_pct": metrics.get("spy_return_pct"),
        "alpha_pct": metrics.get("alpha_pct"),
        "sharpe": metrics.get("sharpe"),
        "max_drawdown_pct": metrics.get("max_drawdown_pct"),
        "win_rate_pct": metrics.get("win_rate_pct"),
        "trade_count": metrics.get("trade_count"),
        "avg_hold_days": metrics.get("avg_hold_days"),
        "stop_hit_rate_pct": metrics.get("stop_hit_rate_pct"),
        "status": "completed",
        "notes": notes,
        "completed_at": datetime.utcnow().isoformat(),
    }
    result = sb.table("backtest_runs").insert(run_row).execute()
    run_id = result.data[0]["id"]
    logger.info("Created backtest_runs row: %s", run_id)

    # 2. Snapshots — batch insert
    snapshot_rows = []
    for i, date in enumerate(equity_curve.index):
        equity = float(equity_curve.iloc[i])
        cash = float(cash_curve.iloc[i]) if i < len(cash_curve) else 0.0
        spy_close = float(spy_curve.get(date)) if date in spy_curve.index else None
        snapshot_rows.append({
            "run_id": run_id,
            "snapshot_date": date.date().isoformat(),
            "equity": equity,
            "cash": cash,
            "positions_value": equity - cash,
            "spy_close": spy_close,
            "portfolio_return_pct": round((equity / starting_equity - 1) * 100, 4),
            "spy_return_pct": (
                round((spy_close / float(spy_curve.iloc[0]) - 1) * 100, 4)
                if spy_close is not None and len(spy_curve) > 0
                else None
            ),
            "deployed_pct": round((equity - cash) / equity * 100, 2) if equity > 0 else 0.0,
        })
    # Batch insert in chunks of 500 to avoid payload size issues
    for chunk_start in range(0, len(snapshot_rows), 500):
        chunk = snapshot_rows[chunk_start:chunk_start + 500]
        sb.table("backtest_snapshots").insert(chunk).execute()
    logger.info("Persisted %d snapshots", len(snapshot_rows))

    # 3. Trades
    if trades:
        trade_rows = [
            {
                "run_id": run_id,
                "symbol": t["symbol"],
                "side": t["side"],
                "trade_date": t["trade_date"],
                "price": t["price"],
                "quantity": t["quantity"],
                "composite_score": t.get("composite_score"),
                "exit_reason": t.get("exit_reason"),
                "pnl": t.get("pnl"),
                "holding_days": t.get("holding_days"),
            }
            for t in trades
        ]
        for chunk_start in range(0, len(trade_rows), 500):
            chunk = trade_rows[chunk_start:chunk_start + 500]
            sb.table("backtest_trades").insert(chunk).execute()
        logger.info("Persisted %d trades", len(trade_rows))

    return run_id
