"""Market-data tools: quotes, history, technicals, fundamentals, screening, sector/peer/earnings/breadth."""

import logging
import os
from datetime import datetime, timedelta
from typing import Literal

import pandas as pd
import yfinance as yf
from tavily import TavilyClient

from stock_agent.db import get_watchlist, read_memory, write_memory as db_write_memory
from stock_agent.finnhub_client import get_finnhub
from stock_agent.market_data import (
    get_historical_bars,
    get_historical_data_dict,
    get_portfolio,
    get_quote,
    get_sp500_sp400_tickers,
)
from stock_agent.technical import compute_indicators

logger = logging.getLogger(__name__)


def _avg_return(sectors: list[dict], etf_set: set[str]) -> float:
    """Average return for a set of sector ETFs."""
    vals = [s["total_return"] for s in sectors if s["etf"] in etf_set]
    return sum(vals) / len(vals) if vals else 0.0

SECTOR_ETFS = {
    "XLK": "Technology",
    "XLF": "Financials",
    "XLV": "Health Care",
    "XLC": "Communication Services",
    "XLY": "Consumer Discretionary",
    "XLP": "Consumer Staples",
    "XLE": "Energy",
    "XLI": "Industrials",
    "XLB": "Materials",
    "XLRE": "Real Estate",
    "XLU": "Utilities",
}


CYCLICAL_SECTORS = {"XLK", "XLF", "XLY", "XLI", "XLB", "XLE"}

DEFENSIVE_SECTORS = {"XLV", "XLP", "XLU", "XLRE"}


# ============================================================
# Shared tools (both modes)
# ============================================================


def internet_search(
    query: str,
    *,
    topic: Literal["general", "news", "finance"] = "general",
    max_results: int = 5,
) -> list[dict]:
    """Search the internet for news, analysis, and financial information.

    Args:
        query: The search query string.
        topic: Category - "general", "news", or "finance".
        max_results: Maximum number of results (1-10).

    Returns:
        List of search results with title, url, and content snippet.
    """
    client = TavilyClient(api_key=os.environ.get("TAVILY_API_KEY"))
    response = client.search(
        query=query,
        topic=topic,
        max_results=max_results,
    )
    return response.get("results", [])



def get_stock_quote(symbol: str) -> dict:
    """Get the latest quote for a stock symbol.

    Args:
        symbol: Stock ticker symbol (e.g. "AAPL").

    Returns:
        Dict with ask_price, bid_price, and timestamp.
    """
    return get_quote(symbol)


# ============================================================
# Autonomous-mode tools (used in autonomy.py)
# ============================================================


def get_historical_data(symbol: str, days: int = 90) -> dict:
    """Get historical OHLCV data for a stock.

    Args:
        symbol: Stock ticker symbol.
        days: Number of days of history (default 90).

    Returns:
        Dict with bars (date, OHLCV), count, and latest close.
    """
    return get_historical_data_dict(symbol, days=days)



def technical_analysis(symbol: str, days: int = 90) -> dict:
    """Run technical analysis on a stock — RSI, MACD, Bollinger, SMA, volume, ATR.

    Args:
        symbol: Stock ticker symbol.
        days: Number of days of data to analyze.

    Returns:
        Dict of indicators and signals.
    """
    df = get_historical_bars(symbol, days=days)
    return {"symbol": symbol, **compute_indicators(df)}



def fundamental_analysis(symbol: str) -> dict:
    """Get fundamental data for a stock using yfinance.

    Args:
        symbol: Stock ticker symbol.

    Returns:
        Dict with P/E, market cap, revenue, earnings, and other fundamentals.
    """
    ticker = yf.Ticker(symbol)
    info = ticker.info

    return {
        "symbol": symbol,
        "name": info.get("longName", symbol),
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "market_cap": info.get("marketCap"),
        "pe_ratio": info.get("trailingPE"),
        "forward_pe": info.get("forwardPE"),
        "peg_ratio": info.get("pegRatio"),
        "price_to_book": info.get("priceToBook"),
        "revenue": info.get("totalRevenue"),
        "revenue_growth": info.get("revenueGrowth"),
        "earnings_growth": info.get("earningsGrowth"),
        "profit_margin": info.get("profitMargins"),
        "debt_to_equity": info.get("debtToEquity"),
        "current_ratio": info.get("currentRatio"),
        "dividend_yield": info.get("dividendYield"),
        "beta": info.get("beta"),
        "fifty_two_week_high": info.get("fiftyTwoWeekHigh"),
        "fifty_two_week_low": info.get("fiftyTwoWeekLow"),
        "analyst_target": info.get("targetMeanPrice"),
        "recommendation": info.get("recommendationKey"),
    }



