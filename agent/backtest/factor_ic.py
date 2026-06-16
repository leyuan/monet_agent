"""Factor IC (Information Coefficient) analysis.

Measures the rank correlation between factor scores computed on date T and
actual forward returns over the next N trading days. Run across many historical
dates, average the correlations, and compute a t-statistic.

Interpretation:
    IC ~ 0.00: factor has no predictive power (random)
    IC ~ 0.02: weak but real signal (~5-10% annualized alpha before costs)
    IC ~ 0.05: strong signal
    IC ~ 0.10: exceptional (rare in public markets)

The t-statistic matters more than a single IC reading:
    |t| > 2 with 50+ observations → statistically significant

This tells you WHICH factors are predictive AT WHICH horizons — critical for
diagnosing issues like "momentum is great at 60d but useless at 5d."
"""

from __future__ import annotations

import argparse
import logging
from datetime import datetime, timedelta

from dotenv import load_dotenv
load_dotenv()

import numpy as np
import pandas as pd

from stock_agent.factor_scoring import (
    BASELINE_VARIANT,
    FactorVariant,
    compute_factor_scores,
    compute_momentum,
    compute_quality,
    compute_value,
)
from common.supabase_client import get_supabase

from backtest.data import load_fundamentals, load_prices
from backtest.variants import VARIANTS, get_variant

logger = logging.getLogger(__name__)

FORWARD_HORIZONS = [5, 10, 20, 60]  # trading days


def _forward_returns(
    close: pd.DataFrame,
    base_date: pd.Timestamp,
    horizon_days: int,
) -> pd.Series:
    """Returns from base_date to base_date + horizon_days (trading days).

    Uses iloc offsets based on base_date's row position.
    """
    if base_date not in close.index:
        return pd.Series(dtype=float)

    base_pos = close.index.get_loc(base_date)
    target_pos = base_pos + horizon_days
    if target_pos >= len(close):
        return pd.Series(dtype=float)

    base_prices = close.iloc[base_pos]
    target_prices = close.iloc[target_pos]
    ret = (target_prices / base_prices - 1).dropna()
    return ret


def _rank_corr(a: pd.Series, b: pd.Series) -> float:
    """Spearman rank correlation between two series on their common index.

    Implemented as Pearson on ranks to avoid scipy dependency.
    """
    common = a.index.intersection(b.index)
    if len(common) < 10:
        return np.nan
    a_ranks = a.loc[common].rank()
    b_ranks = b.loc[common].rank()
    return float(a_ranks.corr(b_ranks))


def compute_ic(
    variant: FactorVariant,
    close: pd.DataFrame,
    fundamentals: dict[str, dict],
    start: str,
    end: str,
    sample_every_n_days: int = 5,
) -> dict[str, dict[int, dict]]:
    """Compute IC for each factor at each forward horizon.

    Samples every N trading days to avoid redundant computation (consecutive
    days are highly correlated). N=5 means weekly samples.

    Returns:
        nested dict: {factor_name: {horizon_days: {mean, std, tstat, n}}}
    """
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)

    # Need at least max(horizon) days of forward data
    max_horizon = max(FORWARD_HORIZONS)
    # Need at least max(lookback) days of backward data for momentum
    max_lookback = max(lb + skip for lb, skip in variant.momentum_lookbacks) + 10

    eligible_dates = close.index[
        (close.index >= start_ts)
        & (close.index <= end_ts)
    ]

    # Filter to dates that have enough history and enough forward returns
    sampled_dates = []
    for i, d in enumerate(eligible_dates):
        pos = close.index.get_loc(d)
        if pos < max_lookback:
            continue
        if pos + max_horizon >= len(close):
            continue
        if i % sample_every_n_days != 0:
            continue
        sampled_dates.append(d)

    logger.info("IC sampling %d dates (every %dth day)", len(sampled_dates), sample_every_n_days)

    # Collect IC samples per factor × horizon
    factor_names = ["momentum", "quality", "value", "composite"]
    samples: dict[str, dict[int, list[float]]] = {
        f: {h: [] for h in FORWARD_HORIZONS} for f in factor_names
    }

    for idx, base_date in enumerate(sampled_dates):
        if idx % 10 == 0:
            logger.info("  IC date %d/%d: %s", idx + 1, len(sampled_dates), base_date.date())

        # Slice price history up to base_date (no look-ahead)
        historical = close.loc[:base_date]

        # Compute factor scores as if it were base_date
        mom = compute_momentum(historical, variant)
        if len(mom) == 0:
            continue

        # Use all symbols for IC (no pre-filter, so every stock gets scored)
        candidates = mom.index.tolist()
        cand_fund = {s: fundamentals[s] for s in candidates if s in fundamentals}

        qual = compute_quality(cand_fund) if cand_fund else pd.Series(dtype=float)
        val = compute_value(cand_fund) if cand_fund else pd.Series(dtype=float)

        # Composite using default weights
        default_weights = {"momentum": 0.35, "quality": 0.30, "value": 0.20, "eps_revision": 0.15}
        composite_dict: dict[str, float] = {}
        for sym in cand_fund:
            m = float(mom.get(sym, 50.0))
            q = float(qual.get(sym, 50.0))
            v = float(val.get(sym, 50.0))
            composite_dict[sym] = (
                default_weights["momentum"] * m
                + default_weights["quality"] * q
                + default_weights["value"] * v
                + default_weights["eps_revision"] * 50.0  # neutral for EPS (not available historically)
            )
        composite = pd.Series(composite_dict)

        factor_series = {
            "momentum": mom,
            "quality": qual,
            "value": val,
            "composite": composite,
        }

        # For each horizon, compute forward returns and correlation
        for h in FORWARD_HORIZONS:
            fwd_ret = _forward_returns(close, base_date, h)
            if len(fwd_ret) == 0:
                continue
            for factor_name, factor_scores in factor_series.items():
                if len(factor_scores) == 0:
                    continue
                ic = _rank_corr(factor_scores, fwd_ret)
                if not np.isnan(ic):
                    samples[factor_name][h].append(ic)

    # Aggregate: mean, std, t-stat
    results: dict[str, dict[int, dict]] = {}
    for factor_name in factor_names:
        results[factor_name] = {}
        for h in FORWARD_HORIZONS:
            vals = samples[factor_name][h]
            n = len(vals)
            if n < 5:
                results[factor_name][h] = {"mean": np.nan, "std": np.nan, "tstat": np.nan, "n": n}
                continue
            mean = float(np.mean(vals))
            std = float(np.std(vals, ddof=1))
            tstat = float(mean / (std / np.sqrt(n))) if std > 0 else 0.0
            results[factor_name][h] = {
                "mean": round(mean, 5),
                "std": round(std, 5),
                "tstat": round(tstat, 4),
                "n": n,
            }

    return results


