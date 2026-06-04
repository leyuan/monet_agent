"""Tier-1 strategy health monitoring: factor IC audit, live-vs-backtest divergence, weight-adjustment suggestions."""

import logging
from datetime import datetime, timedelta

import pandas as pd
import yfinance as yf

from stock_agent.market_data import get_sp500_sp400_tickers
from stock_agent.supabase_client import get_supabase
from stock_agent.tools._shared import _load_factor_weights

logger = logging.getLogger(__name__)

def audit_factor_ic(months_back: int = 3, sample_every_n_days: int = 7) -> dict:
    """Run factor IC analysis on recent market data, detect drift vs prior audits.

    This is the **weekly IC audit** — the early-warning system for strategy
    degradation. Measures whether the live factor system is still predictive
    and flags regime changes before they show up in live P&L.

    Pipeline:
    1. Download 1Y of prices for full S&P 500 + S&P 400 universe
    2. Fetch fundamentals for top 300 stocks by momentum (bounded for speed)
    3. Compute IC for {momentum, quality, value, composite} at 5/10/20/60d horizons
    4. Persist to factor_ic_runs with variant_name="live_audit"
    5. Compare to prior audit (most recent live_audit row per factor/horizon)
    6. Flag drift: sign flip, significance drop, composite below zero

    Typical runtime: 3-5 minutes (one-time-per-week cost).

    Args:
        months_back: How far back to compute IC (default 3 months — balances
            sample size with recency). Shorter = more reactive to regime changes.
        sample_every_n_days: Sample frequency (default 7 = weekly). Smaller = more
            samples, slower, more precise.

    Returns:
        Dict with current IC, drift flags, and delta vs prior audit.
    """
    import yfinance as yf
    from ..factor_scoring import (
        BASELINE_VARIANT,
        compute_momentum,
        compute_quality,
        compute_value,
    )

    result: dict = {
        "variant": BASELINE_VARIANT.name,
        "months_back": months_back,
        "as_of": datetime.now().isoformat(),
    }

    # Step 1: Prices
    try:
        tickers = get_sp500_sp400_tickers()
        if not tickers:
            return {"error": "Could not fetch ticker universe"}
        # Need lookback window BEFORE sample window for momentum
        max_lookback = max(lb + skip for lb, skip in BASELINE_VARIANT.momentum_lookbacks) + 10
        data_start = (datetime.now() - timedelta(days=months_back * 31 + max_lookback * 2)).strftime("%Y-%m-%d")
        end = datetime.now().strftime("%Y-%m-%d")
        price_data = yf.download(tickers, start=data_start, end=end, progress=False, threads=True, auto_adjust=True)
        close = price_data["Close"].dropna(axis=1, how="all")
    except Exception as e:
        logger.error("audit_factor_ic: price download failed: %s", e)
        return {"error": f"Price download failed: {e}"}

    # Step 2: Top-300 fundamentals (bounded for tractable weekly runtime)
    try:
        mom_full = compute_momentum(close, BASELINE_VARIANT)
        top_300 = mom_full.nlargest(300).index.tolist() if len(mom_full) >= 300 else mom_full.index.tolist()
    except Exception as e:
        return {"error": f"Momentum computation failed: {e}"}

    fundamentals: dict[str, dict] = {}
    for sym in top_300:
        try:
            info = yf.Ticker(sym).info
            fundamentals[sym] = {
                "sector": info.get("sector", "Unknown"),
                "forward_pe": info.get("forwardPE"),
                "profit_margin": info.get("profitMargins"),
                "roe": info.get("returnOnEquity"),
                "debt_to_equity": info.get("debtToEquity"),
            }
        except Exception:
            continue

    if not fundamentals:
        return {"error": "No fundamentals retrieved"}

    # Step 3: Sample dates in the audit window + compute IC
    sample_start = (datetime.now() - timedelta(days=months_back * 31)).date()
    horizons = [5, 10, 20, 60]
    max_horizon = max(horizons)

    sample_dates = []
    for i, d in enumerate(close.index):
        if d.date() < sample_start:
            continue
        pos = close.index.get_loc(d)
        if pos < max_lookback:
            continue
        if pos + max_horizon >= len(close):
            continue
        if i % sample_every_n_days != 0:
            continue
        sample_dates.append(d)

    if len(sample_dates) < 3:
        return {"error": f"Only {len(sample_dates)} sample dates — need more history"}

    factor_names = ["momentum", "quality", "value", "composite"]
    samples: dict[str, dict[int, list]] = {f: {h: [] for h in horizons} for f in factor_names}
    default_weights = _load_factor_weights()

    for base_date in sample_dates:
        historical = close.loc[:base_date]
        mom = compute_momentum(historical, BASELINE_VARIANT)
        if len(mom) == 0:
            continue
        cand_fund = {s: fundamentals[s] for s in mom.index if s in fundamentals}
        qual = compute_quality(cand_fund) if cand_fund else pd.Series(dtype=float)
        val = compute_value(cand_fund) if cand_fund else pd.Series(dtype=float)

        composite_dict = {}
        for sym in cand_fund:
            m = float(mom.get(sym, 50.0))
            q = float(qual.get(sym, 50.0))
            v = float(val.get(sym, 50.0))
            composite_dict[sym] = (
                default_weights["momentum"] * m
                + default_weights["quality"] * q
                + default_weights["value"] * v
                + default_weights["eps_revision"] * 50.0
            )
        composite = pd.Series(composite_dict)

        factor_series = {"momentum": mom, "quality": qual, "value": val, "composite": composite}

        base_pos = close.index.get_loc(base_date)
        for h in horizons:
            target_pos = base_pos + h
            if target_pos >= len(close):
                continue
            fwd_ret = (close.iloc[target_pos] / close.iloc[base_pos] - 1).dropna()
            for fname, fscores in factor_series.items():
                if len(fscores) == 0:
                    continue
                common = fscores.index.intersection(fwd_ret.index)
                if len(common) < 10:
                    continue
                ic = float(fscores.loc[common].rank().corr(fwd_ret.loc[common].rank()))
                if not pd.isna(ic):
                    samples[fname][h].append(ic)

    # Aggregate
    import numpy as np
    current_ic: dict = {}
    for fname in factor_names:
        current_ic[fname] = {}
        for h in horizons:
            vals = samples[fname][h]
            n = len(vals)
            if n < 3:
                current_ic[fname][h] = {"mean": None, "tstat": None, "n": n}
                continue
            mean = float(np.mean(vals))
            std = float(np.std(vals, ddof=1))
            tstat = float(mean / (std / np.sqrt(n))) if std > 0 else 0.0
            current_ic[fname][h] = {
                "mean": round(mean, 5),
                "tstat": round(tstat, 4),
                "n": n,
            }

    # Step 4: Persist + compare to prior
    sb = get_supabase()
    rows = []
    for fname in factor_names:
        for h in horizons:
            stats = current_ic[fname][h]
            if stats["mean"] is None:
                continue
            rows.append({
                "variant_name": "live_audit",
                "factor_name": fname,
                "forward_horizon_days": h,
                "start_date": sample_start.isoformat(),
                "end_date": datetime.now().date().isoformat(),
                "ic_mean": stats["mean"],
                "ic_std": None,
                "ic_tstat": stats["tstat"],
                "sample_size": stats["n"],
            })

    if rows:
        try:
            sb.table("factor_ic_runs").insert(rows).execute()
        except Exception as e:
            logger.warning("Failed to persist IC audit: %s", e)

    # Step 5: Compare to prior audit
    drift_flags: list[str] = []
    deltas: dict = {}
    try:
        prior = (
            sb.table("factor_ic_runs")
            .select("factor_name, forward_horizon_days, ic_mean, ic_tstat, created_at")
            .eq("variant_name", "live_audit")
            .order("created_at", desc=True)
            .limit(100)
            .execute()
        )
        # Find the most recent row BEFORE the one we just wrote (per factor/horizon)
        seen_current = False
        prior_map: dict[tuple[str, int], dict] = {}
        for row in prior.data or []:
            key = (row["factor_name"], row["forward_horizon_days"])
            # Skip rows we just wrote (same day)
            if row["created_at"][:10] == datetime.now().date().isoformat() and not seen_current:
                continue
            if key not in prior_map:
                prior_map[key] = row

        for fname in factor_names:
            for h in horizons:
                stats = current_ic[fname][h]
                if stats["mean"] is None:
                    continue
                prev = prior_map.get((fname, h))
                if not prev or prev.get("ic_mean") is None:
                    continue
                curr = stats["mean"]
                prev_val = float(prev["ic_mean"])
                delta = round(curr - prev_val, 5)
                deltas.setdefault(fname, {})[h] = {"prev": prev_val, "curr": curr, "delta": delta}

                # Drift rules
                if prev_val > 0 and curr < 0:
                    drift_flags.append(f"SIGN FLIP: {fname}@{h}d went {prev_val:+.3f} → {curr:+.3f}")
                elif prev_val < 0 and curr > 0:
                    drift_flags.append(f"SIGN FLIP (recovery): {fname}@{h}d went {prev_val:+.3f} → {curr:+.3f}")
                elif abs(prev_val) >= 0.03 and abs(curr) < 0.01:
                    drift_flags.append(f"SIGNIFICANCE LOSS: {fname}@{h}d IC collapsed from {prev_val:+.3f} → {curr:+.3f}")
    except Exception as e:
        logger.warning("Prior IC comparison failed: %s", e)

    # Additional alerts independent of history
    comp_60 = current_ic.get("composite", {}).get(60, {}).get("mean")
    if comp_60 is not None and comp_60 < 0:
        drift_flags.append(f"COMPOSITE NEGATIVE: composite IC at 60d = {comp_60:+.3f} (strategy is net-losing-edge)")
    mom_20 = current_ic.get("momentum", {}).get(20, {}).get("mean")
    if mom_20 is not None and mom_20 < 0:
        drift_flags.append(f"MOMENTUM NEGATIVE: momentum IC at 20d = {mom_20:+.3f} (core factor not working)")

    # Per-factor negative IC for 20d+ horizons (candidates for weight cut)
    for fname in ["quality", "value"]:
        ic60 = current_ic.get(fname, {}).get(60, {}).get("mean")
        if ic60 is not None and ic60 < -0.02:
            drift_flags.append(f"DRAG: {fname} IC at 60d = {ic60:+.3f} — consider reducing its weight")

    result["current_ic"] = current_ic
    result["drift_flags"] = drift_flags
    result["deltas_vs_prior"] = deltas
    result["sample_dates"] = len(sample_dates)
    result["sample_size_hint"] = "weekly audit — use trend across audits, not single reading"

    # Persist summary to agent_memory for dashboard card
    try:
        sb.table("agent_memory").upsert(
            {"key": "strategy_health", "value": result},
            on_conflict="key",
        ).execute()
    except Exception:
        pass

    return result