def screen_stocks(
    criteria: Literal["value", "momentum", "quality", "oversold", "growth"],
    sector: str | None = None,
    max_results: int = 10,
) -> dict:
    """Screen S&P 500 + S&P 400 stocks using quantitative filters.

    Args:
        criteria: Screening strategy — "value", "momentum", "quality", "oversold", or "growth".
        sector: Optional sector filter (e.g. "Technology").
        max_results: Max stocks to return (default 10).

    Returns:
        Dict with criteria used and list of matching stocks with key metrics.
    """
    tickers = get_sp500_sp400_tickers()
    if not tickers:
        return {"error": "Could not fetch ticker universe", "candidates": []}

    # Phase 1: Bulk price download for fast filtering
    try:
        price_data = yf.download(tickers, period="3mo", progress=False, threads=True)
    except Exception as e:
        return {"error": f"Price download failed: {e}", "candidates": []}

    if price_data.empty:
        return {"error": "No price data returned", "candidates": []}

    close = price_data["Close"]

    # Compute 3-month returns and basic RSI for pre-filtering
    returns_3m = (close.iloc[-1] / close.iloc[0] - 1).dropna()

    # Simple RSI approximation from daily closes
    daily_returns = close.pct_change()
    window = 14
    gain = daily_returns.clip(lower=0).rolling(window).mean()
    loss = (-daily_returns.clip(upper=0)).rolling(window).mean()
    rs = gain.iloc[-1] / loss.iloc[-1].replace(0, float("nan"))
    rsi = 100 - (100 / (1 + rs))
    rsi = rsi.dropna()

    # Phase 1 pre-filter based on criteria
    if criteria == "momentum":
        candidates = returns_3m[returns_3m > 0.15].index.tolist()
        candidates = [s for s in candidates if s in rsi.index and 50 <= rsi[s] <= 70]
    elif criteria == "oversold":
        candidates = [s for s in rsi.index if rsi[s] < 35]
    elif criteria == "value":
        # Can't filter by P/E from price data alone — take bottom 30% by returns (beaten down)
        bottom = returns_3m.nsmallest(int(len(returns_3m) * 0.3))
        candidates = bottom.index.tolist()
    elif criteria == "quality":
        # Take top 30% by returns as initial filter (quality tends to outperform)
        top = returns_3m.nlargest(int(len(returns_3m) * 0.3))
        candidates = top.index.tolist()
    elif criteria == "growth":
        # Top 20% by returns as proxy for growth
        top = returns_3m.nlargest(int(len(returns_3m) * 0.2))
        candidates = top.index.tolist()
    else:
        candidates = returns_3m.nlargest(30).index.tolist()

    # Cap candidates for detailed lookup
    candidates = candidates[:30]

    # Phase 2: Fetch fundamentals for candidates
    results = []
    for sym in candidates:
        if len(results) >= max_results:
            break
        try:
            info = yf.Ticker(sym).info
            sym_sector = info.get("sector", "")
            if sector and sector.lower() not in sym_sector.lower():
                continue

            pe = info.get("trailingPE")
            fwd_pe = info.get("forwardPE")
            pb = info.get("priceToBook")
            div_yield = info.get("dividendYield")
            profit_margin = info.get("profitMargins")
            roe = info.get("returnOnEquity")
            de = info.get("debtToEquity")
            rev_growth = info.get("revenueGrowth")
            earn_growth = info.get("earningsGrowth")
            ret = float(returns_3m.get(sym, 0))
            sym_rsi = float(rsi.get(sym, 50))

            # Apply criteria-specific fundamental filters
            reason = []
            if criteria == "value":
                if pe and pe > 15:
                    continue
                if pb and pb > 2:
                    continue
                if pe:
                    reason.append(f"P/E={pe:.1f}")
                if pb:
                    reason.append(f"P/B={pb:.1f}")
                if div_yield:
                    reason.append(f"Div={div_yield:.1%}")
            elif criteria == "momentum":
                reason.append(f"3mo return={ret:.1%}")
                reason.append(f"RSI={sym_rsi:.0f}")
            elif criteria == "quality":
                if profit_margin and profit_margin < 0.15:
                    continue
                if roe and roe < 0.15:
                    continue
                if de and de > 100:
                    continue
                if profit_margin:
                    reason.append(f"Margin={profit_margin:.1%}")
                if roe:
                    reason.append(f"ROE={roe:.1%}")
            elif criteria == "oversold":
                reason.append(f"RSI={sym_rsi:.0f}")
                if pe:
                    reason.append(f"P/E={pe:.1f}")
            elif criteria == "growth":
                if rev_growth and rev_growth < 0.15:
                    continue
                if rev_growth:
                    reason.append(f"RevGrowth={rev_growth:.1%}")
                if earn_growth:
                    reason.append(f"EarnGrowth={earn_growth:.1%}")
                if fwd_pe and pe and fwd_pe < pe:
                    reason.append("Fwd P/E < Trailing P/E")

            results.append({
                "symbol": sym,
                "name": info.get("longName", sym),
                "sector": sym_sector,
                "industry": info.get("industry", ""),
                "market_cap": info.get("marketCap"),
                "pe_ratio": pe,
                "forward_pe": fwd_pe,
                "price_to_book": pb,
                "profit_margin": profit_margin,
                "roe": roe,
                "debt_to_equity": de,
                "revenue_growth": rev_growth,
                "earnings_growth": earn_growth,
                "dividend_yield": div_yield,
                "return_3m": round(ret, 4),
                "rsi": round(sym_rsi, 1),
                "reason": ", ".join(reason) if reason else criteria,
            })
        except Exception:
            continue

    return {
        "criteria": criteria,
        "sector": sector,
        "universe_size": len(tickers),
        "candidates_screened": len(candidates),
        "results": results,
    }



