"""Factor scoring + monitoring tools: universe scoring, EPS revisions, ranking signals, watchlist alerts, catalysts, earnings results."""

import logging
import os
import time
from datetime import datetime

import pandas as pd
import yfinance as yf
from tavily import TavilyClient

from common.db import get_watchlist, read_memory, write_memory as db_write_memory
from stock_agent.market_data import (
    get_historical_bars,
    get_portfolio,
    get_quote,
    get_sp500_sp400_tickers,
)
from stock_agent.tools._shared import _load_factor_weights
from stock_agent.tools.market import earnings_calendar, eps_estimates

logger = logging.getLogger(__name__)

_factor_cache: dict = {"data": None, "timestamp": 0.0}

_FACTOR_CACHE_TTL = 14400  # 4 hours

# Sector ETF mapping for sector_analysis and market_breadth

def _percentile_rank(series: pd.Series) -> pd.Series:
    """Compute percentile rank (0-100) for each value in a Series."""
    return series.rank(pct=True, na_option="keep") * 100



def score_universe(top_n: int = 30) -> dict:
    """Score the S&P 500 + S&P 400 universe on momentum, quality, and value factors.

    This is a systematic, deterministic scoring pipeline that replaces subjective
    LLM analysis. All computation happens in Python — no LLM reasoning needed.

    Pipeline:
    1. Bulk download 1Y prices for ~900 tickers
    2. Compute momentum factor (12m-ex-1m + 3m returns)
    3. Pre-filter top ~150 by momentum, fetch fundamentals
    4. Compute quality factor (margin + ROE - leverage)
    5. Compute value factor (inverse forward P/E within sector)
    6. Composite = weighted sum using factor_weights from memory (eps starts at 50)
    7. Return top_n ranked stocks

    Uses a 4-hour cache to avoid redundant downloads within the same trading day.

    Args:
        top_n: Number of top-ranked stocks to return (default 30).

    Returns:
        Dict with universe_size, scored count, factor_weights, and rankings list.
    """
    global _factor_cache

    now = time.time()
    if _factor_cache["data"] and (now - _factor_cache["timestamp"]) < _FACTOR_CACHE_TTL:
        cached = _factor_cache["data"]
        # Re-slice to requested top_n
        return {
            **cached,
            "rankings": cached["rankings"][:top_n],
            "cached": True,
        }

    # Cross-run cache: check agent_memory for recent scoring (survives process restarts)
    try:
        cached_mem = read_memory("factor_cache")
        if cached_mem and cached_mem.get("value"):
            cv = cached_mem["value"]
            cached_at = cv.get("cached_at", 0)
            if (now - cached_at) < _FACTOR_CACHE_TTL and len(cv.get("rankings", [])) >= 20:
                _factor_cache["data"] = cv
                _factor_cache["timestamp"] = cached_at
                return {
                    **cv,
                    "rankings": cv["rankings"][:top_n],
                    "cached": True,
                }
    except Exception:
        pass

    tickers = get_sp500_sp400_tickers()
    if not tickers:
        return {"error": "Could not fetch ticker universe", "rankings": []}

    # Step 1: Bulk download 1Y of daily closes
    try:
        price_data = yf.download(tickers, period="1y", progress=False, threads=True)
    except Exception as e:
        return {"error": f"Price download failed: {e}", "rankings": []}

    if price_data.empty:
        return {"error": "No price data returned", "rankings": []}

    close = price_data["Close"]

    # Step 2: Compute momentum on full universe (lets us pre-filter below)
    from ..factor_scoring import (
        BASELINE_VARIANT,
        compute_factor_scores,
        compute_momentum,
    )

    variant = BASELINE_VARIANT
    momentum_score = compute_momentum(close, variant)
    if len(momentum_score) == 0:
        return {"error": "No valid momentum data", "rankings": []}

    # Keep 3m and 12m-ex-1m returns for downstream UI display
    ret_3m = pd.Series(dtype=float)
    ret_12m_ex1m = pd.Series(dtype=float)
    try:
        if len(close) > 22:
            ret_12m_ex1m = (close.iloc[-22] / close.iloc[0] - 1).dropna()
        lookback_3m = min(63, len(close) - 1)
        if lookback_3m > 0:
            ret_3m = (close.iloc[-1] / close.iloc[-lookback_3m] - 1).dropna()
    except Exception:
        pass

    # Step 3: Pre-filter top N by momentum, fetch fundamentals for candidates
    candidates = (
        momentum_score.nlargest(variant.prefilter_top_n).index.tolist()
        if variant.prefilter_top_n
        else momentum_score.index.tolist()
    )

    fundamentals: dict[str, dict] = {}
    for sym in candidates:
        try:
            info = yf.Ticker(sym).info
            fundamentals[sym] = {
                "sector": info.get("sector", "Unknown"),
                "forward_pe": info.get("forwardPE"),
                "profit_margin": info.get("profitMargins"),
                "roe": info.get("returnOnEquity"),
                "debt_to_equity": info.get("debtToEquity"),
                "current_price": info.get("currentPrice") or info.get("regularMarketPrice"),
            }
        except Exception:
            continue

    if not fundamentals:
        return {"error": "No fundamental data retrieved", "rankings": []}

    # Step 4: Call shared pure scoring function
    factor_weights = _load_factor_weights()
    results = compute_factor_scores(
        close=close,
        fundamentals=fundamentals,
        variant=variant,
        factor_weights=factor_weights,
    )

    # Step 5: Attach raw returns for UI compatibility (return_3m, return_12m_ex1m)
    for r in results:
        sym = r["symbol"]
        r["return_3m"] = round(float(ret_3m.get(sym, 0)), 4) if sym in ret_3m.index else 0.0
        r["return_12m_ex1m"] = (
            round(float(ret_12m_ex1m.get(sym, 0)), 4) if sym in ret_12m_ex1m.index else 0.0
        )

    # Sanity check: if scoring returned very few results, fall back to cached data
    if len(results) < 20:
        logger.warning("score_universe returned only %d stocks (expected 100+), checking cache", len(results))
        try:
            cached_mem = read_memory("factor_cache")
            if cached_mem and cached_mem.get("value"):
                cv = cached_mem["value"]
                if len(cv.get("rankings", [])) >= 20:
                    logger.info("Falling back to cached scoring with %d stocks", len(cv["rankings"]))
                    _factor_cache["data"] = cv
                    _factor_cache["timestamp"] = cv.get("cached_at", now)
                    return {
                        **cv,
                        "rankings": cv["rankings"][:top_n],
                        "cached": True,
                        "fallback_reason": f"Fresh scoring returned only {len(results)} stocks, using cache",
                    }
        except Exception:
            pass

    # Cache all results (not just top_n) so enrich and generate can use them
    cache_payload = {
        "universe_size": len(tickers),
        "scored": len(results),
        "factor_weights": factor_weights,
        "rankings": results,
        "scored_at": datetime.now().strftime("%Y-%m-%d %I:%M %p"),
    }
    _factor_cache["data"] = cache_payload
    _factor_cache["timestamp"] = now

    # Persist to agent_memory so the next cron run can use it (cross-process cache)
    try:
        # Store only top 50 to keep memory size reasonable
        persist_payload = {**cache_payload, "rankings": results[:50], "cached_at": now}
        db_write_memory("factor_cache", persist_payload)
    except Exception:
        logger.warning("Failed to persist factor cache to agent_memory")

    return {
        **cache_payload,
        "rankings": results[:top_n],
        "cached": False,
    }



