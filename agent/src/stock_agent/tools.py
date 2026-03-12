"""Stock Agent tools — autonomous-mode and chat-mode."""

import logging
import os
from datetime import datetime, timedelta
from typing import Literal

import time

import pandas as pd
import yfinance as yf
from alpaca.trading.requests import MarketOrderRequest, LimitOrderRequest, TakeProfitRequest, StopLossRequest
from alpaca.trading.enums import OrderSide, TimeInForce, OrderClass
from tavily import TavilyClient

from langgraph_sdk import get_sync_client

from stock_agent.alpaca_client import get_trading_client
from stock_agent.db import (
    add_to_watchlist,
    create_trade,
    get_trades,
    get_watchlist,
    read_journal,
    read_memory,
    remove_from_watchlist,
    update_trade,
    write_journal as db_write_journal,
    write_memory as db_write_memory,
    read_all_memory,
    record_equity_snapshot as db_record_equity_snapshot,
    get_equity_snapshots,
    get_risk_settings,
)
from stock_agent.finnhub_client import get_finnhub
from stock_agent.market_data import (
    get_historical_bars,
    get_historical_data_dict,
    get_portfolio,
    get_quote,
    get_sp500_sp400_tickers,
)
from stock_agent.risk import check_risk
from stock_agent.supabase_client import get_supabase
from stock_agent.technical import compute_indicators

logger = logging.getLogger(__name__)

# --- Factor scoring cache ---
_factor_cache: dict = {"data": None, "timestamp": 0.0}
_FACTOR_CACHE_TTL = 14400  # 4 hours