def persist_ic_results(
    variant_name: str,
    results: dict,
    start: str,
    end: str,
) -> None:
    """Write IC results to Supabase factor_ic_runs table."""
    sb = get_supabase()
    rows = []
    for factor_name, horizons in results.items():
        for h, stats in horizons.items():
            if np.isnan(stats["mean"]):
                continue
            rows.append({
                "variant_name": variant_name,
                "factor_name": factor_name,
                "forward_horizon_days": h,
                "start_date": start,
                "end_date": end,
                "ic_mean": stats["mean"],
                "ic_std": stats["std"],
                "ic_tstat": stats["tstat"],
                "sample_size": stats["n"],
            })
    if rows:
        sb.table("factor_ic_runs").insert(rows).execute()
        logger.info("Persisted %d IC rows to Supabase", len(rows))


def print_ic_table(variant_name: str, results: dict) -> None:
    """Pretty-print IC results as a text table."""
    print(f"\n═══ Factor IC — variant: {variant_name} ═══")
    print(f"{'Factor':<12} " + " ".join(f"{h:>10}d" for h in FORWARD_HORIZONS))
    print("─" * (12 + 11 * len(FORWARD_HORIZONS)))
    for factor, horizons in results.items():
        row = f"{factor:<12} "
        for h in FORWARD_HORIZONS:
            stats = horizons.get(h, {})
            mean = stats.get("mean", float("nan"))
            tstat = stats.get("tstat", float("nan"))
            if np.isnan(mean):
                row += f"{'—':>11} "
            else:
                marker = "*" if abs(tstat) >= 2 else " "
                row += f"{mean:+.4f}{marker:<2}"
                if len(row) < 14 + 12 * FORWARD_HORIZONS.index(h) + 12:
                    row += " "
        print(row)
    print("\n* = |t-stat| >= 2 (statistically significant)")
    print()


def main() -> None:
    """CLI entry point: python -m backtest.factor_ic --variant baseline"""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    parser = argparse.ArgumentParser(description="Run factor IC analysis")
    parser.add_argument("--variant", default="baseline",
                        choices=list(VARIANTS.keys()) + ["all"],
                        help="Variant to test (or 'all')")
    parser.add_argument("--start", default=None, help="Backtest start (YYYY-MM-DD). Default: 1 year ago.")
    parser.add_argument("--end", default=None, help="Backtest end (YYYY-MM-DD). Default: today.")
    parser.add_argument("--sample-every", type=int, default=5,
                        help="Sample every Nth trading day (default: 5 = weekly)")
    parser.add_argument("--no-persist", action="store_true",
                        help="Skip Supabase persistence (print only)")
    parser.add_argument("--force-refresh", action="store_true",
                        help="Re-download data ignoring cache")
    args = parser.parse_args()

    today = datetime.now().date()
    end = args.end or today.isoformat()
    start = args.start or (today - timedelta(days=400)).isoformat()

    # Need extra history BEFORE the backtest window for momentum lookback (~12m)
    data_start = (datetime.fromisoformat(start) - timedelta(days=400)).date().isoformat()

    logger.info("Loading prices: %s → %s", data_start, end)
    close = load_prices(data_start, end, force_refresh=args.force_refresh)

    logger.info("Loading fundamentals")
    fundamentals = load_fundamentals(force_refresh=args.force_refresh)

    variants_to_run = list(VARIANTS.values()) if args.variant == "all" else [get_variant(args.variant)]

    for variant in variants_to_run:
        logger.info("Computing IC for variant: %s", variant.name)
        results = compute_ic(
            variant=variant,
            close=close,
            fundamentals=fundamentals,
            start=start,
            end=end,
            sample_every_n_days=args.sample_every,
        )
        print_ic_table(variant.name, results)
        if not args.no_persist:
            try:
                persist_ic_results(variant.name, results, start, end)
            except Exception as e:
                logger.error("Persist failed: %s", e)


if __name__ == "__main__":
    main()