def enrich_eps_revisions(symbols: list[str]) -> dict:
    """Enrich top-ranked stocks with EPS revision scores using yfinance.

    Combines two signals:
    1. **eps_trend** (70% weight): Estimate direction — current consensus vs 30 days ago.
    2. **eps_revisions** (30% weight): Analyst breadth — ratio of up vs down revisions.

    Score ranges:
    - Strong rising (estimate up + many analysts revising up) → 80-90
    - Rising → 70-80
    - Flat → 45-55
    - Falling → 20-30
    - Strong falling → 10-20

    Uses yfinance (free, no API key needed). Each call takes ~0.5s.

    Args:
        symbols: List of ticker symbols to enrich (recommended: top 20).

    Returns:
        Dict with enriched list of symbols and their EPS revision scores.
    """
    enriched = []

    for sym in symbols[:20]:  # Cap at 20
        try:
            ticker = yf.Ticker(sym)
            eps_trend = ticker.eps_trend
            eps_revisions = ticker.eps_revisions

            if eps_trend is None or eps_trend.empty:
                enriched.append({
                    "symbol": sym,
                    "eps_revision_score": 50.0,
                    "revision_signal": "no_data",
                    "next_quarter_eps_avg": None,
                    "analysts_up": None,
                    "analysts_down": None,
                })
                continue

            # --- Signal 1: Estimate direction (eps_trend) ---
            if "0q" in eps_trend.index:
                row = eps_trend.loc["0q"]
            else:
                row = eps_trend.iloc[0]

            current = row.get("current")
            thirty_days_ago = row.get("30daysAgo")
            next_q_eps = float(current) if current is not None else None

            if current is not None and thirty_days_ago is not None and thirty_days_ago != 0:
                pct_change = (float(current) - float(thirty_days_ago)) / abs(float(thirty_days_ago))

                if pct_change > 0.03:
                    trend_score = min(90.0, 70.0 + pct_change * 100)
                    signal = "rising"
                elif pct_change < -0.03:
                    trend_score = max(10.0, 30.0 + pct_change * 100)
                    signal = "falling"
                else:
                    trend_score = 50.0
                    signal = "flat"
            else:
                trend_score = 50.0
                signal = "no_data"

            # --- Signal 2: Analyst breadth (eps_revisions) ---
            breadth_score = 50.0  # Default neutral
            analysts_up = None
            analysts_down = None

            if eps_revisions is not None and not eps_revisions.empty:
                if "0q" in eps_revisions.index:
                    rev_row = eps_revisions.loc["0q"]
                else:
                    rev_row = eps_revisions.iloc[0]

                up_30 = rev_row.get("upLast30days", 0) or 0
                down_30 = rev_row.get("downLast30days", 0) or 0
                analysts_up = int(up_30)
                analysts_down = int(down_30)
                total = analysts_up + analysts_down

                if total > 0:
                    # Ratio of up/(up+down): 1.0 = all up, 0.0 = all down
                    up_ratio = analysts_up / total
                    # Map to score: 0.0 → 10, 0.5 → 50, 1.0 → 90
                    breadth_score = 10.0 + up_ratio * 80.0

            # --- Combine: 70% trend + 30% breadth ---
            combined_score = round(0.7 * trend_score + 0.3 * breadth_score, 1)

            # Adjust signal based on combined score
            if combined_score >= 70:
                signal = "rising"
            elif combined_score <= 30:
                signal = "falling"
            elif 45 <= combined_score <= 55:
                signal = "flat"
            # else keep original signal from trend

            enriched.append({
                "symbol": sym,
                "eps_revision_score": combined_score,
                "revision_signal": signal,
                "next_quarter_eps_avg": next_q_eps,
                "analysts_up": analysts_up,
                "analysts_down": analysts_down,
            })

        except Exception as e:
            enriched.append({
                "symbol": sym,
                "eps_revision_score": 50.0,
                "revision_signal": "error",
                "next_quarter_eps_avg": None,
                "error": str(e),
            })

    return {"enriched": enriched, "count": len(enriched)}