def company_profile(symbol: str) -> dict:
    """Get a deep company profile combining Finnhub and yfinance data.

    Includes: company overview, analyst recommendations, insider transactions,
    4-year financials, balance sheet, cash flow, and major holders.

    Args:
        symbol: Stock ticker symbol.

    Returns:
        Comprehensive company profile dict.
    """
    fh = get_finnhub()
    result: dict = {"symbol": symbol}

    # Finnhub: company profile
    try:
        profile = fh.company_profile2(symbol=symbol)
        result["profile"] = {
            "name": profile.get("name"),
            "sector": profile.get("finnhubIndustry"),
            "country": profile.get("country"),
            "exchange": profile.get("exchange"),
            "ipo_date": profile.get("ipo"),
            "market_cap": profile.get("marketCapitalization"),
            "website": profile.get("weburl"),
            "logo": profile.get("logo"),
        }
    except Exception:
        result["profile"] = {"error": "Failed to fetch Finnhub profile"}

    # Finnhub: analyst recommendations (last 4 months)
    try:
        recs = fh.recommendation_trends(symbol)
        result["analyst_recommendations"] = recs[:4] if recs else []
    except Exception:
        result["analyst_recommendations"] = []

    # Finnhub: insider transactions (last 3 months)
    try:
        today = datetime.now()
        three_months_ago = today - timedelta(days=90)
        insider = fh.stock_insider_transactions(
            symbol=symbol,
            _from=three_months_ago.strftime("%Y-%m-%d"),
            to=today.strftime("%Y-%m-%d"),
        )
        txns = insider.get("data", [])[:10]
        result["insider_transactions"] = [
            {
                "name": t.get("name"),
                "share": t.get("share"),
                "change": t.get("change"),
                "transaction_type": t.get("transactionType"),
                "filing_date": t.get("filingDate"),
            }
            for t in txns
        ]
    except Exception:
        result["insider_transactions"] = []

    # yfinance: financials, balance sheet, cash flow, holders
    try:
        ticker = yf.Ticker(symbol)

        # Annual financials (last 4 years)
        fin = ticker.financials
        if fin is not None and not fin.empty:
            result["annual_financials"] = {
                str(col.date()): {
                    "total_revenue": _safe_float(fin.loc["Total Revenue", col]) if "Total Revenue" in fin.index else None,
                    "net_income": _safe_float(fin.loc["Net Income", col]) if "Net Income" in fin.index else None,
                    "operating_income": _safe_float(fin.loc["Operating Income", col]) if "Operating Income" in fin.index else None,
                }
                for col in fin.columns[:4]
            }
        else:
            result["annual_financials"] = {}

        # Quarterly financials (last 4 quarters)
        qfin = ticker.quarterly_financials
        if qfin is not None and not qfin.empty:
            result["quarterly_financials"] = {
                str(col.date()): {
                    "total_revenue": _safe_float(qfin.loc["Total Revenue", col]) if "Total Revenue" in qfin.index else None,
                    "net_income": _safe_float(qfin.loc["Net Income", col]) if "Net Income" in qfin.index else None,
                }
                for col in qfin.columns[:4]
            }
        else:
            result["quarterly_financials"] = {}

        # Balance sheet
        bs = ticker.balance_sheet
        if bs is not None and not bs.empty:
            latest = bs.columns[0]
            result["balance_sheet"] = {
                "date": str(latest.date()),
                "total_assets": _safe_float(bs.loc["Total Assets", latest]) if "Total Assets" in bs.index else None,
                "total_debt": _safe_float(bs.loc["Total Debt", latest]) if "Total Debt" in bs.index else None,
                "cash_and_equivalents": _safe_float(bs.loc["Cash And Cash Equivalents", latest]) if "Cash And Cash Equivalents" in bs.index else None,
                "stockholders_equity": _safe_float(bs.loc["Stockholders Equity", latest]) if "Stockholders Equity" in bs.index else None,
            }
        else:
            result["balance_sheet"] = {}

        # Cash flow
        cf = ticker.cashflow
        if cf is not None and not cf.empty:
            latest = cf.columns[0]
            result["cash_flow"] = {
                "date": str(latest.date()),
                "operating_cf": _safe_float(cf.loc["Operating Cash Flow", latest]) if "Operating Cash Flow" in cf.index else None,
                "free_cf": _safe_float(cf.loc["Free Cash Flow", latest]) if "Free Cash Flow" in cf.index else None,
                "capex": _safe_float(cf.loc["Capital Expenditure", latest]) if "Capital Expenditure" in cf.index else None,
            }
        else:
            result["cash_flow"] = {}

        # Major holders
        try:
            holders = ticker.major_holders
            if holders is not None and not holders.empty:
                result["major_holders"] = {
                    str(row.iloc[1]).strip(): str(row.iloc[0]).strip()
                    for _, row in holders.iterrows()
                }
            else:
                result["major_holders"] = {}
        except Exception:
            result["major_holders"] = {}

    except Exception as e:
        result["yfinance_error"] = str(e)

    return result