def check_live_vs_backtest_divergence() -> dict:
    """Compare recent live alpha to most recent backtest alpha for the live variant.

    Lightweight daily check (no data download) — flags when the live strategy is
    deviating materially from backtest expectations. Most common causes:
    - Regime change the backtest period didn't cover
    - Overfitting surfacing in live execution
    - Risk gate (e.g., daily loss limit) suppressing trades the backtest would take

    Thresholds:
    - |live - backtest| / backtest > 0.5 over 30d: moderate divergence
    - >1.0 over 30d: major divergence, consider re-running backtest + audit
    - Magnitude comparison uses ANNUALIZED returns to normalize window length

    Returns:
        Dict with live_alpha_30d, backtest_alpha_annualized, divergence_pct, status.
    """
    from ..factor_scoring import BASELINE_VARIANT

    sb = get_supabase()
    today = datetime.now().date()
    thirty_days_ago = today - timedelta(days=30)

    result: dict = {"as_of": today.isoformat()}

    # 1. Live 30-day alpha from equity_snapshots
    try:
        snaps = (
            sb.table("equity_snapshots")
            .select("snapshot_date, portfolio_cumulative_return, spy_cumulative_return")
            .gte("snapshot_date", thirty_days_ago.isoformat())
            .order("snapshot_date", desc=False)
            .execute()
        )
        rows = snaps.data or []
        if len(rows) < 5:
            return {"status": "insufficient_data", "message": f"Only {len(rows)} live snapshots in past 30d"}

        first, last = rows[0], rows[-1]
        port_first = float(first["portfolio_cumulative_return"])
        port_last = float(last["portfolio_cumulative_return"])
        spy_first = float(first["spy_cumulative_return"])
        spy_last = float(last["spy_cumulative_return"])

        live_port_return_30d = port_last - port_first
        live_spy_return_30d = spy_last - spy_first
        live_alpha_30d = live_port_return_30d - live_spy_return_30d
        # Annualize (252 trading days / ~22 in window)
        days_span = (datetime.fromisoformat(last["snapshot_date"]).date()
                     - datetime.fromisoformat(first["snapshot_date"]).date()).days
        annualize_factor = 365 / max(days_span, 1)
        live_alpha_annualized = live_alpha_30d * annualize_factor
    except Exception as e:
        return {"status": "error", "error": f"Failed to fetch live snapshots: {e}"}

    result["live_alpha_30d_pct"] = round(live_alpha_30d, 4)
    result["live_alpha_annualized_pct"] = round(live_alpha_annualized, 4)

    # 2. Most recent backtest alpha (annualized) for the current live variant
    try:
        bt = (
            sb.table("backtest_runs")
            .select("variant_name, start_date, end_date, alpha_pct, total_return_pct, spy_return_pct")
            .eq("status", "completed")
            .order("created_at", desc=True)
            .limit(20)
            .execute()
        )
        runs = bt.data or []
        # Find the run whose variant matches our live variant name logic
        # (after Apr 17 promotion, "baseline" = short_mom_atr equivalent)
        # Prefer short_mom_atr as canonical backtest since that's what baseline now is
        candidate = None
        for r in runs:
            if r["variant_name"] in ("short_mom_atr", BASELINE_VARIANT.name):
                candidate = r
                break
        if not candidate and runs:
            candidate = runs[0]

        if not candidate:
            return {**result, "status": "no_backtest", "message": "No completed backtest runs yet"}

        # Annualize backtest alpha
        start = datetime.fromisoformat(candidate["start_date"]).date()
        end = datetime.fromisoformat(candidate["end_date"]).date()
        bt_days = (end - start).days
        bt_alpha = float(candidate["alpha_pct"] or 0)
        bt_alpha_annualized = bt_alpha * (365 / max(bt_days, 1))

        result["backtest_variant"] = candidate["variant_name"]
        result["backtest_alpha_pct"] = round(bt_alpha, 4)
        result["backtest_alpha_annualized_pct"] = round(bt_alpha_annualized, 4)
        result["backtest_period"] = f"{candidate['start_date']} → {candidate['end_date']}"

        # Divergence
        if bt_alpha_annualized != 0:
            divergence_pct = (live_alpha_annualized - bt_alpha_annualized) / abs(bt_alpha_annualized)
            result["divergence_ratio"] = round(divergence_pct, 3)

            if divergence_pct < -1.0:
                result["status"] = "major_underperformance"
                result["action"] = "Re-run audit_factor_ic and consider re-running full backtest with recent data"
            elif divergence_pct < -0.5:
                result["status"] = "moderate_underperformance"
                result["action"] = "Watch for 1-2 more weeks; if sustained, investigate regime change"
            elif divergence_pct > 1.0:
                result["status"] = "major_outperformance"
                result["action"] = "Lucky streak or improved regime — don't touch the strategy, but don't trust the boost"
            elif divergence_pct > 0.5:
                result["status"] = "moderate_outperformance"
                result["action"] = "Running ahead of backtest — benign, watch for mean reversion"
            else:
                result["status"] = "aligned"
                result["action"] = "Live performance tracks backtest expectations"
        else:
            result["status"] = "no_baseline"
    except Exception as e:
        return {**result, "status": "error", "error": f"Backtest comparison failed: {e}"}

    # Persist for dashboard
    try:
        sb.table("agent_memory").upsert(
            {"key": "strategy_divergence", "value": result},
            on_conflict="key",
        ).execute()
    except Exception:
        pass

    return result