def _check_reentry_delta(symbol: str, stopped_data: dict) -> str | None:
    """Check if conditions have changed enough to allow re-entry after a stop-loss.

    Returns a reason string if re-entry should be BLOCKED, or None if a delta is met.
    Requires at least ONE of: price drop (1 ATR below stop), regime improvement
    (VIX -2 or breadth +10pp), or new earnings data since exit.
    """
    exit_price = stopped_data.get("exit_price", 0)
    regime_at_exit = stopped_data.get("regime_at_exit", {})
    exit_date_str = stopped_data.get("exit_date", "")

    # Staleness escape: if exit was >30 days ago, allow re-entry
    if exit_date_str:
        try:
            exit_date = datetime.strptime(exit_date_str, "%Y-%m-%d")
            if (datetime.now() - exit_date).days > 30:
                return None
        except ValueError:
            pass

    deltas_checked = []

    # Delta 1: Price — current price >= 1 ATR below the stop price
    try:
        df = get_historical_bars(symbol, days=30)
        if df is not None and len(df) >= 14:
            from stock_agent.technical import compute_indicators

            indicators = compute_indicators(df)
            atr = indicators.get("atr", 0)
            current_price = float(df["close"].iloc[-1])

            if atr > 0 and exit_price > 0:
                if current_price <= exit_price - atr:
                    return None  # Price delta met
                deltas_checked.append(
                    f"Price ${current_price:.2f} not 1 ATR (${atr:.2f}) below stop ${exit_price:.2f}"
                )
    except Exception:
        deltas_checked.append("Could not compute price delta")

    # Delta 2: Regime improvement — VIX down 2+ or breadth up 10+
    try:
        current_regime = read_memory("market_regime")
        if current_regime and current_regime.get("value") and regime_at_exit:
            cr = current_regime["value"]
            exit_vix = regime_at_exit.get("vix")
            exit_breadth = regime_at_exit.get("breadth_pct")
            current_vix = cr.get("vix")
            current_breadth = cr.get("breadth_pct")

            if exit_vix is not None and current_vix is not None:
                if current_vix <= exit_vix - 2:
                    return None  # VIX improved
            if exit_breadth is not None and current_breadth is not None:
                if current_breadth >= exit_breadth + 10:
                    return None  # Breadth improved
            deltas_checked.append(
                f"Regime unchanged (VIX {current_vix} vs {exit_vix} at exit, "
                f"breadth {current_breadth}% vs {exit_breadth}%)"
            )
    except Exception:
        deltas_checked.append("Could not compute regime delta")

    # Delta 3: New earnings reaction since exit
    try:
        er_mem = read_memory(f"earnings_reaction:{symbol}")
        if er_mem and er_mem.get("value"):
            reaction_date = er_mem["value"].get("date", "")
            if reaction_date > exit_date_str:
                return None  # New earnings data since exit
        deltas_checked.append("No new earnings reaction since exit")
    except Exception:
        deltas_checked.append("Could not check earnings delta")

    # No delta met — block re-entry
    return "No meaningful change: " + "; ".join(deltas_checked)