def sector_analysis(period: Literal["1mo", "3mo", "6mo", "1y"] = "3mo") -> dict:
    """Analyze sector performance and rotation signals.

    Fetches sector ETFs + SPY/QQQ, computes returns, RSI, and rotation signals.

    Args:
        period: Lookback period — "1mo", "3mo", "6mo", or "1y".

    Returns:
        Sector rankings, rotation signal, and market context.
    """
    etf_symbols = list(SECTOR_ETFS.keys()) + ["SPY", "QQQ"]

    try:
        data = yf.download(etf_symbols, period=period, progress=False, threads=True)
    except Exception as e:
        return {"error": f"Failed to download sector data: {e}"}

    if data.empty:
        return {"error": "No sector data returned"}

    close = data["Close"]

    # Compute metrics for each ETF
    spy_return = float(close["SPY"].iloc[-1] / close["SPY"].iloc[0] - 1)
    sectors = []

    for etf, name in SECTOR_ETFS.items():
        if etf not in close.columns:
            continue
        series = close[etf].dropna()
        if len(series) < 14:
            continue

        total_return = float(series.iloc[-1] / series.iloc[0] - 1)
        relative_perf = total_return - spy_return

        # RSI
        daily_ret = series.pct_change().dropna()
        gain = daily_ret.clip(lower=0).rolling(14).mean().iloc[-1]
        loss = (-daily_ret.clip(upper=0)).rolling(14).mean().iloc[-1]
        rsi_val = 100 - (100 / (1 + gain / loss)) if loss != 0 else 50

        # Above/below 50-day SMA
        sma_50 = series.rolling(50).mean().iloc[-1] if len(series) >= 50 else series.mean()
        above_sma50 = bool(series.iloc[-1] > sma_50)

        sectors.append({
            "etf": etf,
            "sector": name,
            "total_return": round(total_return, 4),
            "relative_to_spy": round(relative_perf, 4),
            "rsi": round(float(rsi_val), 1),
            "above_sma50": above_sma50,
        })

    # Sort by return
    sectors.sort(key=lambda x: x["total_return"], reverse=True)

    # Rotation signal
    cyclical_avg = _avg_return(sectors, CYCLICAL_SECTORS)
    defensive_avg = _avg_return(sectors, DEFENSIVE_SECTORS)

    if cyclical_avg > defensive_avg + 0.02:
        rotation_signal = "risk-on"
    elif defensive_avg > cyclical_avg + 0.02:
        rotation_signal = "risk-off"
    else:
        rotation_signal = "neutral"

    # QQQ and SPY returns
    qqq_return = float(close["QQQ"].iloc[-1] / close["QQQ"].iloc[0] - 1) if "QQQ" in close.columns else None

    return {
        "period": period,
        "spy_return": round(spy_return, 4),
        "qqq_return": round(qqq_return, 4) if qqq_return is not None else None,
        "rotation_signal": rotation_signal,
        "cyclical_avg_return": round(cyclical_avg, 4),
        "defensive_avg_return": round(defensive_avg, 4),
        "leading_sectors": [s["sector"] for s in sectors[:3]],
        "lagging_sectors": [s["sector"] for s in sectors[-3:]],
        "sectors": sectors,
    }