# Sector ETF mapping for sector_analysis and market_breadth
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

    for sym in symbols:
        # Upcoming earnings
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

    # Persist upcoming earnings to memory so the web UI calendar can display them
    if upcoming:
        try:
            db_write_memory("upcoming_earnings", {
                "events": upcoming,
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


def place_order(
    symbol: str,
    side: Literal["buy", "sell"],
    quantity: float,
    order_type: Literal["market", "limit"] = "market",
    limit_price: float | None = None,
    thesis: str | None = None,
    confidence: float | None = None,
    take_profit_price: float | None = None,
    stop_loss_price: float | None = None,
    composite_score: float | None = None,
) -> dict:
    """Place a trade order via Alpaca paper trading, optionally as a bracket order.

    IMPORTANT: Always run check_trade_risk first. This tool should only be called
    from the autonomous loop, never from chat mode.

    Order type selection (when using factor-based scoring):
    - composite_score > 80 → Market order (get the fill)
    - composite_score 70-80 → Limit 1% below current price
    - composite_score 60-70 → Limit 3% below current price

    When composite_score is provided and order_type/limit_price are not explicitly
    set, the order type is auto-derived from the composite score.

    For buy orders, if stop_loss_price is not provided, a default 5% stop-loss
    is auto-calculated from the entry price.

    Args:
        symbol: Stock ticker symbol.
        side: "buy" or "sell".
        quantity: Number of shares.
        order_type: "market" or "limit".
        limit_price: Required if order_type is "limit".
        thesis: The reasoning behind this trade.
        confidence: Confidence score 0.0-1.0, or composite_score/100.
        take_profit_price: Target exit price for take-profit leg.
        stop_loss_price: Stop price for stop-loss leg.
        composite_score: Factor composite score (0-100). When provided, auto-derives
            order_type and limit_price based on score thresholds.

    Returns:
        Dict with order details and trade record.
    """
    # Auto-derive order type from composite score for buys
    if composite_score is not None and side == "buy" and limit_price is None:
        if composite_score > 80:
            order_type = "market"
        else:
            order_type = "limit"
            quote = get_quote(symbol)
            current = float(quote.get("last_price", 0))
            if current > 0:
                if composite_score >= 70:
                    limit_price = round(current * 0.99, 2)  # 1% below
                else:
                    limit_price = round(current * 0.97, 2)  # 3% below

        # Set confidence from composite if not provided
        if confidence is None:
            confidence = round(composite_score / 100, 2)
    # Risk check
    risk = check_risk(symbol, side, quantity, limit_price)
    if not risk["approved"]:
        return {"error": f"Risk check failed: {risk['reason']}", "risk": risk}

    # Determine if bracket order
    is_bracket = take_profit_price is not None or stop_loss_price is not None

    # Auto-derive stop-loss for buys if not provided but take-profit is
    if is_bracket and side == "buy" and stop_loss_price is None:
        risk_settings = get_risk_settings()
        stop_pct = risk_settings.get("default_stop_loss_pct", 5.0) / 100
        ref_price = limit_price if limit_price else get_quote(symbol).get("last_price", 0)
        stop_loss_price = round(ref_price * (1 - stop_pct), 2)

    # Build order kwargs
    order_kwargs = {
        "symbol": symbol,
        "qty": quantity,
        "side": OrderSide.BUY if side == "buy" else OrderSide.SELL,
    }

    if is_bracket:
        order_kwargs["order_class"] = OrderClass.BRACKET
        order_kwargs["time_in_force"] = TimeInForce.GTC
        if take_profit_price is not None:
            order_kwargs["take_profit"] = TakeProfitRequest(limit_price=take_profit_price)
        if stop_loss_price is not None:
            order_kwargs["stop_loss"] = StopLossRequest(stop_price=stop_loss_price)
    else:
        order_kwargs["time_in_force"] = TimeInForce.DAY

    if order_type == "limit" and limit_price is not None:
        order_kwargs["limit_price"] = limit_price
        request = LimitOrderRequest(**order_kwargs)
    else:
        request = MarketOrderRequest(**order_kwargs)

    # Place order with Alpaca
    client = get_trading_client()
    order = client.submit_order(request)

    # Record in database
    order_class_str = "bracket" if is_bracket else "simple"
    trade = create_trade(
        symbol=symbol,
        side=side,
        quantity=quantity,
        order_type=order_type,
        limit_price=limit_price,
        thesis=thesis,
        confidence=confidence,
        take_profit_price=take_profit_price,
        stop_loss_price=stop_loss_price,
        order_class=order_class_str,
    )

    # Update with broker order ID
    update_trade(trade["id"], {
        "broker_order_id": str(order.id),
        "status": str(order.status),
    })

    # Poll for fill (up to 10s for market orders, skip for limit)
    filled_avg_price = None
    filled_qty = None
    final_status = str(order.status)
    if order_type == "market":
        for _ in range(5):
            time.sleep(2)
            try:
                refreshed = client.get_order_by_id(str(order.id))
                final_status = str(refreshed.status)
                if refreshed.filled_avg_price is not None:
                    filled_avg_price = float(refreshed.filled_avg_price)
                    filled_qty = float(refreshed.filled_qty)
                    update_trade(trade["id"], {
                        "status": final_status,
                        "filled_avg_price": filled_avg_price,
                        "filled_quantity": filled_qty,
                    })
                    break
            except Exception:
                pass

    return {
        "trade_id": trade["id"],
        "broker_order_id": str(order.id),
        "symbol": symbol,
        "side": side,
        "quantity": quantity,
        "order_type": order_type,
        "order_class": order_class_str,
        "status": final_status,
        "filled_avg_price": filled_avg_price,
        "filled_quantity": filled_qty,
        "take_profit_price": take_profit_price,
        "stop_loss_price": stop_loss_price,
        "risk_metrics": risk.get("metrics", {}),
    }


def cancel_order(
    trade_id: str,
    reason: str | None = None,
) -> dict:
    """Cancel an open/accepted order on Alpaca and update the trade record.

    Use this to clean up orders that were placed prematurely, no longer align
    with your thesis, or that you regret after reflection.

    Args:
        trade_id: The trade UUID from the trades table (NOT the broker_order_id).
        reason: Why you're cancelling — logged for accountability.

    Returns:
        Dict with cancellation status.
    """
    # Look up the trade to get broker_order_id
    sb = get_supabase()
    result = sb.table("trades").select("*").eq("id", trade_id).maybe_single().execute()
    if not result.data:
        return {"error": f"Trade {trade_id} not found"}

    trade = result.data
    broker_order_id = trade.get("broker_order_id")
    if not broker_order_id:
        return {"error": "No broker_order_id — trade may not have been submitted to Alpaca"}

    # Check if already terminal
    status = (trade.get("status") or "").lower()
    if "filled" in status or "cancelled" in status or "canceled" in status:
        return {"error": f"Order already in terminal state: {trade.get('status')}"}

    # Cancel on Alpaca
    client = get_trading_client()
    try:
        client.cancel_order_by_id(broker_order_id)
    except Exception as e:
        error_msg = str(e)
        # If Alpaca says it's already done, update our record
        if "already" in error_msg.lower() or "not found" in error_msg.lower():
            update_trade(trade_id, {"status": "cancelled", "thesis": f"{trade.get('thesis', '')} | CANCELLED: {reason or 'no reason'}"})
            return {"status": "already_terminal", "message": error_msg}
        return {"error": f"Failed to cancel on Alpaca: {error_msg}"}

    # Update our trade record
    updated_thesis = trade.get("thesis", "") or ""
    if reason:
        updated_thesis = f"{updated_thesis} | CANCELLED: {reason}"

    update_trade(trade_id, {
        "status": "cancelled",
        "thesis": updated_thesis.strip(),
    })

    # Write a journal entry to track the cancellation for accountability
    cancel_summary = (
        f"**Cancelled order**: {trade.get('side', '').upper()} "
        f"{trade.get('quantity')} {trade.get('symbol')}\n\n"
        f"**Original thesis**: {trade.get('thesis', 'N/A')}\n\n"
        f"**Reason for cancellation**: {reason or 'No reason given'}\n\n"
        f"**Order was placed**: {trade.get('created_at', 'unknown')}\n"
        f"**Confidence at placement**: {trade.get('confidence', 'N/A')}"
    )
    cancel_title = f"Cancelled {trade.get('side', '').upper()} {trade.get('symbol')}"
    if reason:
        # Truncate reason in title to keep it readable
        short_reason = reason[:60] + "..." if len(reason) > 60 else reason
        cancel_title = f"{cancel_title} — {short_reason}"

    try:
        db_write_journal(
            entry_type="trade",
            title=cancel_title,
            content=cancel_summary,
            symbols=[trade.get("symbol")] if trade.get("symbol") else None,
        )
    except Exception:
        logger.warning("Failed to write cancellation journal entry for %s", trade_id)

    return {
        "status": "cancelled",
        "trade_id": trade_id,
        "symbol": trade.get("symbol"),
        "side": trade.get("side"),
        "quantity": str(trade.get("quantity")),
        "reason": reason,
    }


def get_open_orders() -> dict:
    """Get all open/accepted orders that haven't been filled or cancelled.

    Use this at the start of execution phase to review pending orders
    and decide whether to keep or cancel them.

    Returns:
        List of open trades with their details.
    """
    sb = get_supabase()
    result = (
        sb.table("trades")
        .select("*")
        .not_.is_("broker_order_id", "null")
        .or_("status.ilike.%accepted%,status.ilike.%new%,status.ilike.%pending%,status.ilike.%partially_filled%")
        .order("created_at", desc=True)
        .execute()
    )

    open_trades = result.data or []

    # Also check current status on Alpaca for each
    client = get_trading_client()
    enriched = []
    for trade in open_trades:
        broker_id = trade.get("broker_order_id")
        alpaca_status = None
        if broker_id:
            try:
                order = client.get_order_by_id(broker_id)
                alpaca_status = str(order.status)
                # Sync status if it changed
                if alpaca_status != trade.get("status"):
                    update_trade(trade["id"], {"status": alpaca_status})
                    trade["status"] = alpaca_status
            except Exception:
                alpaca_status = "unknown (API error)"

        enriched.append({
            "trade_id": trade["id"],
            "symbol": trade.get("symbol"),
            "side": trade.get("side"),
            "quantity": str(trade.get("quantity")),
            "order_type": trade.get("order_type"),
            "limit_price": str(trade.get("limit_price")) if trade.get("limit_price") else None,
            "status": trade.get("status"),
            "alpaca_status": alpaca_status,
            "thesis": trade.get("thesis"),
            "confidence": str(trade.get("confidence")),
            "created_at": trade.get("created_at"),
        })

    return {
        "open_orders": enriched,
        "count": len(enriched),
    }


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


def get_portfolio_state() -> dict:
    """Get the current portfolio state from Alpaca.

    Returns:
        Dict with equity, cash, positions, and P&L.
    """
    return get_portfolio()


def check_trade_risk(
    symbol: str,
    side: Literal["buy", "sell"],
    quantity: float,
    limit_price: float | None = None,
) -> dict:
    """Check if a proposed trade passes risk management rules.

    Args:
        symbol: Stock ticker.
        side: "buy" or "sell".
        quantity: Number of shares.
        limit_price: Optional limit price.

    Returns:
        Dict with 'approved' bool and risk metrics.
    """
    return check_risk(symbol, side, quantity, limit_price)


# ============================================================
# Chat-mode tools (read-only access to agent's brain)
# ============================================================

def get_my_portfolio() -> dict:
    """Show the agent's current portfolio holdings and P&L from Alpaca.

    Returns:
        Portfolio with equity, cash, positions.
    """
    return get_portfolio()


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

def _safe_float(val) -> float | None:
    """Safely convert a value to float."""
    try:
        if pd.isna(val):
            return None
        return round(float(val), 2)
    except (TypeError, ValueError):
        return None


def _avg_return(sectors: list[dict], etf_set: set[str]) -> float:
    """Average return for a set of sector ETFs."""
    vals = [s["total_return"] for s in sectors if s["etf"] in etf_set]
    return sum(vals) / len(vals) if vals else 0.0


def send_daily_recap() -> dict:
    """Send a daily trade recap to the chat tab for the user to read.

    Creates a new thread on the chat graph and triggers a run that queries
    today's journal entries and generates a concise recap. The recap appears
    as a new conversation in the chat tab.

    Call this at the very end of the 4 PM reflection phase (weekdays only).

    Returns:
        Dict with thread_id and status.
    """
    today = datetime.now().strftime("%A, %B %-d")

    recap_prompt = (
        f"Today is {today}. Generate a daily recap for sharing.\n\n"
        "Query today's journal entries and trades:\n"
        "```sql\n"
        "SELECT entry_type, title, content, symbols, created_at\n"
        "FROM agent_journal WHERE created_at >= CURRENT_DATE ORDER BY created_at\n"
        "```\n"
        "```sql\n"
        "SELECT symbol, side, quantity, order_type, limit_price, status, thesis, confidence\n"
        "FROM trades WHERE created_at >= CURRENT_DATE ORDER BY created_at\n"
        "```\n\n"
        "Write a SHORT recap (aim for ~150 words). This will be screenshotted and shared.\n"
        "Format:\n"
        "1. **Market** — regime, VIX, sector rotation (1-2 sentences)\n"
        "2. **Research** — what you analyzed and key findings (2-3 sentences)\n"
        "3. **Trades** — what you bought/sold/passed on and why (1-2 sentences)\n"
        "4. **Watching** — 2-3 tickers and what you're waiting for\n\n"
        "No self-reflection, no improvement notes, no verbose explanations. "
        "Be punchy and specific — numbers, tickers, prices. "
        "Think investor newsletter, not diary entry."
    )

    try:
        langgraph_url = os.environ.get(
            "LANGGRAPH_URL",
            "https://monet-0f211e9ce05255c2a85f92d6847873b5.us.langgraph.app",
        )
        api_key = os.environ.get("LANGGRAPH_API_KEY") or os.environ.get("LANGSMITH_API_KEY")
        client = get_sync_client(url=langgraph_url, api_key=api_key)
        # Owner must match the frontend user's Supabase ID so the thread
        # appears in their chat conversation list.
        owner_id = os.environ.get("RECAP_OWNER_ID", "593fa090-4515-4a02-a79b-8462c7266999")
        thread = client.threads.create(
            metadata={"title": f"Daily Recap — {today}", "owner": owner_id},
        )
        client.runs.create(
            thread["thread_id"],
            assistant_id="monet_agent",
            input={"messages": [
                {"role": "system", "content": recap_prompt},
                {"role": "user", "content": f"Give me today's daily recap ({today})."},
            ]},
        )
        return {
            "thread_id": thread["thread_id"],
            "status": "recap_triggered",
            "message": f"Daily recap thread created. It will appear in the chat tab shortly.",
        }
    except Exception as e:
        logger.error(f"Failed to send daily recap: {e}")
        return {"status": "error", "error": str(e)}


# ============================================================
# Bracket / Position Protection tools
# ============================================================

def attach_bracket_to_position(
    symbol: str,
    quantity: float,
    stop_loss_price: float,
    take_profit_price: float | None = None,
) -> dict:
    """Attach protective stop-loss and take-profit orders to an existing position.

    Use this to protect positions that were opened without bracket orders,
    or to update stops on positions that have appreciated (trailing stop).

    Places an OCO (one-cancels-other) sell order: one leg is a stop at
    stop_loss_price, the other is a limit at take_profit_price.
    If only stop_loss_price is provided, places a simple stop order.

    Args:
        symbol: Stock ticker with an existing long position.
        quantity: Number of shares to protect (usually full position size).
        stop_loss_price: Stop price — triggers a market sell if hit.
        take_profit_price: Limit price for take-profit leg. If None, places stop-only.

    Returns:
        Dict with order details.
    """
    client = get_trading_client()

    if take_profit_price is not None:
        # OCO: stop-loss + take-profit
        # Alpaca OCO requires a limit order with take_profit and stop_loss
        request = LimitOrderRequest(
            symbol=symbol,
            qty=quantity,
            side=OrderSide.SELL,
            time_in_force=TimeInForce.GTC,
            order_class=OrderClass.OCO,
            limit_price=take_profit_price,
            take_profit=TakeProfitRequest(limit_price=take_profit_price),
            stop_loss=StopLossRequest(stop_price=stop_loss_price),
        )
    else:
        # Simple stop order
        from alpaca.trading.requests import StopOrderRequest
        request = StopOrderRequest(
            symbol=symbol,
            qty=quantity,
            side=OrderSide.SELL,
            time_in_force=TimeInForce.GTC,
            stop_price=stop_loss_price,
        )

    order = client.submit_order(request)

    # Record in trades table
    order_class_str = "oco" if take_profit_price else "stop"
    trade = create_trade(
        symbol=symbol,
        side="sell",
        quantity=quantity,
        order_type="stop" if take_profit_price is None else "oco",
        take_profit_price=take_profit_price,
        stop_loss_price=stop_loss_price,
        order_class=order_class_str,
        thesis=f"Protective order: SL={stop_loss_price}" + (f", TP={take_profit_price}" if take_profit_price else ""),
    )
    update_trade(trade["id"], {
        "broker_order_id": str(order.id),
        "status": str(order.status),
    })

    return {
        "trade_id": trade["id"],
        "broker_order_id": str(order.id),
        "symbol": symbol,
        "order_class": order_class_str,
        "stop_loss_price": stop_loss_price,
        "take_profit_price": take_profit_price,
        "status": str(order.status),
    }


# ============================================================
# Performance Tracking tools
# ============================================================

def record_daily_snapshot() -> dict:
    """Record today's portfolio equity and SPY close for benchmark tracking.

    Call this during EOD reflection (4 PM ET) to log a daily data point.
    Cumulative returns vs SPY are auto-computed from the first snapshot (inception).

    Returns:
        Dict with today's snapshot including portfolio return, SPY return, and alpha.
    """
    portfolio = get_portfolio()
    equity = float(portfolio.get("equity", 0))
    cash = float(portfolio.get("cash", 0))

    spy_quote = get_quote("SPY")
    # get_quote returns bid/ask, use midpoint as proxy for close
    bid = float(spy_quote.get("bid_price", 0))
    ask = float(spy_quote.get("ask_price", 0))
    spy_close = round((bid + ask) / 2, 2) if bid and ask else float(spy_quote.get("last_price", 0))

    today = datetime.now().strftime("%Y-%m-%d")
    snapshot = db_record_equity_snapshot(today, equity, cash, spy_close)

    return {
        "date": today,
        "portfolio_equity": equity,
        "spy_close": spy_close,
        "portfolio_cumulative_return": snapshot.get("portfolio_cumulative_return"),
        "spy_cumulative_return": snapshot.get("spy_cumulative_return"),
        "alpha": snapshot.get("alpha"),
    }


def get_performance_comparison(days: int = 30) -> dict:
    """Compare portfolio performance vs SPY over a given period.

    Uses daily equity snapshots recorded by record_daily_snapshot().
    Available in both autonomous and chat modes.

    Args:
        days: Number of days to look back (default 30).

    Returns:
        Dict with portfolio return, SPY return, alpha, max drawdown, and time series.
    """
    snapshots = get_equity_snapshots(days)
    if not snapshots:
        return {"error": "No equity snapshots yet. Snapshots are recorded during EOD reflection."}

    # Snapshots come newest-first, reverse for chronological
    snapshots = list(reversed(snapshots))

    latest = snapshots[-1]
    oldest = snapshots[0]

    # Period return (not cumulative from inception — just this window)
    oldest_equity = float(oldest["portfolio_equity"])
    latest_equity = float(latest["portfolio_equity"])
    oldest_spy = float(oldest["spy_close"])
    latest_spy = float(latest["spy_close"])

    period_portfolio_return = round((latest_equity / oldest_equity - 1) * 100, 2) if oldest_equity else 0
    period_spy_return = round((latest_spy / oldest_spy - 1) * 100, 2) if oldest_spy else 0
    period_alpha = round(period_portfolio_return - period_spy_return, 2)

    # Max drawdown
    peak = 0
    max_dd = 0
    for s in snapshots:
        eq = float(s["portfolio_equity"])
        peak = max(peak, eq)
        dd = (peak - eq) / peak * 100 if peak > 0 else 0
        max_dd = max(max_dd, dd)

    # Time series for charting
    series = [
        {
            "date": s["snapshot_date"],
            "portfolio": float(s.get("portfolio_cumulative_return") or 0),
            "spy": float(s.get("spy_cumulative_return") or 0),
            "alpha": float(s.get("alpha") or 0),
        }
        for s in snapshots
    ]

    return {
        "period_days": len(snapshots),
        "portfolio_return_pct": period_portfolio_return,
        "spy_return_pct": period_spy_return,
        "alpha_pct": period_alpha,
        "max_drawdown_pct": round(max_dd, 2),
        "latest_equity": latest_equity,
        "latest_date": latest["snapshot_date"],
        "cumulative_portfolio_return": float(latest.get("portfolio_cumulative_return") or 0),
        "cumulative_spy_return": float(latest.get("spy_cumulative_return") or 0),
        "cumulative_alpha": float(latest.get("alpha") or 0),
        "series": series,
    }


# ============================================================
# Position Management tools
# ============================================================

def position_health_check(symbol: str) -> dict:
    """Get a structured health report for a held position.

    Returns P&L, days held, distance from stop/target, position weight,
    whether protective orders exist, and DCA eligibility.

    Args:
        symbol: Stock ticker to check.

    Returns:
        Dict with position health metrics.
    """
    portfolio = get_portfolio()
    positions = portfolio.get("positions", [])
    pos = next((p for p in positions if p.get("symbol") == symbol.upper()), None)
    if not pos:
        return {"error": f"No open position in {symbol}"}

    equity = float(portfolio.get("equity", 1))
    current_price = float(pos.get("current_price", 0))
    avg_entry = float(pos.get("avg_entry_price", 0))
    qty = float(pos.get("qty", 0))
    market_value = float(pos.get("market_value", 0))
    unrealized_pnl = float(pos.get("unrealized_pl", 0))
    pnl_pct = float(pos.get("unrealized_plpc", 0)) * 100 if pos.get("unrealized_plpc") else 0

    position_weight = round(market_value / equity * 100, 2) if equity else 0

    # Check stock analysis memory for targets
    stock_mem = read_memory(f"stock:{symbol.upper()}")
    target_entry = None
    target_exit = None
    confidence = None
    if stock_mem and isinstance(stock_mem.get("value"), dict):
        v = stock_mem["value"]
        target_entry = v.get("target_entry")
        target_exit = v.get("target_exit")
        confidence = v.get("confidence")

    # Distance from targets
    dist_to_exit = round((float(target_exit) / current_price - 1) * 100, 2) if target_exit and current_price else None
    dist_from_entry = round((current_price / avg_entry - 1) * 100, 2) if avg_entry else None

    # Check for protective orders
    sb = get_supabase()
    protective = (
        sb.table("trades")
        .select("id, order_class, stop_loss_price, take_profit_price, status")
        .eq("symbol", symbol.upper())
        .eq("side", "sell")
        .or_("status.ilike.%new%,status.ilike.%accepted%,status.ilike.%pending%")
        .execute()
    )
    has_stop_loss = any(
        t.get("stop_loss_price") for t in (protective.data or [])
    )
    has_take_profit = any(
        t.get("take_profit_price") for t in (protective.data or [])
    )

    # DCA eligibility
    risk_settings = get_risk_settings()
    max_pos_pct = risk_settings.get("max_position_pct", 10.0)
    dca_eligible = (
        pnl_pct < -8
        and position_weight < max_pos_pct
        and confidence is not None
        and confidence >= 0.6
    )

    return {
        "symbol": symbol.upper(),
        "quantity": qty,
        "avg_entry_price": avg_entry,
        "current_price": current_price,
        "market_value": market_value,
        "unrealized_pnl": unrealized_pnl,
        "pnl_pct": round(pnl_pct, 2),
        "position_weight_pct": position_weight,
        "dist_from_entry_pct": dist_from_entry,
        "target_exit": target_exit,
        "dist_to_exit_pct": dist_to_exit,
        "has_stop_loss": has_stop_loss,
        "has_take_profit": has_take_profit,
        "protected": has_stop_loss,
        "dca_eligible": dca_eligible,
        "confidence": confidence,
    }


# ============================================================
# Factor-Based Scoring tools
# ============================================================


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
    6. Composite = 0.35*momentum + 0.30*quality + 0.20*value + 0.15*eps_revision (eps starts at 50)
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

    # Step 2: Momentum factor
    # 12-month return excluding last month (classic momentum)
    if len(close) >= 252:
        ret_12m_ex1m = (close.iloc[-22] / close.iloc[0] - 1).dropna()
    else:
        ret_12m_ex1m = (close.iloc[-22] / close.iloc[0] - 1).dropna() if len(close) > 22 else pd.Series(dtype=float)

    # 3-month return
    lookback_3m = min(63, len(close) - 1)
    ret_3m = (close.iloc[-1] / close.iloc[-lookback_3m] - 1).dropna() if lookback_3m > 0 else pd.Series(dtype=float)

    # Combined momentum score: 50% 12m-ex-1m + 50% 3m
    common_syms = ret_12m_ex1m.index.intersection(ret_3m.index)
    if len(common_syms) == 0:
        return {"error": "No valid momentum data", "rankings": []}

    momentum_rank_12m = _percentile_rank(ret_12m_ex1m[common_syms])
    momentum_rank_3m = _percentile_rank(ret_3m[common_syms])
    momentum_score = 0.5 * momentum_rank_12m + 0.5 * momentum_rank_3m

    # Step 3: Pre-filter top ~150 by momentum for fundamental lookups
    top_momentum = momentum_score.nlargest(150)
    candidates = top_momentum.index.tolist()

    # Step 4-6: Fetch fundamentals and compute quality + value factors
    results = []
    sector_fwd_pe: dict[str, list] = {}  # For within-sector value ranking

    for sym in candidates:
        try:
            info = yf.Ticker(sym).info
            sector = info.get("sector", "Unknown")
            fwd_pe = info.get("forwardPE")
            profit_margin = info.get("profitMargins")
            roe = info.get("returnOnEquity")
            de = info.get("debtToEquity")
            current_price = info.get("currentPrice") or info.get("regularMarketPrice")

            results.append({
                "symbol": sym,
                "sector": sector,
                "forward_pe": fwd_pe,
                "profit_margin": profit_margin,
                "roe": roe,
                "debt_to_equity": de,
                "current_price": current_price,
                "return_3m": round(float(ret_3m.get(sym, 0)), 4),
                "return_12m_ex1m": round(float(ret_12m_ex1m.get(sym, 0)), 4),
                "momentum_score": round(float(momentum_score.get(sym, 0)), 1),
            })

            # Track forward P/E by sector for within-sector value ranking
            if fwd_pe and fwd_pe > 0:
                sector_fwd_pe.setdefault(sector, []).append((sym, fwd_pe))

        except Exception:
            continue

    if not results:
        return {"error": "No fundamental data retrieved", "rankings": []}

    # Compute quality factor
    margins = pd.Series({r["symbol"]: r["profit_margin"] for r in results if r["profit_margin"] is not None})
    roes = pd.Series({r["symbol"]: r["roe"] for r in results if r["roe"] is not None})
    leverages = pd.Series({r["symbol"]: r["debt_to_equity"] for r in results if r["debt_to_equity"] is not None})

    margin_rank = _percentile_rank(margins)
    roe_rank = _percentile_rank(roes)
    leverage_rank = _percentile_rank(leverages)

    # Compute within-sector value factor (lower forward P/E = higher value)
    value_scores: dict[str, float] = {}
    for sector, pe_list in sector_fwd_pe.items():
        if len(pe_list) < 2:
            for sym, _ in pe_list:
                value_scores[sym] = 50.0  # Not enough peers
            continue
        syms, pes = zip(*pe_list)
        pe_series = pd.Series(pes, index=syms)
        # Invert: lower P/E = higher score
        value_rank = 100 - _percentile_rank(pe_series)
        for s in syms:
            if s in value_rank.index and not pd.isna(value_rank[s]):
                value_scores[s] = round(float(value_rank[s]), 1)

    # Assemble final scores
    factor_weights = {"momentum": 0.35, "quality": 0.30, "value": 0.20, "eps_revision": 0.15}

    for r in results:
        sym = r["symbol"]
        # Quality: 0.4*margin + 0.4*roe + 0.2*(100-leverage)
        m_rank = float(margin_rank.get(sym, 50))
        r_rank = float(roe_rank.get(sym, 50))
        l_rank = float(leverage_rank.get(sym, 50))
        quality = 0.4 * m_rank + 0.4 * r_rank + 0.2 * (100 - l_rank)

        value = value_scores.get(sym, 50.0)
        mom = r["momentum_score"]
        eps_rev = 50.0  # Default — enriched later by enrich_eps_revisions

        composite = (
            factor_weights["momentum"] * mom
            + factor_weights["quality"] * quality
            + factor_weights["value"] * value
            + factor_weights["eps_revision"] * eps_rev
        )

        r["quality_score"] = round(quality, 1)
        r["value_score"] = round(value, 1)
        r["eps_revision_score"] = eps_rev
        r["composite_score"] = round(composite, 1)

    # Sort by composite, take top
    results.sort(key=lambda x: x["composite_score"], reverse=True)

    # Add rank
    for i, r in enumerate(results):
        r["rank"] = i + 1

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

    return {
        **cache_payload,
        "rankings": results[:top_n],
        "cached": False,
    }


def enrich_eps_revisions(symbols: list[str]) -> dict:
    """Enrich top-ranked stocks with EPS revision scores from Finnhub.

    For each symbol, fetches quarterly EPS estimates and scores based on
    revision direction:
    - Rising revisions → 70-85
    - Flat → 50
    - Falling revisions → 15-30

    Respects Finnhub free tier rate limit (60 calls/min) with built-in delays.

    Args:
        symbols: List of ticker symbols to enrich (recommended: top 20).

    Returns:
        Dict with enriched list of symbols and their EPS revision scores.
    """
    fh = get_finnhub()
    enriched = []

    for i, sym in enumerate(symbols[:20]):  # Hard cap at 20 for rate limiting
        if i > 0:
            time.sleep(1)  # Finnhub free tier: 60 calls/min, pace at 1/sec

        try:
            # Retry once on 403 (rate limit) with backoff
            try:
                data = fh.company_eps_estimates(sym, freq="quarterly")
            except Exception as retry_err:
                if "403" in str(retry_err):
                    time.sleep(5)  # Back off on rate limit
                    data = fh.company_eps_estimates(sym, freq="quarterly")
                else:
                    raise retry_err
            estimates = data.get("data", [])

            if len(estimates) >= 2:
                curr = estimates[0].get("epsAvg")
                nxt = estimates[1].get("epsAvg")

                if curr is not None and nxt is not None:
                    if nxt > curr * 1.03:
                        # Rising revisions
                        pct_change = (nxt - curr) / abs(curr) if curr != 0 else 0
                        score = min(85, 70 + pct_change * 100)
                        signal = "rising"
                    elif nxt < curr * 0.97:
                        # Falling revisions
                        pct_change = (curr - nxt) / abs(curr) if curr != 0 else 0
                        score = max(15, 30 - pct_change * 100)
                        signal = "falling"
                    else:
                        score = 50.0
                        signal = "flat"
                else:
                    score = 50.0
                    signal = "no_data"

                next_q_eps = estimates[0].get("epsAvg")
            else:
                score = 50.0
                signal = "insufficient_data"
                next_q_eps = None

            enriched.append({
                "symbol": sym,
                "eps_revision_score": round(score, 1),
                "revision_signal": signal,
                "next_quarter_eps_avg": next_q_eps,
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

    # Factor weights (matching score_universe defaults)
    weights = {"momentum": 0.35, "quality": 0.30, "value": 0.20, "eps_revision": 0.15}

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


# ============================================================
# Tool collections for each mode
# ============================================================

AUTONOMOUS_TOOLS = [
    internet_search,
    get_stock_quote,
    get_historical_data,
    technical_analysis,
    fundamental_analysis,
    screen_stocks,
    company_profile,
    sector_analysis,
    peer_comparison,
    earnings_calendar,
    eps_estimates,
    market_breadth,
    place_order,
    cancel_order,
    get_open_orders,
    attach_bracket_to_position,
    read_agent_memory,
    read_all_agent_memory,
    write_agent_memory,
    write_journal_entry,
    manage_watchlist,
    get_portfolio_state,
    check_trade_risk,
    query_database,
    send_daily_recap,
    update_market_regime,
    update_stock_analysis,
    record_decision,
    record_daily_snapshot,
    get_performance_comparison,
    position_health_check,
    check_watchlist_alerts,
    # Factor-based scoring tools
    score_universe,
    enrich_eps_revisions,
    generate_factor_rankings,
]

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


CHAT_TOOLS = [
    internet_search,
    get_stock_quote,
    get_my_portfolio,
    query_database,
    company_profile,
    sector_analysis,
    peer_comparison,
    market_breadth,
    eps_estimates,
    submit_user_insight,
    get_performance_comparison,
]