def generate_factor_rankings(
    universe_scores: list[dict],
    eps_enrichment: list[dict],
    held_symbols: list[str],
) -> dict:
    """Merge EPS revision scores, recompute composites, and produce BUY/SELL/HOLD signals.

    Pure computation — no API calls. Takes output from score_universe() and
    enrich_eps_revisions() and produces actionable signals.

    Signal logic:
    - BUY: Top 20 by composite, not currently held, composite > 70
    - HOLD: Currently held, still in top 50
    - SELL: Currently held, dropped below rank 100 OR eps_revision < 30

    Position sizing: Equal weight with 20% cash buffer, max 8 positions.

    Args:
        universe_scores: The rankings list from score_universe().
        eps_enrichment: The enriched list from enrich_eps_revisions().
        held_symbols: List of currently held ticker symbols.

    Returns:
        Dict with buy_signals, sell_signals, hold_signals, and position sizing.
    """
    # Build EPS revision lookup
    eps_lookup = {e["symbol"]: e["eps_revision_score"] for e in eps_enrichment}

    # Factor weights — read from memory (updated by weekly review)
    weights = _load_factor_weights()

    # Update composite scores with actual EPS revision data
    for stock in universe_scores:
        sym = stock["symbol"]
        if sym in eps_lookup:
            old_eps = stock.get("eps_revision_score", 50.0)
            new_eps = eps_lookup[sym]
            stock["eps_revision_score"] = new_eps
            # Recompute composite
            stock["composite_score"] = round(
                weights["momentum"] * stock.get("momentum_score", 50)
                + weights["quality"] * stock.get("quality_score", 50)
                + weights["value"] * stock.get("value_score", 50)
                + weights["eps_revision"] * new_eps,
                1,
            )

    # Re-sort by composite
    universe_scores.sort(key=lambda x: x.get("composite_score", 0), reverse=True)

    # Re-rank
    for i, stock in enumerate(universe_scores):
        stock["rank"] = i + 1

    held_set = {s.upper() for s in held_symbols}

    # Build signal lists
    buy_signals = []
    sell_signals = []
    hold_signals = []

    for stock in universe_scores:
        sym = stock["symbol"]
        rank = stock["rank"]
        composite = stock.get("composite_score", 0)
        eps_rev = stock.get("eps_revision_score", 50)

        if sym in held_set:
            # Held position evaluation
            if rank > 100 or eps_rev < 30:
                sell_signals.append({
                    **stock,
                    "signal": "SELL",
                    "reason": f"Rank #{rank}" + (", falling EPS revisions" if eps_rev < 30 else ", dropped out of top 100"),
                })
            elif rank <= 50:
                hold_signals.append({
                    **stock,
                    "signal": "HOLD",
                    "reason": f"Rank #{rank}, still in top 50",
                })
            else:
                hold_signals.append({
                    **stock,
                    "signal": "HOLD",
                    "reason": f"Rank #{rank}, between 50-100 — monitoring",
                })
        else:
            # Not held — potential buy
            if rank <= 20 and composite > 70:
                # Entry quality floor: don't buy what we'd immediately sell
                if eps_rev < 30:
                    hold_signals.append({
                        **stock,
                        "signal": "HOLD",
                        "reason": f"ENTRY BLOCKED: EPS revision {eps_rev} < 30 (would trigger immediate SELL)",
                    })
                    continue

                # Re-entry guard: check if recently stopped out
                stopped_mem = read_memory(f"stopped:{sym}")
                if stopped_mem and stopped_mem.get("value"):
                    sv = stopped_mem["value"]
                    block_reason = _check_reentry_delta(sym, sv)
                    if block_reason:
                        exit_date = sv.get("exit_date", "unknown")
                        hold_signals.append({
                            **stock,
                            "signal": "HOLD",
                            "reason": f"RE-ENTRY BLOCKED: stopped out on {exit_date}. {block_reason}",
                        })
                        continue

                buy_signals.append({
                    **stock,
                    "signal": "BUY",
                    "reason": f"Rank #{rank}, composite {composite}",
                })

    # Position sizing: equal weight, 20% cash buffer, max 8 positions
    current_positions = len(held_set)
    max_positions = 8
    available_slots = max(0, max_positions - current_positions)
    position_weight_pct = round(80.0 / max_positions, 1)  # 10% each with 20% cash buffer

    return {
        "buy_signals": buy_signals[:available_slots],  # Only as many as we have room for
        "sell_signals": sell_signals,
        "hold_signals": hold_signals,
        "total_ranked": len(universe_scores),
        "position_sizing": {
            "max_positions": max_positions,
            "current_positions": current_positions,
            "available_slots": available_slots,
            "target_weight_pct": position_weight_pct,
            "cash_buffer_pct": 20.0,
        },
        "factor_weights": weights,
    }