def peer_comparison(symbol: str, peers: list[str] | None = None) -> dict:
    """Compare a stock against its industry peers on key metrics.

    Args:
        symbol: Target stock ticker.
        peers: Optional list of peer tickers. If None, auto-discovers via Finnhub.

    Returns:
        Comparison table with percentile rankings.
    """
    # Auto-discover peers if not provided
    if not peers:
        try:
            fh = get_finnhub()
            peers = fh.company_peers(symbol)
            # Remove the target itself and limit to 8 peers
            peers = [p for p in peers if p != symbol][:8]
        except Exception:
            peers = []

    if not peers:
        return {"error": f"No peers found for {symbol}", "symbol": symbol}

    all_symbols = [symbol] + peers
    comparisons = []

    for sym in all_symbols:
        try:
            info = yf.Ticker(sym).info
            comparisons.append({
                "symbol": sym,
                "name": info.get("longName", sym),
                "market_cap": info.get("marketCap"),
                "pe_ratio": info.get("trailingPE"),
                "forward_pe": info.get("forwardPE"),
                "revenue_growth": info.get("revenueGrowth"),
                "profit_margin": info.get("profitMargins"),
                "roe": info.get("returnOnEquity"),
                "debt_to_equity": info.get("debtToEquity"),
            })
        except Exception:
            continue

    if len(comparisons) < 2:
        return {"error": "Not enough peer data", "symbol": symbol}

    # Compute 3-month price changes
    try:
        price_data = yf.download(all_symbols, period="3mo", progress=False, threads=True)
        close = price_data["Close"]
        for comp in comparisons:
            sym = comp["symbol"]
            if sym in close.columns:
                series = close[sym].dropna()
                if len(series) > 1:
                    comp["return_3m"] = round(float(series.iloc[-1] / series.iloc[0] - 1), 4)
    except Exception:
        pass

    # Compute percentile rankings for the target
    target = next((c for c in comparisons if c["symbol"] == symbol), None)
    if target:
        rank_metrics = ["pe_ratio", "forward_pe", "revenue_growth", "profit_margin", "roe", "return_3m"]
        # For P/E and debt: lower is better (invert ranking)
        lower_is_better = {"pe_ratio", "forward_pe", "debt_to_equity"}

        percentiles = {}
        for metric in rank_metrics:
            vals = [(c["symbol"], c.get(metric)) for c in comparisons if c.get(metric) is not None]
            if len(vals) < 2:
                continue
            vals.sort(key=lambda x: x[1], reverse=(metric not in lower_is_better))
            target_rank = next((i for i, v in enumerate(vals) if v[0] == symbol), None)
            if target_rank is not None:
                percentiles[metric] = round((1 - target_rank / (len(vals) - 1)) * 100, 0) if len(vals) > 1 else 50

        target["percentile_rankings"] = percentiles

    return {
        "symbol": symbol,
        "peer_count": len(peers),
        "peers": peers,
        "comparisons": comparisons,
    }