def suggest_factor_weight_adjustment() -> dict:
    """Propose new factor weights based on latest IC audit — closes the self-adjustment loop.

    This is the bridge between IC data (what the market says each factor is worth)
    and live strategy (how much weight each factor gets). Reads the most recent
    `strategy_health` (from audit_factor_ic) and current `factor_weights`, then
    proposes a new weight distribution.

    **Does NOT auto-apply** — returns a proposal + rationale. The weekly review
    agent reviews, potentially overrides for regime context (e.g., keep momentum
    high in risk-on environments even if IC is marginally lower), and applies via
    `write_agent_memory("factor_weights", ...)`.

    Algorithm:
    1. Compute "signal" per factor: IC at 20d × 0.6 + IC at 60d × 0.4 (weights
       20d higher for responsiveness)
    2. Allocate weight proportionally to max(signal, 0) — factors with negative
       signal get floor weight (0.10)
    3. Apply constraints:
       - Max ±0.05 change per factor per audit (anti-thrashing)
       - Bounds [0.10, 0.45]
       - Sum to 1.00 (normalize after clamping)

    Returns:
        Dict with proposed_weights, current_weights, deltas, rationale per factor,
        and signal strength per factor.
    """
    # 1. Load current weights and latest IC audit
    current = _load_factor_weights()
    sb = get_supabase()

    strategy_health = None
    try:
        row = sb.table("agent_memory").select("value").eq("key", "strategy_health").maybe_single().execute()
        if row.data and row.data.get("value"):
            strategy_health = row.data["value"]
    except Exception as e:
        return {"error": f"Failed to load strategy_health: {e}"}

    if not strategy_health:
        return {
            "status": "no_ic_data",
            "message": "No strategy_health data yet. Run audit_factor_ic() first.",
            "current_weights": current,
        }

    current_ic = strategy_health.get("current_ic", {})

    # 2. Compute "signal" per factor: weighted blend of 20d and 60d IC
    # Only blend factors that ALSO appear in factor_weights (momentum/quality/value/eps_revision)
    factor_signals: dict[str, float] = {}
    factor_ic_detail: dict[str, dict] = {}

    # momentum, quality, value come from audit_factor_ic; eps_revision is not measured there
    # (it requires historical analyst revision data we don't have). Treat it as neutral.
    def _ic_at(fname: str, horizon: int) -> float | None:
        """Handle both int and string horizon keys (JSON round-trip stringifies them)."""
        f_dict = current_ic.get(fname, {})
        stat = f_dict.get(horizon) or f_dict.get(str(horizon))
        if not stat:
            return None
        return stat.get("mean")

    for fname in ["momentum", "quality", "value"]:
        ic_20 = _ic_at(fname, 20)
        ic_60 = _ic_at(fname, 60)
        if ic_20 is None and ic_60 is None:
            factor_signals[fname] = 0.0
            factor_ic_detail[fname] = {"ic_20d": None, "ic_60d": None, "signal": 0.0}
            continue

        ic_20 = ic_20 if ic_20 is not None else 0.0
        ic_60 = ic_60 if ic_60 is not None else 0.0
        signal = 0.6 * ic_20 + 0.4 * ic_60
        factor_signals[fname] = signal
        factor_ic_detail[fname] = {"ic_20d": ic_20, "ic_60d": ic_60, "signal": round(signal, 5)}

    # EPS revision: we don't have historical IC for it, but live system has observed it works.
    # Assume neutral positive signal (0.01) — slightly favors keeping current allocation.
    factor_signals["eps_revision"] = 0.01
    factor_ic_detail["eps_revision"] = {"ic_20d": None, "ic_60d": None, "signal": 0.01, "note": "Not measured in audit — assumed neutral positive"}

    # 3. Allocate proportional to positive signal; negative-signal factors go to floor (0.10)
    floor = 0.10
    cap = 0.45
    max_shift = 0.05  # per audit
    min_signal_threshold = 0.005  # factors below this get floor weight

    # Separate "winners" (positive signal above threshold) from "losers" (below)
    winners: dict[str, float] = {f: s for f, s in factor_signals.items() if s >= min_signal_threshold}
    losers: list[str] = [f for f, s in factor_signals.items() if s < min_signal_threshold]

    # Allocate floor weight to losers first
    remaining_budget = 1.0 - (floor * len(losers))

    # Distribute remaining among winners proportional to signal
    total_winner_signal = sum(winners.values()) if winners else 0
    target: dict[str, float] = {}

    if total_winner_signal > 0:
        for f, sig in winners.items():
            target[f] = remaining_budget * (sig / total_winner_signal)
        for f in losers:
            target[f] = floor
    else:
        # No positive factors — equal-weight fallback
        for f in ["momentum", "quality", "value", "eps_revision"]:
            target[f] = 0.25

    # 4. Apply constraints: ±0.05 max shift from current, [floor, cap] bounds.
    # Iteratively renormalize + reclamp until no constraint violations, max 5 rounds.
    proposed: dict[str, float] = {}
    for f in ["momentum", "quality", "value", "eps_revision"]:
        curr = current.get(f, 0.25)
        raw_target = target.get(f, 0.25)
        shift = max(-max_shift, min(max_shift, raw_target - curr))
        new_w = curr + shift
        new_w = max(floor, min(cap, new_w))
        proposed[f] = new_w

    # Iteratively normalize + reclamp so final deltas respect ±max_shift
    for _ in range(5):
        total = sum(proposed.values())
        if total <= 0:
            break
        normalized = {f: w / total for f, w in proposed.items()}
        # Re-apply max_shift and bounds
        changed = False
        for f in ["momentum", "quality", "value", "eps_revision"]:
            curr = current.get(f, 0.25)
            new_w = normalized[f]
            # Clamp delta from current
            new_w = max(curr - max_shift, min(curr + max_shift, new_w))
            # Clamp to bounds
            new_w = max(floor, min(cap, new_w))
            if abs(new_w - proposed[f]) > 1e-6:
                changed = True
            proposed[f] = new_w
        if not changed:
            break

    # Final round in case normalization still off; accept small drift
    total = sum(proposed.values())
    if total > 0:
        proposed = {f: round(w / total, 3) for f, w in proposed.items()}

    # 6. Rationale per factor
    rationale: dict[str, str] = {}
    deltas: dict[str, float] = {}
    for f in ["momentum", "quality", "value", "eps_revision"]:
        delta = round(proposed[f] - current.get(f, 0.25), 3)
        deltas[f] = delta
        sig = factor_signals.get(f, 0.0)

        if abs(delta) < 0.005:
            rationale[f] = f"Hold steady. Signal {sig:+.3f} doesn't justify a change."
        elif delta > 0:
            if sig > 0.02:
                rationale[f] = f"Increase by +{delta:.2f}. Strong positive IC (signal {sig:+.3f})."
            else:
                rationale[f] = f"Increase by +{delta:.2f}. Modest positive IC (signal {sig:+.3f})."
        else:
            if sig < -0.02:
                rationale[f] = f"Decrease by {delta:.2f}. Negative IC (signal {sig:+.3f}) — factor is a drag."
            else:
                rationale[f] = f"Decrease by {delta:.2f}. Redistributing to stronger factors."

    # Summary flag
    big_changes = [f for f, d in deltas.items() if abs(d) >= 0.05]
    summary = (
        f"Big changes: {', '.join(big_changes)}" if big_changes
        else "Small adjustments only — IC roughly stable."
    )

    return {
        "status": "ok",
        "current_weights": current,
        "proposed_weights": proposed,
        "deltas": deltas,
        "factor_signals": factor_ic_detail,
        "rationale": rationale,
        "summary": summary,
        "constraints_applied": {
            "max_shift_per_audit": max_shift,
            "bounds": [floor, cap],
            "sum_normalized_to": 1.0,
        },
        "as_of": datetime.now().isoformat(),
    }