# ============================================================
# Price Alert tools
# ============================================================


def check_watchlist_alerts(threshold_pct: float = 2.0) -> dict:
    """Check all watchlist stocks against their target_entry prices.

    Returns stocks within threshold_pct of their target (or below it).
    Use this for lightweight price checks between full trading loops.

    Args:
        threshold_pct: How close to target to trigger an alert (default 2%).

    Returns:
        Dict with alerts list and count.
    """
    watchlist = get_watchlist()
    alerts = []

    for item in watchlist:
        target = item.get("target_entry")
        if not target:
            continue
        target = float(target)
        symbol = item["symbol"]

        try:
            quote = get_quote(symbol)
            price = float(quote.get("last_price", 0))
            if price <= 0:
                continue

            distance_pct = round((price / target - 1) * 100, 2)

            if distance_pct <= threshold_pct:
                alerts.append({
                    "symbol": symbol,
                    "current_price": price,
                    "target_entry": target,
                    "distance_pct": distance_pct,
                    "at_or_below_target": distance_pct <= 0,
                    "thesis": item.get("thesis", ""),
                })
        except Exception:
            logger.warning("Failed to get quote for %s in alert check", symbol)

    return {
        "alerts": alerts,
        "count": len(alerts),
        "checked": len([w for w in watchlist if w.get("target_entry")]),
    }



def discover_catalysts(
    symbols: list[str] | None = None,
    days_ahead: int = 30,
) -> dict:
    """Discover upcoming corporate catalysts (conferences, product launches, investor days, regulatory events).

    Searches the web for upcoming high-impact events for each symbol. Returns raw
    search results — the LLM interprets significance and writes structured memory.

    Args:
        symbols: Tickers to check. If None, uses watchlist + current positions.
        days_ahead: How many days to look ahead (default 30).

    Returns:
        Raw search results grouped by symbol for LLM interpretation.
    """
    # Auto-populate from watchlist + positions if no symbols provided
    if not symbols:
        symbols = set()
        try:
            watchlist = get_watchlist()
            symbols.update(item["symbol"] for item in watchlist)
        except Exception:
            pass
        try:
            portfolio = get_portfolio()
            symbols.update(pos["symbol"] for pos in portfolio.get("positions", []))
        except Exception:
            pass
        symbols = list(symbols) if symbols else []

    if not symbols:
        return {"error": "No symbols to check — watchlist and portfolio are empty"}

    # Cap at 15 symbols to avoid excessive API calls
    symbols = symbols[:15]

    current_year = datetime.now().year
    client = TavilyClient(api_key=os.environ.get("TAVILY_API_KEY"))
    results = {}

    # Map tickers to company names for better search quality
    _names: dict[str, str] = {}
    try:
        for sym in symbols:
            t = yf.Ticker(sym)
            _names[sym] = t.info.get("shortName", sym)
    except Exception:
        pass

    for sym in symbols:
        try:
            name = _names.get(sym, sym)
            response = client.search(
                query=f"{name} ({sym}) upcoming conference investor day product launch catalyst event {current_year}",
                topic="general",
                max_results=5,
            )
            hits = response.get("results", [])
            if hits:
                results[sym] = [
                    {"title": h.get("title", ""), "url": h.get("url", ""), "content": h.get("content", "")}
                    for h in hits
                ]
        except Exception:
            logger.warning("Failed to search catalysts for %s", sym)

    return {
        "results": results,
        "symbols_checked": symbols,
        "searched_at": datetime.now().isoformat(),
    }