def earnings_calendar(symbols: list[str] | None = None, days_ahead: int = 30) -> dict:
    """Check upcoming earnings and recent earnings surprises.

    Args:
        symbols: Tickers to check. If None, uses watchlist + current positions.
        days_ahead: How many days to look ahead (default 30).

    Returns:
        Upcoming earnings dates, recent surprises, and alerts.
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

    fh = get_finnhub()
    today = datetime.now()
    end_date = today + timedelta(days=days_ahead)

    upcoming = []
    recent_surprises = []

    # Track which symbols Finnhub returned dates for so we can fallback
    symbols_with_dates: set[str] = set()

    for sym in symbols:
        # Upcoming earnings — try Finnhub first
        try:
            cal = fh.earnings_calendar(
                _from=today.strftime("%Y-%m-%d"),
                to=end_date.strftime("%Y-%m-%d"),
                symbol=sym,
            )
            for entry in cal.get("earningsCalendar", []):
                days_until = (datetime.strptime(entry["date"], "%Y-%m-%d") - today).days
                upcoming.append({
                    "symbol": entry.get("symbol", sym),
                    "date": entry.get("date"),
                    "days_until": days_until,
                    "eps_estimate": entry.get("epsEstimate"),
                    "revenue_estimate": entry.get("revenueEstimate"),
                    "hour": entry.get("hour", "unknown"),
                })
                symbols_with_dates.add(sym)
        except Exception:
            pass

    # Fallback: use yfinance for symbols Finnhub missed
    for sym in symbols:
        if sym in symbols_with_dates:
            continue
        try:
            ticker = yf.Ticker(sym)
            cal_dates = ticker.calendar
            if cal_dates is not None and not (hasattr(cal_dates, "empty") and cal_dates.empty):
                # yfinance returns calendar as a dict or DataFrame depending on version
                earnings_date = None
                if isinstance(cal_dates, dict):
                    raw = cal_dates.get("Earnings Date", [])
                    earnings_date = raw[0] if raw else None
                elif hasattr(cal_dates, "loc"):
                    try:
                        raw = cal_dates.loc["Earnings Date"]
                        earnings_date = raw.iloc[0] if hasattr(raw, "iloc") else raw
                    except (KeyError, IndexError):
                        pass

                if earnings_date is not None:
                    from pandas import Timestamp
                    if isinstance(earnings_date, Timestamp):
                        earnings_date = earnings_date.to_pydatetime()
                    if isinstance(earnings_date, datetime):
                        days_until = (earnings_date - today).days
                        if 0 <= days_until <= days_ahead:
                            upcoming.append({
                                "symbol": sym,
                                "date": earnings_date.strftime("%Y-%m-%d"),
                                "days_until": days_until,
                                "eps_estimate": None,
                                "revenue_estimate": None,
                                "hour": "unknown",
                            })
                            symbols_with_dates.add(sym)
                            logger.info("yfinance fallback found earnings for %s on %s", sym, earnings_date.strftime("%Y-%m-%d"))
        except Exception:
            pass

        # Historical earnings surprises (last 4 quarters)
        try:
            earnings = fh.company_earnings(sym, limit=4)
            for e in earnings:
                if e.get("actual") is not None and e.get("estimate") is not None:
                    surprise_pct = ((e["actual"] - e["estimate"]) / abs(e["estimate"]) * 100) if e["estimate"] != 0 else 0
                    recent_surprises.append({
                        "symbol": sym,
                        "period": e.get("period"),
                        "actual_eps": e.get("actual"),
                        "estimated_eps": e.get("estimate"),
                        "surprise_pct": round(surprise_pct, 1),
                    })
        except Exception:
            pass

    # Sort upcoming by date
    upcoming.sort(key=lambda x: x.get("days_until", 999))

    # Flag earnings within 5 days
    imminent = [e for e in upcoming if e.get("days_until", 999) <= 5]

    # Persist upcoming earnings to memory so the web UI calendar can display them.
    # Merge with existing events (keyed by symbol) so that symbols not queried this
    # run aren't dropped. Prune events whose date has already passed.
    try:
        existing_mem = read_memory("upcoming_earnings")
        existing_events: list[dict] = []
        if existing_mem and existing_mem.get("value"):
            existing_events = existing_mem["value"].get("events", [])

        # Build a map keyed by symbol — new results overwrite stale ones
        today_str = today.strftime("%Y-%m-%d")
        merged: dict[str, dict] = {}
        for ev in existing_events:
            sym_key = ev.get("symbol", "")
            # Drop events whose date has passed
            if ev.get("date", "") >= today_str and sym_key:
                merged[sym_key] = ev
        for ev in upcoming:
            sym_key = ev.get("symbol", "")
            if sym_key:
                merged[sym_key] = ev

        merged_list = sorted(merged.values(), key=lambda x: x.get("date", "9999"))
        db_write_memory("upcoming_earnings", {
            "events": merged_list,
            "fetched_at": today.strftime("%Y-%m-%d %H:%M"),
        })
    except Exception:
        logger.warning("Failed to persist upcoming_earnings to memory")

    return {
        "symbols_checked": symbols,
        "upcoming_earnings": upcoming,
        "imminent_earnings": imminent,
        "recent_surprises": recent_surprises,
    }



def eps_estimates(symbol: str, freq: str = "quarterly") -> dict:
    """Get consensus EPS estimates and revision trends for a stock.

    Shows forward-looking analyst EPS estimates by period, including high/low
    range and analyst count. Use this to detect estimate revisions — rising
    estimates are a strong bullish signal, falling estimates are bearish.

    Args:
        symbol: Ticker symbol (e.g. "NVDA").
        freq: "quarterly" or "annual" (default "quarterly").

    Returns:
        Dict with current estimates, revision direction, and analyst coverage.
    """
    fh = get_finnhub()

    try:
        data = fh.company_eps_estimates(symbol, freq=freq)
    except Exception as e:
        return {"error": f"Failed to fetch EPS estimates for {symbol}: {e}"}

    estimates = data.get("data", [])
    if not estimates:
        return {"symbol": symbol, "freq": freq, "estimates": [], "note": "No estimates available"}

    # Build structured output
    results = []
    for est in estimates:
        results.append({
            "period": est.get("period"),
            "quarter": est.get("quarter"),
            "year": est.get("year"),
            "eps_avg": est.get("epsAvg"),
            "eps_high": est.get("epsHigh"),
            "eps_low": est.get("epsLow"),
            "num_analysts": est.get("numberAnalysts"),
        })

    # Detect revision trend: compare consecutive quarterly estimates
    # If next quarter estimate > current quarter estimate, that's growth
    revision_signal = None
    if len(results) >= 2:
        curr = results[0].get("eps_avg")
        nxt = results[1].get("eps_avg")
        if curr is not None and nxt is not None:
            if nxt > curr:
                revision_signal = "rising"
            elif nxt < curr:
                revision_signal = "falling"
            else:
                revision_signal = "flat"

    return {
        "symbol": symbol,
        "freq": freq,
        "estimates": results[:8],  # Cap at 8 periods
        "revision_signal": revision_signal,
        "total_periods": len(results),
    }



def market_breadth() -> dict:
    """Assess overall market health using breadth indicators.

    Computes advance/decline ratio, % above 50/200-day SMA from a representative
    sample of large-caps, and determines market regime.

    Returns:
        Market regime assessment, breadth metrics, and sector performance.
    """
    # Representative large-cap sample across sectors
    sample = [
        "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "AVGO", "ORCL", "CRM",  # Tech
        "JPM", "BAC", "GS", "MS", "V",  # Financials
        "UNH", "JNJ", "LLY", "PFE", "ABT",  # Health Care
        "XOM", "CVX", "COP", "SLB", "EOG",  # Energy
        "CAT", "HON", "UPS", "RTX", "DE",  # Industrials
        "PG", "KO", "PEP", "COST", "WMT",  # Consumer Staples
        "HD", "MCD", "NKE", "SBUX", "TJX",  # Consumer Discretionary
        "NEE", "DUK", "SO", "D", "AEP",  # Utilities
        "AMT", "PLD", "CCI", "EQIX", "SPG",  # Real Estate
        "LIN", "APD", "SHW", "ECL", "FCX",  # Materials
    ]

    try:
        data = yf.download(sample, period="1y", progress=False, threads=True)
    except Exception as e:
        return {"error": f"Failed to download breadth data: {e}"}

    if data.empty:
        return {"error": "No breadth data returned"}

    close = data["Close"]

    above_sma50 = 0
    above_sma200 = 0
    advancing = 0
    declining = 0
    total = 0

    for sym in sample:
        if sym not in close.columns:
            continue
        series = close[sym].dropna()
        if len(series) < 50:
            continue

        total += 1
        price = series.iloc[-1]

        sma50 = series.rolling(50).mean().iloc[-1]
        if price > sma50:
            above_sma50 += 1

        if len(series) >= 200:
            sma200 = series.rolling(200).mean().iloc[-1]
            if price > sma200:
                above_sma200 += 1

        # 20-day change for advance/decline
        if len(series) >= 20:
            change_20d = price / series.iloc[-20] - 1
            if change_20d > 0:
                advancing += 1
            else:
                declining += 1

    pct_above_50 = round(above_sma50 / total * 100, 1) if total else 0
    pct_above_200 = round(above_sma200 / total * 100, 1) if total else 0
    ad_ratio = round(advancing / declining, 2) if declining > 0 else float(advancing)

    # Determine regime
    if pct_above_50 > 70 and pct_above_200 > 60 and ad_ratio > 1.5:
        regime = "Healthy bull"
    elif pct_above_50 > 50 and pct_above_200 > 50:
        regime = "Moderate uptrend"
    elif pct_above_50 < 30 and pct_above_200 < 40:
        regime = "Broad weakness"
    elif pct_above_50 < 50 and pct_above_200 > 50:
        regime = "Transitional — near-term weakness in longer-term uptrend"
    elif pct_above_50 > 50 and pct_above_200 < 50:
        regime = "Transitional — near-term recovery in longer-term downtrend"
    else:
        regime = "Mixed / Choppy"

    return {
        "regime": regime,
        "stocks_sampled": total,
        "pct_above_sma50": pct_above_50,
        "pct_above_sma200": pct_above_200,
        "advance_decline_ratio": ad_ratio,
        "advancing_20d": advancing,
        "declining_20d": declining,
    }



def _safe_float(val) -> float | None:
    """Safely convert a value to float."""
    try:
        if pd.isna(val):
            return None
        return round(float(val), 2)
    except (TypeError, ValueError):
        return None