def get_earnings_results(symbol: str) -> dict:
    """Get structured earnings data: 4-quarter surprise history + forward estimate revisions.

    Combines earnings_calendar() surprise data with eps_estimates() revision signal.
    Use this to bootstrap or update an earnings profile for a company.

    Args:
        symbol: Ticker symbol (e.g. "MU").

    Returns:
        Dict with surprise_history, summary stats, forward_estimates, and flags.
    """
    # 1. Get historical surprises from earnings_calendar
    cal_data = earnings_calendar(symbols=[symbol])
    surprises = [s for s in cal_data.get("recent_surprises", []) if s.get("symbol") == symbol]

    # Sort by period descending
    surprises.sort(key=lambda x: x.get("period", ""), reverse=True)

    # Build surprise history
    surprise_history = []
    for s in surprises:
        surprise_history.append({
            "period": s.get("period"),
            "actual": s.get("actual_eps"),
            "estimate": s.get("estimated_eps"),
            "surprise_pct": s.get("surprise_pct", 0),
        })

    # 2. Compute summary stats
    quarters_available = len(surprise_history)
    if quarters_available > 0:
        avg_surprise_pct = round(
            sum(s["surprise_pct"] for s in surprise_history) / quarters_available, 1
        )
        # Beat streak: consecutive positive surprises from most recent
        beat_streak = 0
        for s in surprise_history:
            if s["surprise_pct"] > 0:
                beat_streak += 1
            else:
                break
        beats = sum(1 for s in surprise_history if s["surprise_pct"] > 0)
        beat_rate = round(beats / quarters_available, 2)
    else:
        avg_surprise_pct = 0
        beat_streak = 0
        beat_rate = 0

    # 3. Check if most recent report is fresh (within last 10 days)
    reported_recently = False
    latest_quarter = None
    if surprise_history:
        latest = surprise_history[0]
        latest_quarter = {
            "period": latest["period"],
            "actual_eps": latest["actual"],
            "estimated_eps": latest["estimate"],
            "surprise_pct": latest["surprise_pct"],
        }
        try:
            period_date = datetime.strptime(latest["period"], "%Y-%m-%d")
            if (datetime.now() - period_date).days <= 10:
                reported_recently = True
        except (ValueError, TypeError):
            pass

    # 4. Get forward estimates
    est_data = eps_estimates(symbol, freq="quarterly")
    forward_estimates = {}
    if est_data.get("estimates"):
        next_q = est_data["estimates"][0]
        forward_estimates = {
            "next_quarter_eps": next_q.get("eps_avg"),
            "revision_signal": est_data.get("revision_signal", "unknown"),
        }

    # 5. Determine if qualitative review is needed
    needs_qualitative_review = False
    if latest_quarter and abs(latest_quarter.get("surprise_pct", 0)) > 5:
        needs_qualitative_review = True

    return {
        "symbol": symbol,
        "reported_recently": reported_recently,
        "latest_quarter": latest_quarter,
        "surprise_history": surprise_history,
        "summary": {
            "quarters_available": quarters_available,
            "avg_surprise_pct": avg_surprise_pct,
            "beat_streak": beat_streak,
            "beat_rate": beat_rate,
        },
        "forward_estimates": forward_estimates,
        "needs_qualitative_review": needs_qualitative_review,
    }


# ============================================================
# Tool collections for each mode
# ============================================================

