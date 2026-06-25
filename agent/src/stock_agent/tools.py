"""Stock Agent tools — autonomous-mode and chat-mode."""

import html
import logging
import os
from datetime import datetime, timedelta
from typing import Literal

import time

import httpx
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
        price_data = yf.download(tickers, period="3mo", progress=False, threads=True, auto_adjust=True)
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
        data = yf.download(etf_symbols, period=period, progress=False, threads=True, auto_adjust=True)
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
        price_data = yf.download(all_symbols, period="3mo", progress=False, threads=True, auto_adjust=True)
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
        data = yf.download(sample, period="1y", progress=False, threads=True, auto_adjust=True)
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
    portfolio: str = "quant",
    risk_overrides: dict | None = None,
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
        portfolio: Which book to trade in — "quant" (default, Quant Core systematic
            strategy) or "conviction" (concentrated cyclical book on its own Alpaca
            account). Routes the order, risk check, and trade record to that book.
        risk_overrides: Optional dict merged over default risk settings (e.g. the
            Conviction book passes {"max_position_pct": 40, "max_total_exposure_pct": 95}).

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
    risk = check_risk(symbol, side, quantity, limit_price, portfolio=portfolio, risk_overrides=risk_overrides)
    if not risk["approved"]:
        return {"error": f"Risk check failed: {risk['reason']}", "risk": risk}

    # Determine if bracket order
    is_bracket = take_profit_price is not None or stop_loss_price is not None

    # Auto-derive stop-loss for buys if not provided but take-profit is.
    # Uses 2x ATR(14) clamped to [3%, 8%], falling back to fixed 5% if ATR unavailable.
    # Promoted from backtest variant short_mom_atr (v1.4) which reduced stop-hit
    # rate from 55% → 35% vs the fixed-5% baseline.
    if is_bracket and side == "buy" and stop_loss_price is None:
        risk_settings = get_risk_settings()
        fallback_pct = risk_settings.get("default_stop_loss_pct", 5.0) / 100
        ref_price = limit_price if limit_price else get_quote(symbol).get("last_price", 0)

        stop_pct = fallback_pct
        try:
            from .factor_scoring import BASELINE_VARIANT
            if BASELINE_VARIANT.stop_method == "atr" and ref_price > 0:
                # Fetch 30d of OHLC for ATR calculation
                bars = get_historical_data(symbol, period="1mo")
                if isinstance(bars, list) and len(bars) >= 15:
                    df = pd.DataFrame(bars)
                    high = df["high"] if "high" in df.columns else df.get("High")
                    low = df["low"] if "low" in df.columns else df.get("Low")
                    close = df["close"] if "close" in df.columns else df.get("Close")
                    if high is not None and low is not None and close is not None:
                        prev_close = close.shift(1)
                        tr = pd.concat([
                            high - low,
                            (high - prev_close).abs(),
                            (low - prev_close).abs(),
                        ], axis=1).max(axis=1)
                        atr = tr.rolling(14).mean().iloc[-1]
                        if pd.notna(atr) and atr > 0:
                            atr_pct = float(atr) / float(ref_price)
                            stop_pct = min(
                                BASELINE_VARIANT.atr_max_pct,
                                max(BASELINE_VARIANT.atr_min_pct,
                                    atr_pct * BASELINE_VARIANT.atr_multiplier),
                            )
        except Exception as e:
            logger.warning("ATR stop calc failed for %s (%s); using fallback %.1f%%",
                           symbol, e, fallback_pct * 100)

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
    client = get_trading_client(portfolio)
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
        portfolio=portfolio,
    )

    # Update with broker order ID
    update_trade(trade["id"], {
        "broker_order_id": str(order.id),
        "status": str(order.status),
    })

    # Clear re-entry guard if this was a stopped symbol
    if side == "buy":
        try:
            from stock_agent.db import delete_memory

            delete_memory(f"stopped:{symbol}")
        except Exception:
            pass

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

    # Cancel on Alpaca — route to the account that owns this trade
    client = get_trading_client(trade.get("portfolio", "quant"))
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

    # Also check current status on Alpaca for each (route by owning portfolio)
    enriched = []
    for trade in open_trades:
        broker_id = trade.get("broker_order_id")
        alpaca_status = None
        if broker_id:
            try:
                client = get_trading_client(trade.get("portfolio", "quant"))
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


def _recent_split(symbol: str, ref_date_str: str, window_days: int = 4) -> float | None:
    """Return the split ratio if `symbol` split within ±window_days of ref_date, else None.

    Used to recognize when a 'stop fill' is actually a stock-split artifact: a paper
    broker can adjust a position's price for a split without multiplying the share
    count, making a held position look like it crashed ~1/ratio and tripping the stop.
    """
    try:
        sp = yf.Ticker(symbol).splits
        if sp is None or len(sp) == 0:
            return None
        ref = datetime.strptime(ref_date_str[:10], "%Y-%m-%d").date()
        for dt, ratio in sp.items():
            d = dt.date() if hasattr(dt, "date") else dt
            if ratio and ratio != 1 and abs((d - ref).days) <= window_days:
                return float(ratio)
    except Exception:
        return None
    return None


def _splits_in_window(symbol: str, window_days: int) -> list[tuple[str, float]]:
    """List of (date_str, ratio) for `symbol` splits within the last window_days."""
    try:
        sp = yf.Ticker(symbol).splits
        if sp is None or len(sp) == 0:
            return []
        cutoff = (datetime.now() - timedelta(days=window_days)).date()
        out = []
        for dt, ratio in sp.items():
            d = dt.date() if hasattr(dt, "date") else dt
            if d >= cutoff and ratio and ratio != 1:
                out.append((d.isoformat(), float(ratio)))
        return out
    except Exception:
        return []


def adjust_for_corporate_actions(window_days: int = 14) -> dict:
    """Daily corporate-actions hygiene — keep stored prices consistent across splits.

    Run at the START of the factor loop. Two jobs:

    1. **Stored targets** — for each `stock:*` and `watchlist` symbol that split in the
       last `window_days`, divide the stored target_entry/target_exit by the split
       ratio so price comparisons (alerts, decision gates) aren't off by ~the ratio
       (e.g. a 10:1 split making a $217 stock read as 90% below a $2173 target).

    2. **Held positions** — if a held name split in the window, flag it so its broker
       stop can be re-checked. (A phantom stop fill is handled by the split-artifact
       guard in reconcile_positions; this flags it proactively.)

    Idempotent: each `SYMBOL:date` split is applied once, tracked in the
    `splits_processed` memory key, so repeated daily runs never double-adjust.

    Returns a summary of adjustments + flags.
    """
    sb = get_supabase()
    pr = read_memory("splits_processed")
    processed: set[str] = set((pr or {}).get("value", {}).get("keys", [])) if pr else set()
    newly_processed: set[str] = set()
    adjusted: list[dict] = []
    flags: list[dict] = []

    def _pending_splits(symbol: str) -> list[tuple[str, float]]:
        return [(d, r) for (d, r) in _splits_in_window(symbol, window_days) if f"{symbol}:{d}" not in processed]

    # ── 1a. stock:* memory targets ──
    try:
        stock_rows = sb.table("agent_memory").select("key,value").like("key", "stock:%").execute().data or []
    except Exception:
        stock_rows = []
    for row in stock_rows:
        val = row.get("value") or {}
        sym = val.get("symbol") or row["key"].split(":", 1)[-1]
        pending = _pending_splits(sym)
        if not pending:
            continue
        ratio = 1.0
        for d, r in pending:
            ratio *= r
            newly_processed.add(f"{sym}:{d}")
        new_val = dict(val)
        for f in ("target_entry", "target_exit"):
            if isinstance(val.get(f), (int, float)):
                new_val[f] = round(val[f] / ratio, 2)
        new_val["thesis"] = (new_val.get("thesis") or "") + f" [auto-adjusted for {ratio:g}:1 split]"
        try:
            db_write_memory(row["key"], new_val)
            adjusted.append({"symbol": sym, "ratio": ratio, "source": "stock_memory"})
        except Exception:
            pass

    # ── 1b. watchlist targets ──
    try:
        wl = sb.table("watchlist").select("id,symbol,target_entry,target_exit").execute().data or []
    except Exception:
        wl = []
    for w in wl:
        pending = _pending_splits(w["symbol"])
        if not pending:
            continue
        ratio = 1.0
        for d, r in pending:
            ratio *= r
            newly_processed.add(f"{w['symbol']}:{d}")
        updates = {f: round(w[f] / ratio, 2) for f in ("target_entry", "target_exit") if isinstance(w.get(f), (int, float))}
        if updates:
            try:
                sb.table("watchlist").update(updates).eq("id", w["id"]).execute()
                adjusted.append({"symbol": w["symbol"], "ratio": ratio, "source": "watchlist"})
            except Exception:
                pass

    # ── 2. Held positions that split recently (informational flag) ──
    for slug in ("quant", "conviction"):
        try:
            positions = get_portfolio(slug).get("positions", [])
        except Exception:
            positions = []
        for pos in positions:
            for d, r in _splits_in_window(pos["symbol"], window_days):
                flags.append({
                    "symbol": pos["symbol"], "portfolio": slug, "ratio": r, "date": d,
                    "note": "Held name split recently — verify its protective stop is split-adjusted.",
                })

    # Persist the processed set so future runs don't re-adjust
    if newly_processed:
        all_keys = sorted(processed | newly_processed)[-500:]  # cap growth
        try:
            db_write_memory("splits_processed", {"keys": all_keys})
        except Exception:
            pass

    return {
        "status": "ok",
        "adjusted_targets": adjusted,
        "split_flags": flags,
        "message": (
            f"Adjusted {len(adjusted)} stored target(s) for splits; "
            f"{len(flags)} held position(s) flagged for stop review."
        ),
    }


def reconcile_positions(portfolio: str = "quant") -> dict:
    """Reconcile Alpaca positions against trades table to detect bracket stop-loss/take-profit fills.

    Call this at the start of every factor loop and EOD reflection. It compares
    Alpaca's live positions to the trades table and detects positions that were
    closed by bracket orders (stop-loss or take-profit) without the agent knowing.

    portfolio: which book to reconcile — "quant" (default) or "conviction". Only
        that portfolio's Alpaca account and its own trade rows are considered, so
        the two books never cross-contaminate each other's ghost detection.

    For each detected exit:
    - Updates the protective sell order in trades table to 'filled'
    - Creates a new 'sell' trade record with the fill details
    - Writes a journal entry noting the bracket execution

    Returns:
        Dict with reconciled exits and any errors.
    """
    from alpaca.trading.requests import GetOrdersRequest
    from alpaca.trading.enums import QueryOrderStatus

    client = get_trading_client(portfolio)
    sb = get_supabase()

    # 1. Get live Alpaca positions
    live_positions = client.get_all_positions()
    live_symbols = {pos.symbol for pos in live_positions}

    # 2. Find symbols we think we hold (open buy fills) but Alpaca says we don't
    open_buys = (
        sb.table("trades")
        .select("symbol, broker_order_id, quantity, filled_avg_price, created_at")
        .eq("side", "buy")
        .eq("portfolio", portfolio)
        .or_("status.ilike.%filled%,status.ilike.%FILLED%")
        .order("created_at", desc=True)
        .execute()
    ).data or []

    # Deduplicate: for each symbol, get the most recent filled buy
    bought_symbols: dict[str, dict] = {}
    for t in open_buys:
        sym = t["symbol"]
        if sym not in bought_symbols:
            bought_symbols[sym] = t

    # Also check if there's a corresponding filled sell (manual or bracket)
    filled_sells = (
        sb.table("trades")
        .select("symbol, created_at")
        .eq("side", "sell")
        .eq("portfolio", portfolio)
        .or_("status.ilike.%filled%,status.ilike.%FILLED%")
        .order("created_at", desc=True)
        .execute()
    ).data or []

    # Build set of symbols that have a sell AFTER the latest buy
    sold_symbols: set[str] = set()
    for s in filled_sells:
        sym = s["symbol"]
        if sym in bought_symbols:
            buy_time = bought_symbols[sym]["created_at"]
            if s["created_at"] > buy_time:
                sold_symbols.add(sym)

    # 3. Detect ghost positions: we think we hold it, no sell recorded, but Alpaca says gone
    ghost_symbols = set(bought_symbols.keys()) - live_symbols - sold_symbols
    if not ghost_symbols:
        return {"reconciled": [], "message": "All positions in sync."}

    # 4. For each ghost, query Alpaca for closed orders to find the bracket fill
    reconciled = []
    errors = []
    for sym in ghost_symbols:
        try:
            # Query Alpaca for recent closed/filled orders for this symbol
            request = GetOrdersRequest(
                status=QueryOrderStatus.CLOSED,
                symbols=[sym],
                limit=20,
            )
            orders = client.get_orders(filter=request)

            # Find the most recent filled sell order (the bracket leg)
            fill_order = None
            for o in orders:
                if (
                    str(o.side) == "OrderSide.SELL"
                    and str(o.status) == "OrderStatus.FILLED"
                    and o.filled_avg_price is not None
                ):
                    if fill_order is None or (o.filled_at and (fill_order.filled_at is None or o.filled_at > fill_order.filled_at)):
                        fill_order = o

            if fill_order:
                fill_price = float(fill_order.filled_avg_price)
                fill_qty = float(fill_order.filled_qty)
                entry_price = float(bought_symbols[sym].get("filled_avg_price") or 0)

                # Determine if this was a stop-loss or take-profit
                exit_type = "stop_loss"
                if entry_price > 0 and fill_price > entry_price:
                    exit_type = "take_profit"

                pnl = (fill_price - entry_price) * fill_qty if entry_price > 0 else None

                # Split-artifact guard: if `sym` split right around this fill, the
                # paper broker likely mishandled the split (adjusted price but not
                # share count), tripping the stop on a phantom ~1/ratio drop. Record
                # the exit (the account is real) but DON'T treat it as a genuine stop.
                fill_date = datetime.now().strftime("%Y-%m-%d")
                try:
                    if fill_order.filled_at:
                        fill_date = fill_order.filled_at.date().isoformat()
                except Exception:
                    pass
                split_ratio = _recent_split(sym, fill_date)
                is_split_artifact = bool(split_ratio) and exit_type == "stop_loss"

                exit_label = "split_artifact" if is_split_artifact else exit_type
                exit_thesis = (
                    f"SPLIT ARTIFACT ({split_ratio:g}:1) — paper broker mishandled {sym}'s "
                    f"split; the stop fired on a phantom drop, not a real stop. Sold {fill_qty} "
                    f"@ ${fill_price:.2f}. Re-entry NOT blocked."
                    if is_split_artifact
                    else f"Bracket {exit_type} executed by Alpaca at ${fill_price:.2f}"
                )

                # Record the exit trade
                exit_trade = create_trade(
                    symbol=sym,
                    side="sell",
                    quantity=fill_qty,
                    order_type="market",
                    thesis=exit_thesis,
                    order_class="bracket_fill",
                    portfolio=portfolio,
                )
                update_trade(exit_trade["id"], {
                    "status": "OrderStatus.FILLED",
                    "filled_avg_price": fill_price,
                    "filled_quantity": fill_qty,
                    "broker_order_id": str(fill_order.id),
                })

                # Update the protective order in trades table to filled
                protective_orders = (
                    sb.table("trades")
                    .select("id")
                    .eq("symbol", sym)
                    .eq("side", "sell")
                    .eq("portfolio", portfolio)
                    .or_("order_class.eq.oco,order_class.eq.bracket,order_class.eq.stop")
                    .or_("status.ilike.%new%,status.ilike.%accepted%,status.ilike.%pending%")
                    .execute()
                ).data or []
                for po in protective_orders:
                    update_trade(po["id"], {"status": "OrderStatus.FILLED"})

                reconciled.append({
                    "symbol": sym,
                    "exit_type": exit_label,
                    "split_artifact": is_split_artifact,
                    "split_ratio": split_ratio,
                    "fill_price": fill_price,
                    "fill_qty": fill_qty,
                    "entry_price": entry_price,
                    "pnl": round(pnl, 2) if pnl is not None else None,
                    "alpaca_order_id": str(fill_order.id),
                })

                # Save exit context for re-entry guard (genuine stop-losses only —
                # never block re-entry when the "stop" was a split artifact).
                if exit_type == "stop_loss" and not is_split_artifact:
                    regime_data = read_memory("market_regime")
                    regime_snapshot = {}
                    if regime_data and regime_data.get("value"):
                        rv = regime_data["value"]
                        regime_snapshot = {
                            "vix": rv.get("vix"),
                            "breadth_pct": rv.get("breadth_pct"),
                        }
                    db_write_memory(f"stopped:{sym}", {
                        "symbol": sym,
                        "exit_price": fill_price,
                        "entry_price": entry_price,
                        "exit_date": datetime.now().strftime("%Y-%m-%d"),
                        "regime_at_exit": regime_snapshot,
                    })
            else:
                errors.append({
                    "symbol": sym,
                    "error": "Position gone from Alpaca but no filled sell order found",
                })
        except Exception as e:
            errors.append({"symbol": sym, "error": str(e)})

    # 5. Write journal entry if any exits detected
    if reconciled:
        lines = ["## Bracket Exits Detected (Reconciliation)", ""]
        for r in reconciled:
            pnl_str = f"${r['pnl']:+,.2f}" if r['pnl'] is not None else "unknown"
            lines.append(
                f"- **{r['symbol']}**: {r['exit_type']} at ${r['fill_price']:.2f} "
                f"(entry ${r['entry_price']:.2f}, P&L {pnl_str})"
            )
        db_write_journal(
            entry_type="trade",
            title=f"Bracket exits: {', '.join(r['symbol'] for r in reconciled)}",
            content="\n".join(lines),
            symbols=[r["symbol"] for r in reconciled],
        )

    return {
        "reconciled": reconciled,
        "errors": errors if errors else None,
        "message": f"Detected {len(reconciled)} bracket exit(s), {len(errors)} error(s).",
    }


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


def _fmt_currency(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"${value:,.0f}"


def _fmt_pct(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"{value:+.2f}%"


AI_SEMI_BASKET = {
    "NVDA", "AMD", "AVGO", "MU", "WDC", "AMAT", "LRCX", "STX",
    "TSM", "CRUS", "SMCI", "INTC", "ARM", "MRVL", "QCOM", "TXN",
}


def _rsi(closes: "pd.Series", period: int = 14) -> float:
    """Compute RSI for a price series."""
    delta = closes.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss
    return float((100 - 100 / (1 + rs)).iloc[-1])


def assess_ai_bubble_risk() -> dict:
    """Assess AI/semiconductor sector heat using pure market signals.

    Three components — all derived from market data, not from what Monet holds:

    1. SMH technical overextension (0-40 pts):
       - RSI(14) component: RSI ≤ 65 = 0 pts; 65→85 linearly = 0→20 pts
       - 200-day MA gap component: ≤10% above = 0 pts; 10%→35% = 0→20 pts

    2. AI basket breadth (0-30 pts): % of basket stocks within 10% of 52-week high.
       - ≤50% near highs = 0 pts; 50%→100% linearly = 0→30 pts

    3. Valuation stretch (0-30 pts): bellwether NTM P/E vs pre-AI-boom baseline of 35x.
       - ≤35x = 0 pts; 35x→70x linearly = 0→30 pts
       - Uses NVDA + AMD forward P/E, but only values in a sane [20x, 120x] band
         (yfinance forwardPE is unreliable for these names); blends both when valid.

    Returns:
        Dict with score (0-100), level, smh_rsi, smh_vs_200ma_pct,
        basket_breadth_pct, nvda_forward_pe, action, and as_of timestamp.
    """
    score = 0

    # --- Component 1: SMH technical overextension (0-40 pts) ---
    smh_rsi: float = 0.0
    smh_vs_200ma_pct: float = 0.0
    try:
        end = datetime.now()
        start = end - timedelta(days=300)  # enough for 200-day MA + RSI warmup
        smh_hist = yf.download(
            "SMH",
            start=start.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
            progress=False,
            auto_adjust=True,
        )["Close"].squeeze()

        smh_rsi = round(_rsi(smh_hist), 1)
        ma200 = float(smh_hist.rolling(200).mean().iloc[-1])
        current = float(smh_hist.iloc[-1])
        smh_vs_200ma_pct = round((current / ma200 - 1) * 100, 1)

        # RSI sub-score: 0 below 65, linear 65→85 = 0→20
        rsi_pts = min(20, max(0, round((smh_rsi - 65) / 20 * 20)))
        # 200MA gap sub-score: 0 below 10%, linear 10%→35% = 0→20
        ma_pts = min(20, max(0, round((smh_vs_200ma_pct - 10) / 25 * 20)))
        score += rsi_pts + ma_pts
    except Exception:
        pass

    # --- Component 2: Basket breadth — % near 52-week highs (0-30 pts) ---
    basket_breadth_pct: float = 0.0
    try:
        end = datetime.now()
        start = end - timedelta(days=370)  # 52-week window + buffer
        basket_hist = yf.download(
            list(AI_SEMI_BASKET),
            start=start.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
            progress=False,
            auto_adjust=True,
        )["Close"]

        near_high_count = 0
        valid_count = 0
        for sym in AI_SEMI_BASKET:
            if sym not in basket_hist.columns:
                continue
            series = basket_hist[sym].dropna()
            if len(series) < 20:
                continue
            valid_count += 1
            high_52w = float(series.max())
            current_price = float(series.iloc[-1])
            if current_price >= high_52w * 0.90:  # within 10% of 52-week high
                near_high_count += 1

        if valid_count > 0:
            basket_breadth_pct = round(near_high_count / valid_count * 100, 1)
            # Linear: 50%→100% = 0→30 pts
            breadth_pts = min(30, max(0, round((basket_breadth_pct - 50) / 50 * 30)))
            score += breadth_pts
    except Exception:
        pass

    # --- Component 3: Valuation stretch — bellwether NTM P/E vs 35x baseline (0-30 pts) ---
    # yfinance's forwardPE is noisy for these names — NVDA in particular prints
    # implausibly low values (e.g. ~15x while trailing is ~30x). Only trust a P/E
    # inside a sane band, and blend NVDA + AMD when both qualify so a single bad
    # print can't zero out (or spike) the valuation signal.
    _PE_MIN, _PE_MAX = 20.0, 120.0
    nvda_forward_pe: float | None = None
    valuation_pe_source: list[str] = []
    try:
        pe_inputs: list[float] = []
        for bellwether in ["NVDA", "AMD"]:
            try:
                pe = yf.Ticker(bellwether).info.get("forwardPE")
            except Exception:
                pe = None
            if pe and _PE_MIN <= float(pe) <= _PE_MAX:
                pe_inputs.append(round(float(pe), 1))
                valuation_pe_source.append(bellwether)

        if pe_inputs:
            nvda_forward_pe = round(sum(pe_inputs) / len(pe_inputs), 1)
            # Linear: 35x→70x = 0→30 pts; below 35x = 0
            val_pts = min(30, max(0, round((nvda_forward_pe - 35) / 35 * 30)))
            score += val_pts
    except Exception:
        pass

    # --- Determine level and action ---
    score = min(100, score)
    if score <= 30:
        level = "low"
        action = "Sector heat is low. No constraints on AI/semi BUYs."
    elif score <= 60:
        level = "moderate"
        action = "Sector moderately extended. Note in journal."
    elif score <= 80:
        level = "elevated"
        action = "Sector overheated. Note 'AI sector elevated (score: X)' in Step 5 journal recap."
    else:
        level = "high"
        action = "Sector at high heat. Limit new AI-basket BUYs to 1 this run."

    return {
        "score": score,
        "level": level,
        "smh_rsi": smh_rsi,
        "smh_vs_200ma_pct": smh_vs_200ma_pct,
        "basket_breadth_pct": basket_breadth_pct,
        "nvda_forward_pe": nvda_forward_pe,
        "valuation_pe_source": valuation_pe_source,
        "action": action,
        "as_of": datetime.now().isoformat(),
    }


# ============================================================
# AI Cycle Durability Assessment
# ============================================================

# Stock baskets for each AI infrastructure layer
AI_CYCLE_LAYERS = {
    "Compute": ["NVDA", "AMD", "AVGO", "ARM", "TSM"],
    "Memory": ["MU", "WDC", "STX"],
    "Power": ["ETN", "VRT", "VST"],
    "Networking": ["ANET", "CSCO"],
    "Equipment": ["AMAT", "LRCX", "KLAC"],
}


def assess_ai_cycle_durability() -> dict:
    """Assess AI capex cycle durability — how much runway the buildout has left.

    Companion to assess_ai_bubble_risk (which measures heat/stretch).
    This measures whether the underlying investment cycle is healthy and broadening.

    Five signals, each 0-20 pts = 0-100 total:

    1. Stack breadth (0-20): How many AI stack layers outperform SPY over 3 months?
       5 layers (Compute, Memory, Power, Networking, Equipment) × 4 pts each.

    2. Infra momentum (0-20): Power/cooling plays (ETN, VRT, VST) avg 3-month
       return vs SPY. >0% outperformance starts scoring; 20%+ = full marks.

    3. Memory demand (0-20): MU 3-month return vs SPY as proxy for HBM pricing.
       0% outperformance = 0; 25%+ = full marks.

    4. Equipment demand (0-20): Semi-equipment (AMAT, LRCX, KLAC) avg 3-month
       return vs SPY. 0% = 0; 20%+ = full marks.

    5. Capex signal (0-20): From ai_capex_tracker memory (quarterly manual update).
       accelerating = 20, stable = 12, decelerating = 4, unknown = 10.

    Cycle phases:
      75-100 = "Full Build"  — all layers firing, capex accelerating
      50-74  = "Expanding"   — most layers participating, strong demand
      25-49  = "Maturing"    — narrowing participation, watch for turns
      0-24   = "Cooling"     — cycle winding down, be selective

    Returns:
        Dict with score, phase, layer details, sub-signal values, and as_of.
    """
    import yfinance as yf

    score = 0
    details: dict = {}

    # ── Helper: 3-month return for a list of tickers ──
    end = datetime.now()
    start_3m = end - timedelta(days=95)  # ~3 months with buffer

    def _avg_return(symbols: list[str], period_start=start_3m, period_end=end) -> float | None:
        """Average 3-month return for a basket of symbols. Returns pct or None."""
        try:
            hist = yf.download(
                symbols,
                start=period_start.strftime("%Y-%m-%d"),
                end=period_end.strftime("%Y-%m-%d"),
                progress=False,
                auto_adjust=True,
            )["Close"]
            if len(symbols) == 1:
                hist = hist.to_frame(symbols[0]) if hasattr(hist, "to_frame") else hist
            returns = []
            cols = [symbols[0]] if len(symbols) == 1 else hist.columns
            for sym in cols:
                series = hist[sym].dropna() if sym in hist.columns else hist.dropna()
                if len(series) < 10:
                    continue
                ret = (float(series.iloc[-1]) / float(series.iloc[0]) - 1) * 100
                returns.append(ret)
            return round(sum(returns) / len(returns), 1) if returns else None
        except Exception:
            return None

    # ── SPY benchmark return ──
    spy_return = _avg_return(["SPY"])
    if spy_return is None:
        spy_return = 0.0

    # ── Signal 1: Stack Breadth (0-20 pts) ──
    # 5 layers × 4 pts each for outperforming SPY
    layers_participating = 0
    layer_details: dict[str, dict] = {}
    for layer_name, symbols in AI_CYCLE_LAYERS.items():
        layer_ret = _avg_return(symbols)
        outperforming = layer_ret is not None and layer_ret > spy_return
        layer_details[layer_name] = {
            "return_3m_pct": layer_ret,
            "vs_spy_pct": round(layer_ret - spy_return, 1) if layer_ret is not None else None,
            "participating": outperforming,
        }
        if outperforming:
            layers_participating += 1

    breadth_pts = layers_participating * 4
    score += breadth_pts
    details["stack_breadth"] = {
        "score": breadth_pts,
        "layers_participating": layers_participating,
        "total_layers": len(AI_CYCLE_LAYERS),
        "layers": layer_details,
    }

    # ── Signal 2: Infra Momentum (0-20 pts) ──
    infra_return = _avg_return(AI_CYCLE_LAYERS["Power"])
    infra_vs_spy = round(infra_return - spy_return, 1) if infra_return is not None else 0.0
    infra_pts = min(20, max(0, round(infra_vs_spy / 20 * 20)))
    score += infra_pts
    details["infra_momentum"] = {
        "score": infra_pts,
        "return_3m_pct": infra_return,
        "vs_spy_pct": infra_vs_spy,
        "tickers": AI_CYCLE_LAYERS["Power"],
    }

    # ── Signal 3: Memory Demand (0-20 pts) ──
    mu_return = _avg_return(["MU"])
    mu_vs_spy = round(mu_return - spy_return, 1) if mu_return is not None else 0.0
    memory_pts = min(20, max(0, round(mu_vs_spy / 25 * 20)))
    score += memory_pts
    details["memory_demand"] = {
        "score": memory_pts,
        "mu_return_3m_pct": mu_return,
        "vs_spy_pct": mu_vs_spy,
    }

    # ── Signal 4: Equipment Demand (0-20 pts) ──
    equip_return = _avg_return(AI_CYCLE_LAYERS["Equipment"])
    equip_vs_spy = round(equip_return - spy_return, 1) if equip_return is not None else 0.0
    equip_pts = min(20, max(0, round(equip_vs_spy / 20 * 20)))
    score += equip_pts
    details["equipment_demand"] = {
        "score": equip_pts,
        "return_3m_pct": equip_return,
        "vs_spy_pct": equip_vs_spy,
        "tickers": AI_CYCLE_LAYERS["Equipment"],
    }

    # ── Signal 5: Capex Signal (0-20 pts) ──
    # Read from ai_capex_tracker memory (quarterly manual update by agent/user)
    capex_direction = "unknown"
    capex_detail = "No capex tracker data — update ai_capex_tracker after earnings."
    try:
        sb = get_supabase()
        cap_row = (
            sb.table("agent_memory")
            .select("value")
            .eq("key", "ai_capex_tracker")
            .maybe_single()
            .execute()
        )
        if cap_row.data and cap_row.data.get("value"):
            tracker = cap_row.data["value"]
            capex_direction = tracker.get("guidance_direction", "unknown")
            capex_detail = tracker.get("summary", capex_detail)
    except Exception:
        pass

    capex_scores = {"accelerating": 20, "stable": 12, "decelerating": 4, "unknown": 10}
    capex_pts = capex_scores.get(capex_direction, 10)
    score += capex_pts
    details["capex_signal"] = {
        "score": capex_pts,
        "direction": capex_direction,
        "detail": capex_detail,
    }

    # ── Phase determination ──
    score = min(100, score)
    if score >= 75:
        phase = "full_build"
        outlook = "All layers firing. Cycle has strong runway — new AI infra positions supported."
    elif score >= 50:
        phase = "expanding"
        outlook = "Most layers participating. Cycle healthy — favor picks-and-shovels plays."
    elif score >= 25:
        phase = "maturing"
        outlook = "Participation narrowing. Be selective — prefer leaders with pricing power."
    else:
        phase = "cooling"
        outlook = "Cycle winding down. Avoid new capex-cycle entries — focus on AI software/services."

    result = {
        "score": score,
        "phase": phase,
        "phase_label": phase.replace("_", " ").title(),
        "outlook": outlook,
        "spy_return_3m_pct": spy_return,
        "signals": details,
        "as_of": datetime.now().isoformat(),
    }

    # Persist to agent_memory for dashboard card
    try:
        sb = get_supabase()
        sb.table("agent_memory").upsert(
            {"key": "ai_cycle_durability", "value": result},
            on_conflict="key",
        ).execute()
    except Exception:
        pass

    return result


# ============================================================
# AI Capex Trend — automated capex signal (replaces manual ai_capex_tracker)
# ============================================================

# Demand side: hyperscaler capex IS the AI infrastructure spend. Supply side:
# memory/storage names whose capex tracks the HBM/NAND build.
AI_CAPEX_HYPERSCALERS = ["MSFT", "GOOGL", "AMZN", "META"]
AI_CAPEX_MEMORY = ["MU", "WDC", "SNDK"]


def _quarterly_capex(symbol: str) -> list[tuple[str, float]]:
    """Quarterly capex for a symbol as [(period_end, abs_capex), ...] newest-first.

    Reads yfinance quarterly cash-flow "Capital Expenditure" (reported negative →
    abs). Returns [] on any failure or missing data so one bad ticker never breaks
    the aggregate.
    """
    try:
        qcf = yf.Ticker(symbol).quarterly_cashflow
        if qcf is None or qcf.empty or "Capital Expenditure" not in qcf.index:
            return []
        row = qcf.loc["Capital Expenditure"]
        out: list[tuple[str, float]] = []
        for col in qcf.columns:
            val = row.get(col)
            if val is None or pd.isna(val):
                continue
            period = str(col.date()) if hasattr(col, "date") else str(col)
            out.append((period, abs(float(val))))
        out.sort(key=lambda x: x[0], reverse=True)
        return out
    except Exception:
        return []


def _capex_yoy(series: list[tuple[str, float]]) -> float | None:
    """YoY % using latest quarter vs 4 quarters ago. Needs >=5 quarters."""
    if len(series) < 5 or series[4][1] == 0:
        return None
    return round((series[0][1] / series[4][1] - 1) * 100, 1)


def _capex_qoq(series: list[tuple[str, float]]) -> float | None:
    """QoQ % using latest vs prior quarter. Needs >=2 quarters."""
    if len(series) < 2 or series[1][1] == 0:
        return None
    return round((series[0][1] / series[1][1] - 1) * 100, 1)


def _basket_capex_yoy(symbols: list[str], min_capex: float = 0.5e9) -> tuple[float | None, dict]:
    """Aggregate capex YoY across a basket + per-name detail.

    Aggregate = (sum latest-quarter capex) / (sum year-ago-quarter capex) - 1,
    over names that have >=5 quarters of data AND latest capex >= ``min_capex``.

    The materiality floor guards against incomplete yfinance cash-flow stubs —
    e.g. post-spinoff SanDisk (SNDK) reports ~$40M/quarter for a NAND business,
    which is clearly partial data. Such names are flagged ``immaterial`` (no YoY
    shown) and excluded from the aggregate so they don't pollute the signal.
    """
    per_name: dict[str, dict] = {}
    sum_latest = 0.0
    sum_year_ago = 0.0
    for sym in symbols:
        series = _quarterly_capex(sym)
        if not series:
            per_name[sym] = {"latest": None, "yoy_pct": None, "qoq_pct": None, "period": None}
            continue
        latest = series[0][1]
        if latest < min_capex:
            # Below the materiality floor — treat as an unreliable/immaterial stub.
            per_name[sym] = {
                "latest": round(latest, 0),
                "yoy_pct": None,
                "qoq_pct": None,
                "period": series[0][0],
                "immaterial": True,
            }
            continue
        yoy = _capex_yoy(series)
        per_name[sym] = {
            "latest": round(latest, 0),
            "yoy_pct": yoy,
            "qoq_pct": _capex_qoq(series),
            "period": series[0][0],
        }
        if len(series) >= 5:
            sum_latest += series[0][1]
            sum_year_ago += series[4][1]
    agg = round((sum_latest / sum_year_ago - 1) * 100, 1) if sum_year_ago > 0 else None
    return agg, per_name


def compute_ai_capex_trend(
    forward_guidance_direction: str | None = None,
    forward_guidance_summary: str = "",
) -> dict:
    """Compute the AI-infrastructure capex trend from company financials.

    This automates the previously-manual ``ai_capex_tracker`` memory. It pulls
    quarterly capex from yfinance cash-flow statements for the hyperscalers
    (MSFT, GOOGL, AMZN, META — the demand for AI infra) and the memory/storage
    names (MU, WDC, SNDK — the supply side), computes YoY/QoQ growth, and derives
    a ``guidance_direction`` that ``assess_ai_cycle_durability()`` reads for its
    capex signal.

    Reported capex is backward-looking. To capture FORWARD guidance (where the
    "will it keep increasing" answer lives), the agent should first run an
    internet_search for recent hyperscaler capex-guidance headlines and pass:
        forward_guidance_direction: "raising" | "maintaining" | "cutting"
        forward_guidance_summary: one-line takeaway
    The tool blends this qualitative read with the financial trend.

    Args:
        forward_guidance_direction: Optional agent read of forward capex guidance.
        forward_guidance_summary: Optional one-line summary of that guidance.

    Returns:
        Dict with guidance_direction, hyperscaler_total_yoy, memory_yoy, per_name
        detail, summary, and as_of. Also persisted to agent_memory.ai_capex_tracker.
    """
    hyper_yoy, hyper_detail = _basket_capex_yoy(AI_CAPEX_HYPERSCALERS)
    mem_yoy, mem_detail = _basket_capex_yoy(AI_CAPEX_MEMORY)

    # Financial direction from hyperscaler capex YoY (the headline demand signal).
    if hyper_yoy is None:
        financial_direction = "unknown"
    elif hyper_yoy >= 15:
        financial_direction = "accelerating"
    elif hyper_yoy >= 0:
        financial_direction = "stable"
    else:
        financial_direction = "decelerating"

    # Blend in the agent's forward-guidance read, if provided.
    direction = financial_direction
    fg = (forward_guidance_direction or "").lower().strip()
    if fg == "raising" and financial_direction in ("stable", "unknown"):
        direction = "accelerating"
    elif fg == "raising" and financial_direction == "decelerating":
        direction = "stable"  # conflicting signals → split the difference
    elif fg == "cutting":
        downgrade = {"accelerating": "stable", "stable": "decelerating",
                     "decelerating": "decelerating", "unknown": "decelerating"}
        direction = downgrade[financial_direction]
    # "maintaining" or no guidance → keep the financial direction.

    hyper_str = f"{hyper_yoy:+.0f}%" if hyper_yoy is not None else "n/a"
    mem_str = f"{mem_yoy:+.0f}%" if mem_yoy is not None else "n/a"
    summary = (
        f"Hyperscaler capex YoY {hyper_str}, memory capex YoY {mem_str} → "
        f"{direction}."
    )
    if forward_guidance_summary:
        summary += f" Guidance: {forward_guidance_summary}"

    result = {
        "guidance_direction": direction,           # consumed by assess_ai_cycle_durability
        "financial_direction": financial_direction,
        "hyperscaler_total_yoy": hyper_yoy,
        "memory_yoy": mem_yoy,
        "per_name": {**hyper_detail, **mem_detail},
        "forward_guidance_direction": forward_guidance_direction,
        "forward_guidance_summary": forward_guidance_summary or None,
        "summary": summary,
        "as_of": datetime.now().isoformat(),
    }

    try:
        get_supabase().table("agent_memory").upsert(
            {"key": "ai_capex_tracker", "value": result}, on_conflict="key"
        ).execute()
    except Exception as e:
        logger.warning("Failed to persist ai_capex_tracker: %s", e)

    return result


def record_ai_cycle_snapshot() -> dict:
    """Persist today's AI super-cycle reading to the ai_cycle_snapshots history table.

    Reads the latest assessments from agent_memory (ai_cycle_durability,
    ai_bubble_risk, ai_capex_tracker) and writes one dated row so the AI Cycle
    page can chart the cycle over time. Run AFTER assess_ai_cycle_durability,
    assess_ai_bubble_risk, and compute_ai_capex_trend in the daily refresh.

    Returns:
        Dict with the snapshot row, or {"status": "skipped"} if no cycle data yet.
    """
    sb = get_supabase()

    def _read(key: str) -> dict:
        try:
            row = sb.table("agent_memory").select("value").eq("key", key).maybe_single().execute()
            return (row.data or {}).get("value", {}) if row and row.data else {}
        except Exception:
            return {}

    cycle = _read("ai_cycle_durability")
    bubble = _read("ai_bubble_risk")
    capex = _read("ai_capex_tracker")

    if not cycle:
        return {"status": "skipped", "message": "No ai_cycle_durability yet — run assess_ai_cycle_durability first."}

    layers_participating = (
        cycle.get("signals", {}).get("stack_breadth", {}).get("layers_participating")
    )

    today = datetime.now().strftime("%Y-%m-%d")
    row = {
        "snapshot_date": today,
        "cycle_score": cycle.get("score"),
        "phase": cycle.get("phase"),
        "bubble_score": bubble.get("score"),
        "bubble_level": bubble.get("level"),
        "capex_direction": capex.get("guidance_direction"),
        "hyperscaler_capex_yoy": capex.get("hyperscaler_total_yoy"),
        "memory_capex_yoy": capex.get("memory_yoy"),
        "layers_participating": layers_participating,
        "signals": {
            "cycle_signals": cycle.get("signals"),
            "capex_per_name": capex.get("per_name"),
            "bubble": {k: bubble.get(k) for k in ("smh_rsi", "basket_breadth_pct", "nvda_forward_pe")},
        },
    }
    try:
        sb.table("ai_cycle_snapshots").upsert(row, on_conflict="snapshot_date").execute()
    except Exception as e:
        logger.warning("Failed to record ai_cycle_snapshot: %s", e)
        return {"status": "error", "error": str(e)}

    return {"status": "recorded", **{k: row[k] for k in ("snapshot_date", "cycle_score", "phase", "capex_direction", "hyperscaler_capex_yoy")}}


# Focused AI-infra basket for news (kept tight to limit API calls + stay on-signal):
# hyperscalers (demand) + memory/storage (supply) + key compute/equipment.
AI_INFRA_NEWS_BASKET = [
    "MSFT", "GOOGL", "AMZN", "META",          # hyperscaler demand
    "MU", "WDC", "SNDK", "STX",               # memory / storage supply
    "NVDA", "AVGO", "AMAT", "LRCX",           # compute + equipment
]


def get_ai_infra_news(days: int = 4, per_symbol: int = 5, max_total: int = 40) -> dict:
    """Structured recent news for the AI-infrastructure basket via Finnhub.

    Returns sourced, ticker-tagged headlines (per-name company_news + a little
    general business news) as CANDIDATES for the Cycle Signals curation step — more
    reliable than free-text web search: real source links, no hallucinated
    attribution, dated, tagged to the basket.

    Args:
        days: lookback window for company news (default 4).
        per_symbol: max articles kept per ticker (default 5).
        max_total: cap on returned candidates (default 40), newest first.

    Returns:
        Dict with as_of, count, and items [{symbol, headline, source, url, summary,
        date, related}]. The agent then curates/classifies these into ai_cycle_signals.
    """
    fh = get_finnhub()
    frm = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    to = datetime.now().strftime("%Y-%m-%d")
    seen: set[str] = set()
    items: list[dict] = []

    def _ts(a: dict) -> str | None:
        try:
            return datetime.fromtimestamp(a.get("datetime", 0)).strftime("%Y-%m-%d") if a.get("datetime") else None
        except Exception:
            return None

    for sym in AI_INFRA_NEWS_BASKET:
        try:
            arts = fh.company_news(sym, _from=frm, to=to) or []
        except Exception:
            continue
        for a in arts[:per_symbol]:
            url = a.get("url")
            if not url or url in seen:
                continue
            seen.add(url)
            items.append({
                "symbol": sym,
                "headline": a.get("headline"),
                "source": a.get("source"),
                "url": url,
                "summary": (a.get("summary") or "")[:240],
                "date": _ts(a),
                "related": a.get("related"),
            })

    try:
        for a in (fh.general_news("general") or [])[:10]:
            url = a.get("url")
            if not url or url in seen:
                continue
            seen.add(url)
            items.append({
                "symbol": None, "headline": a.get("headline"), "source": a.get("source"),
                "url": url, "summary": (a.get("summary") or "")[:240], "date": _ts(a), "related": a.get("related"),
            })
    except Exception:
        pass

    items.sort(key=lambda x: x.get("date") or "", reverse=True)
    items = items[:max_total]
    return {"as_of": datetime.now().isoformat(), "count": len(items), "items": items}


# ============================================================
# Conviction portfolio — concentrated cyclical position sizing
# ============================================================

CONVICTION_TIERS = {"high": 0.40, "medium": 0.30, "starter": 0.20}
CONVICTION_RISK_OVERRIDES = {"max_position_pct": 40, "max_total_exposure_pct": 95}


def size_cycle_position(symbol: str, conviction: str = "medium", portfolio: str = "conviction") -> dict:
    """Size a concentrated Conviction-book position with a wide cyclical stop.

    The Conviction book holds 1-3 names, each sized 20-40% of the book by
    conviction tier. Because memory/AI-infra cyclicals are volatile, the
    protective stop is intentionally WIDER than Quant Core's [3%,8%] — ~3x
    ATR(14) clamped to [10%, 20%] — so ordinary swings don't shake you out
    before the capex-cycle thesis plays out. The take-profit is generous (~3:1
    reward:risk) so the bracket is valid without capping the ride; the
    conviction-loop's hard exit rules manage the real exit.

    Args:
        symbol: Ticker to size.
        conviction: "high" (40% of book), "medium" (30%), or "starter" (20%).
        portfolio: book to size against (default "conviction").

    Returns:
        Dict with quantity, target_pct, current_price, stop_loss_price,
        take_profit_price, stop_pct, and a rationale. Feed stop_loss_price +
        take_profit_price straight into:
          place_order(symbol, "buy", quantity, take_profit_price=...,
                      stop_loss_price=..., portfolio="conviction",
                      risk_overrides=CONVICTION_RISK_OVERRIDES)
    """
    tier = (conviction or "medium").lower().strip()
    target_pct = CONVICTION_TIERS.get(tier, CONVICTION_TIERS["medium"])

    port = get_portfolio(portfolio)
    equity = float(port.get("equity", 0))
    cash = float(port.get("cash", 0))
    if equity <= 0:
        return {"error": f"{portfolio} account equity is zero — cannot size."}

    quote = get_quote(symbol)
    price = float(quote.get("ask_price") or quote.get("price") or quote.get("bid_price") or 0)

    # Wide ATR-based stop for a cyclical: ~3x ATR(14), clamped [10%, 20%].
    stop_pct = 0.15  # fallback if ATR unavailable
    try:
        df = get_historical_bars(symbol, days=90)
        if df is not None and len(df) >= 15:
            high, low, close = df["high"], df["low"], df["close"]
            if price <= 0:
                price = float(close.iloc[-1])
            prev_close = close.shift(1)
            tr = pd.concat(
                [high - low, (high - prev_close).abs(), (low - prev_close).abs()],
                axis=1,
            ).max(axis=1)
            atr = tr.rolling(14).mean().iloc[-1]
            if pd.notna(atr) and atr > 0 and price > 0:
                stop_pct = min(0.20, max(0.10, float(atr) / price * 3.0))
    except Exception as e:
        logger.warning("ATR stop calc failed for %s (%s); using %.0f%% fallback", symbol, e, stop_pct * 100)

    if price <= 0:
        return {"error": f"No valid price for {symbol}."}

    target_dollars = min(equity * target_pct, cash)
    quantity = int(target_dollars // price)
    if quantity < 1:
        return {
            "error": (
                f"Insufficient cash in {portfolio}: {symbol} is ${price:.0f}/share, "
                f"target ${equity * target_pct:.0f} ({round(target_pct*100)}% of book), "
                f"cash ${cash:.0f}."
            )
        }

    stop_loss_price = round(price * (1 - stop_pct), 2)
    take_profit_price = round(price * (1 + stop_pct * 3), 2)

    return {
        "symbol": symbol,
        "portfolio": portfolio,
        "conviction": tier,
        "target_pct": round(target_pct * 100, 1),
        "quantity": quantity,
        "target_dollars": round(quantity * price, 2),
        "current_price": round(price, 2),
        "stop_pct": round(stop_pct * 100, 1),
        "stop_loss_price": stop_loss_price,
        "take_profit_price": take_profit_price,
        "book_equity": round(equity, 2),
        "book_cash": round(cash, 2),
        "risk_overrides": CONVICTION_RISK_OVERRIDES,
        "rationale": (
            f"{tier} conviction → {round(target_pct*100)}% of ${equity:,.0f} book "
            f"= {quantity} sh @ ${price:.2f}. Wide {round(stop_pct*100,1)}% cyclical "
            f"stop (3x ATR) at ${stop_loss_price}, TP ${take_profit_price}."
        ),
    }


# ============================================================
# Tier 1 Monitoring: Factor IC drift + live vs backtest divergence
# ============================================================

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
    from .factor_scoring import (
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
    from .factor_scoring import BASELINE_VARIANT

    sb = get_supabase()
    today = datetime.now().date()
    thirty_days_ago = today - timedelta(days=30)

    result: dict = {"as_of": today.isoformat()}

    # 1. Live 30-day alpha from equity_snapshots
    try:
        snaps = (
            sb.table("equity_snapshots")
            .select("snapshot_date, portfolio_cumulative_return, spy_cumulative_return")
            .eq("portfolio", "quant")  # divergence is for the Quant Core factor strategy
            .gte("snapshot_date", thirty_days_ago.isoformat())
            .order("snapshot_date", desc=False)
            .execute()
        )
        rows = snaps.data or []
        if len(rows) < 5:
            return {"status": "insufficient_data", "message": f"Only {len(rows)} live snapshots in past 30d"}

        # One-time corporate-action corrections (quant) — add back so a broker artifact
        # (e.g. KLAC split) doesn't distort the live-vs-backtest divergence.
        try:
            _pa = sb.table("agent_memory").select("value").eq("key", "performance_adjustments").maybe_single().execute()
            _adjs = [a for a in ((_pa.data or {}).get("value", {}).get("adjustments", []) if _pa and _pa.data else []) if (a.get("portfolio") or "quant") == "quant"]
        except Exception:
            _adjs = []

        def _adj_pp(date_str: str) -> float:
            return sum(float(a.get("amount") or 0) for a in _adjs if a.get("date") and a["date"] <= date_str) / 1000

        first, last = rows[0], rows[-1]
        port_first = float(first["portfolio_cumulative_return"]) + _adj_pp(first["snapshot_date"])
        port_last = float(last["portfolio_cumulative_return"]) + _adj_pp(last["snapshot_date"])
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


def _inline_bold(text: str) -> str:
    """Convert **bold** to <strong> tags."""
    import re
    return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", html.escape(text))


def _markdown_to_html(lines: list[str]) -> str:
    """Convert markdown lines to email-safe HTML (headings, bullets, tables, paragraphs)."""
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]

        # ## Heading
        if line.startswith("#"):
            import re
            text = re.sub(r"^#{1,3}\s+", "", line)
            out.append(
                f"<p style='margin:18px 0 8px 0; font-size:15px; font-weight:700; color:#111827;'>"
                f"{_inline_bold(text)}</p>"
            )
            i += 1
            continue

        # Table block
        if line.startswith("|") and line.endswith("|"):
            cells = [c.strip() for c in line.split("|")[1:-1]]
            # skip separator
            j = i + 1
            import re
            while j < len(lines) and re.match(r"^\|[\s\-:|]+\|$", lines[j]):
                j += 1
            rows: list[list[str]] = []
            while j < len(lines) and lines[j].startswith("|") and lines[j].endswith("|"):
                rows.append([c.strip() for c in lines[j].split("|")[1:-1]])
                j += 1
            th = "".join(
                f"<th style='padding:4px 8px; font-size:12px; font-weight:700; color:#111827; "
                f"background:#f9fafb; border-bottom:2px solid #d1d5db; text-align:left;'>"
                f"{html.escape(c)}</th>"
                for c in cells
            )
            body = ""
            for row in rows:
                tds = "".join(
                    f"<td style='padding:4px 8px; font-size:12px; color:#374151; "
                    f"border-bottom:1px solid #e5e7eb;'>{_inline_bold(c)}</td>"
                    for c in row
                )
                body += f"<tr>{tds}</tr>"
            out.append(
                f"<table width='100%' cellpadding='0' cellspacing='0' "
                f"style='border-collapse:collapse; margin:8px 0 12px 0;'>"
                f"<thead><tr>{th}</tr></thead><tbody>{body}</tbody></table>"
            )
            i = j
            continue

        # Bullet
        if line.startswith("- ") or line.startswith("* "):
            text = line.lstrip("-* ")
            out.append(
                f"<p style='margin:0 0 4px 0; padding-left:12px; font-size:14px; "
                f"line-height:1.6; color:#374151;'>&bull;&nbsp;{_inline_bold(text)}</p>"
            )
            i += 1
            continue

        # Plain paragraph
        out.append(
            f"<p style='margin:0 0 12px 0; line-height:1.6; color:#374151;'>"
            f"{_inline_bold(line)}</p>"
        )
        i += 1

    return "".join(out)


def _build_subscription_email(data: dict, recipient_email: str | None = None) -> tuple[str, str]:
    """Build the single daily digest email (HTML + plain text).

    Critical data first, easy to scan: both portfolios (Quant Core + Conviction),
    the AI super-cycle headline, then today's trades and a short takeaway.

    Args:
        data: {
            "today_label": str,
            "books": [ {"name", "equity", "daily_pnl", "return_pct",
                        "spy_pct", "alpha_pct"} ],   # one per portfolio
            "cycle": {"phase_label", "score", "capex_direction",
                      "hyperscaler_yoy", "heat_level", "heat_score"} | None,
            "cycle_signals": {"net_read", "signals": [
                {"headline","source","url","date","category","direction","why"}
            ]} | None,
            "trades": [ {"portfolio","side","symbol","qty","price"} ],
            "reflection": {"content": str} | None,
        }
        recipient_email: subscriber email for a personalized unsubscribe link.
    """
    import urllib.parse

    today_label = data.get("today_label", "")
    books = data.get("books", [])
    cycle = data.get("cycle")
    cycle_signals = data.get("cycle_signals")
    trades = data.get("trades", [])
    reflection = data.get("reflection")

    def _color(val) -> str:
        if val is None:
            return "#111827"
        return "#16a34a" if val > 0 else ("#dc2626" if val < 0 else "#111827")

    def _signed(val) -> str:
        if val is None:
            return "—"
        return f"{val:+.2f}%"

    # ── Portfolios table ──────────────────────────────────────────────────────
    head = (
        "<tr style='font-size:11px; text-transform:uppercase; letter-spacing:0.05em; color:#9ca3af;'>"
        "<td style='padding:6px 8px;'>Book</td>"
        "<td style='padding:6px 8px; text-align:right;'>Equity</td>"
        "<td style='padding:6px 8px; text-align:right;'>Day P&L</td>"
        "<td style='padding:6px 8px; text-align:right;'>Return</td>"
        "<td style='padding:6px 8px; text-align:right;'>vs SPY</td></tr>"
    )
    body_rows = ""
    for b in books:
        pnl = b.get("daily_pnl")
        ret = b.get("return_pct")
        alpha = b.get("alpha_pct")
        vs = _signed(alpha) if alpha is not None else "—"
        body_rows += (
            "<tr style='border-top:1px solid #eee; font-size:14px;'>"
            f"<td style='padding:8px; font-weight:600;'>{html.escape(b.get('name',''))}</td>"
            f"<td style='padding:8px; text-align:right;'>{html.escape(_fmt_currency(b.get('equity')))}</td>"
            f"<td style='padding:8px; text-align:right; color:{_color(pnl)};'>{html.escape(_fmt_currency(pnl))}</td>"
            f"<td style='padding:8px; text-align:right; color:{_color(ret)};'>{html.escape(_signed(ret))}</td>"
            f"<td style='padding:8px; text-align:right; color:{_color(alpha)};'>{html.escape(vs)}</td></tr>"
        )
    _adj = max((abs(float(b.get("adjustment") or 0)) for b in books), default=0)
    adj_note = (
        f"<p style='margin:6px 0 0 0; font-size:11px; color:#9ca3af;'>"
        f"Equity, Return &amp; vs-SPY include a +${_adj/1000:.1f}k one-time KLAC split-artifact correction.</p>"
        if _adj else ""
    )
    portfolios_html = (
        "<table width='100%' cellpadding='0' cellspacing='0' "
        "style='border-collapse:collapse; margin-top:4px;'>"
        f"{head}{body_rows}</table>{adj_note}"
    )

    # ── AI super-cycle headline band ──────────────────────────────────────────
    cycle_html = ""
    if cycle:
        yoy = cycle.get("hyperscaler_yoy")
        yoy_str = f"{yoy:+.0f}%" if yoy is not None else "n/a"
        capex_dir = (cycle.get("capex_direction") or "—").title()
        phase = cycle.get("phase_label") or "—"
        cscore = cycle.get("score")
        heat = (cycle.get("heat_level") or "—").title()
        hscore = cycle.get("heat_score")
        cycle_html = (
            "<div style='margin-top:18px; padding:14px 16px; border-radius:14px; background:#111827; color:#f9fafb;'>"
            "<p style='margin:0 0 6px 0; font-size:11px; text-transform:uppercase; letter-spacing:0.08em; color:#9ca3af;'>AI Super-Cycle</p>"
            f"<p style='margin:0; font-size:14px; line-height:1.6;'>"
            f"Cycle <b>{html.escape(phase)}</b> {cscore if cscore is not None else '—'}/100 &nbsp;·&nbsp; "
            f"Capex <b style='color:#34d399;'>{html.escape(capex_dir)}</b> {html.escape(yoy_str)} &nbsp;·&nbsp; "
            f"Heat <b>{html.escape(heat)}</b> {hscore if hscore is not None else '—'}/100</p></div>"
        )

    # ── Key news (AI cycle signals) ───────────────────────────────────────────
    # category → (label, text color, pill background) — mirrors the dashboard
    # CycleSignalsCard so the email reads as the same product.
    _SIGNAL_STYLE = {
        "supply_tight":     ("Supply Tight",     "#15803d", "#dcfce7"),
        "capacity_adds":    ("Capacity Adds",    "#15803d", "#dcfce7"),
        "guidance_shift":   ("Guidance",         "#1d4ed8", "#dbeafe"),
        "financing_strain": ("Financing Strain", "#b45309", "#fef3c7"),
        "demand_stress":    ("Demand Stress",    "#b91c1c", "#fee2e2"),
    }
    news_html = ""
    signals = (cycle_signals or {}).get("signals") or []
    if signals:
        as_of_label = ""
        _as_of = (cycle_signals or {}).get("as_of")
        if _as_of:
            try:
                as_of_label = datetime.fromisoformat(
                    str(_as_of).replace("Z", "+00:00")
                ).strftime("%b %-d")
            except Exception:
                as_of_label = ""
        net_read = (cycle_signals or {}).get("net_read") or ""
        net_read_html = (
            f"<p style='margin:0 0 14px 0; font-size:13px; line-height:1.6; color:#4b5563;'>"
            f"{html.escape(net_read)}</p>"
            if net_read else ""
        )
        items = ""
        for s in signals[:4]:
            label, fg, bg = _SIGNAL_STYLE.get(
                s.get("category") or "",
                (str(s.get("category") or "Signal").replace("_", " ").title(), "#374151", "#f3f4f6"),
            )
            pill = (
                f"<span style='display:inline-block; padding:2px 8px; border-radius:9999px; "
                f"background:{bg}; color:{fg}; font-size:10px; font-weight:700; "
                f"text-transform:uppercase; letter-spacing:0.04em; white-space:nowrap;'>"
                f"{html.escape(label)}</span>"
            )
            headline = html.escape(s.get("headline") or "")
            url = s.get("url")
            if url:
                headline = (
                    f"<a href='{html.escape(url)}' style='color:#111827; text-decoration:none;'>"
                    f"{headline} <span style='color:#9ca3af;'>&#8599;</span></a>"
                )
            why_text = html.escape(s.get("why") or "")
            source = s.get("source")
            if source:
                why_text += f" <span style='color:#9ca3af;'>&mdash; {html.escape(source)}</span>"
            why_html = (
                f"<p style='margin:4px 0 0 0; font-size:12px; line-height:1.5; color:#6b7280;'>{why_text}</p>"
                if why_text else ""
            )
            items += (
                "<div style='margin-bottom:14px;'>"
                f"<div style='font-size:14px; line-height:1.5; color:#111827;'>"
                f"{pill}&nbsp; <span style='font-weight:600;'>{headline}</span></div>"
                f"{why_html}</div>"
            )
        as_of_html = (
            f"<span style='float:right; font-size:11px; font-weight:400; text-transform:none; "
            f"letter-spacing:0; color:#9ca3af;'>Monet&rsquo;s read &middot; {html.escape(as_of_label)}</span>"
            if as_of_label else ""
        )
        news_html = (
            "<div style='margin-top:18px; padding-top:16px; border-top:1px solid #e5e7eb;'>"
            "<p style='margin:0 0 10px 0; font-size:11px; font-weight:600; text-transform:uppercase; "
            "letter-spacing:0.06em; color:#6b7280;'>"
            f"Key news &middot; AI super-cycle{as_of_html}</p>"
            f"{net_read_html}{items}</div>"
        )

    # ── Today's trades ────────────────────────────────────────────────────────
    def _trade_line(t: dict) -> str:
        qty = t.get("qty")
        price = t.get("price")
        price_text = f" @ ${float(price):.2f}" if price else ""
        tag = "CONV" if t.get("portfolio") == "conviction" else "QUANT"
        return f"[{tag}] {str(t.get('side','')).upper()} {qty} {t.get('symbol','')}{price_text}"

    trade_lines = [_trade_line(t) for t in trades[:6]]
    trades_html = ""
    if trade_lines:
        items = "".join(f"<li style='margin-bottom:4px;'>{html.escape(t)}</li>" for t in trade_lines)
        trades_html = (
            "<div style='margin-top:18px; padding-top:16px; border-top:1px solid #e5e7eb;'>"
            "<p style='margin:0 0 8px 0; font-size:11px; font-weight:600; text-transform:uppercase; letter-spacing:0.06em; color:#6b7280;'>Today&rsquo;s trades</p>"
            f"<ul style='padding-left:20px; margin:0; color:#374151; font-size:14px;'>{items}</ul></div>"
        )

    # ── Short takeaway (trimmed reflection) ───────────────────────────────────
    reflection_lines = [
        ln.strip() for ln in ((reflection or {}).get("content") or "").splitlines() if ln.strip()
    ][:4]
    takeaway_html = ""
    if reflection_lines:
        takeaway_html = (
            "<div style='margin-top:18px; padding-top:16px; border-top:1px solid #e5e7eb;'>"
            "<p style='margin:0 0 8px 0; font-size:11px; text-transform:uppercase; letter-spacing:0.06em; color:#6b7280;'>Takeaway</p>"
            f"{_markdown_to_html(reflection_lines)}</div>"
        )

    # ── Unsubscribe ───────────────────────────────────────────────────────────
    app_url = os.environ.get("NEXT_APP_URL", "https://monet.app")
    unsub_url = (
        f"{app_url}/api/unsubscribe?email={urllib.parse.quote(recipient_email)}"
        if recipient_email else f"{app_url}/unsubscribe"
    )
    unsubscribe_html = (
        "<div style='margin-top:24px; padding-top:16px; border-top:1px solid #e5e7eb; text-align:center;'>"
        "<p style='margin:0; font-size:12px; color:#9ca3af;'>"
        "You&rsquo;re receiving Monet&rsquo;s daily digest.&nbsp;"
        f"<a href='{unsub_url}' style='color:#6b7280; text-decoration:underline;'>Unsubscribe</a></p></div>"
    )

    html_body = (
        "<div style='font-family:Arial,sans-serif; max-width:680px; margin:0 auto; padding:28px 24px; color:#111827; background:#f4f1ea;'>"
        "<div style='background:#ffffff; border:1px solid #e7e0d2; border-radius:24px; padding:28px;'>"
        "<p style='margin:0 0 4px 0; font-size:12px; letter-spacing:0.08em; text-transform:uppercase; color:#6b7280;'>Monet daily digest</p>"
        f"<h1 style='margin:0 0 16px 0; font-size:24px; line-height:1.15; color:#111827;'>{html.escape(today_label)}</h1>"
        f"{portfolios_html}"
        f"{cycle_html}"
        f"{news_html}"
        f"{trades_html}"
        f"{takeaway_html}"
        f"{unsubscribe_html}"
        "</div></div>"
    )

    # ── Plain text ────────────────────────────────────────────────────────────
    text_parts = [f"Monet Daily Digest — {today_label}", ""]
    for b in books:
        text_parts.append(
            f"{b.get('name',''):11} equity {_fmt_currency(b.get('equity'))}  "
            f"day {_fmt_currency(b.get('daily_pnl'))}  return {_signed(b.get('return_pct'))}  "
            f"vs SPY {_signed(b.get('alpha_pct')) if b.get('alpha_pct') is not None else '—'}"
        )
    if cycle:
        yoy = cycle.get("hyperscaler_yoy")
        text_parts += ["", (
            f"AI Super-Cycle: Cycle {cycle.get('phase_label','—')} {cycle.get('score','—')}/100 · "
            f"Capex {(cycle.get('capex_direction') or '—').title()} {f'{yoy:+.0f}%' if yoy is not None else 'n/a'} · "
            f"Heat {(cycle.get('heat_level') or '—').title()} {cycle.get('heat_score','—')}/100"
        )]
    if signals:
        text_parts += ["", "Key news — AI super-cycle:"]
        net_read = (cycle_signals or {}).get("net_read") or ""
        if net_read:
            text_parts.append(f"  {net_read}")
        for s in signals[:4]:
            label = _SIGNAL_STYLE.get(
                s.get("category") or "",
                ((s.get("category") or "Signal").replace("_", " ").title(),),
            )[0]
            line = f"  - [{label}] {s.get('headline','')}"
            if s.get("source"):
                line += f" ({s.get('source')})"
            text_parts.append(line)
    if trade_lines:
        text_parts += ["", "Today's trades:", *[f"  - {t}" for t in trade_lines]]
    if reflection_lines:
        text_parts += ["", "Takeaway:", *reflection_lines]
    text_parts += ["", "---", f"Unsubscribe: {unsub_url}"]

    return html_body, "\n".join(text_parts)


def send_daily_subscription_emails() -> dict:
    """Send the daily recap email to all active subscribers once per day."""
    resend_api_key = os.environ.get("RESEND_API_KEY")
    from_email = os.environ.get("DAILY_RECAP_FROM_EMAIL")

    if not resend_api_key or not from_email:
        return {
            "status": "skipped",
            "message": "Email delivery not configured. Set RESEND_API_KEY and DAILY_RECAP_FROM_EMAIL.",
        }

    sb = get_supabase()
    today = datetime.now()
    today_label = today.strftime("%A, %B %-d, %Y")
    today_start = today.strftime("%Y-%m-%d")

    try:
        subs_result = (
            sb.table("email_subscriptions")
            .select("id, email, last_sent_at")
            .eq("status", "active")
            .execute()
        )
        subscriptions = subs_result.data or []
        due_subscriptions = []
        for subscription in subscriptions:
            last_sent_at = subscription.get("last_sent_at")
            if not last_sent_at or str(last_sent_at)[:10] < today_start:
                due_subscriptions.append(subscription)

        if not due_subscriptions:
            return {"status": "ok", "sent": 0, "message": "No subscribers due for delivery."}

        reflection_result = (
            sb.table("agent_journal")
            .select("title, content, created_at")
            .eq("entry_type", "reflection")
            .gte("created_at", f"{today_start}T00:00:00")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        reflection = reflection_result.data[0] if reflection_result.data else None

        trades_result = (
            sb.table("trades")
            .select("symbol, side, quantity, filled_quantity, filled_avg_price, limit_price, portfolio, created_at")
            .gte("created_at", f"{today_start}T00:00:00")
            .order("created_at", desc=True)
            .limit(8)
            .execute()
        )
        trades = [
            {
                "portfolio": t.get("portfolio", "quant"),
                "side": t.get("side"),
                "symbol": t.get("symbol"),
                "qty": t.get("filled_quantity") or t.get("quantity"),
                "price": t.get("filled_avg_price") or t.get("limit_price"),
            }
            for t in (trades_result.data or [])
        ]

        # ── Per-book metrics (Quant Core + Conviction) ─────────────────────────
        # Match the dashboard: return = live equity vs $100k inception; SPY/alpha
        # from each book's own latest equity_snapshot; one-time corporate-action
        # corrections (e.g. KLAC split artifact) added back so the email agrees with
        # the dashboard. Cumulative → equity/return; today's portion → daily P&L.
        _STARTING_EQUITY = 100_000
        try:
            _pa = (
                sb.table("agent_memory").select("value").eq("key", "performance_adjustments").maybe_single().execute()
            )
            _perf_adjustments = (_pa.data or {}).get("value", {}).get("adjustments", []) if _pa and _pa.data else []
        except Exception:
            _perf_adjustments = []

        def _book_metrics(name: str, slug: str) -> dict:
            try:
                p = get_portfolio(slug)
            except Exception:
                logger.warning("Failed to load %s portfolio for daily email.", slug)
                return {"name": name, "equity": None, "daily_pnl": None, "return_pct": None, "spy_pct": None, "alpha_pct": None, "adjustment": 0}
            mine = [a for a in _perf_adjustments if (a.get("portfolio") or "quant") == slug]
            adj_total = sum(float(a.get("amount") or 0) for a in mine)
            adj_today = sum(float(a.get("amount") or 0) for a in mine if a.get("date") == today_start)
            eq = p.get("equity")
            eq_adj = (eq + adj_total) if eq else eq
            ret = round((eq_adj - _STARTING_EQUITY) / _STARTING_EQUITY * 100, 2) if eq_adj else None
            spy = None
            try:
                snaps = get_equity_snapshots(days=1, portfolio=slug)
                if snaps:
                    spy = snaps[0].get("spy_cumulative_return")
            except Exception:
                pass
            alpha = round(ret - spy, 2) if (ret is not None and spy is not None) else None
            daily = (p.get("daily_pnl") or 0) + adj_today
            return {"name": name, "equity": eq_adj, "daily_pnl": daily, "return_pct": ret, "spy_pct": spy, "alpha_pct": alpha, "adjustment": adj_total}

        books = [_book_metrics("Quant Core", "quant"), _book_metrics("Conviction", "conviction")]

        # ── AI super-cycle headline (from memory) ──────────────────────────────
        def _read_mem(key: str) -> dict:
            try:
                r = sb.table("agent_memory").select("value").eq("key", key).maybe_single().execute()
                return (r.data or {}).get("value", {}) if r and r.data else {}
            except Exception:
                return {}

        dur, cap, bub = _read_mem("ai_cycle_durability"), _read_mem("ai_capex_tracker"), _read_mem("ai_bubble_risk")
        cycle = None
        if dur or cap or bub:
            cycle = {
                "phase_label": dur.get("phase_label"),
                "score": dur.get("score"),
                "capex_direction": cap.get("guidance_direction"),
                "hyperscaler_yoy": cap.get("hyperscaler_total_yoy"),
                "heat_level": bub.get("level"),
                "heat_score": bub.get("score"),
            }

        # ── Key news (curated AI cycle signals, same source as dashboard) ──────
        # Guardrail: only let recent (≤7d) news lead the subject / Key News list,
        # so a stale or mis-dated standing fact can't hijack the email. Items with
        # no parseable date are kept (can't prove stale; Finnhub items are dated).
        def _signal_fresh(s: dict, max_age_days: int = 7) -> bool:
            d = s.get("date")
            if not d:
                return True
            try:
                dt = datetime.fromisoformat(str(d).replace("Z", "+00:00"))
            except Exception:
                return True
            return (today.date() - dt.date()).days <= max_age_days

        sig = _read_mem("ai_cycle_signals")
        cycle_signals = None
        if sig and sig.get("signals"):
            _fresh = [s for s in sig["signals"] if _signal_fresh(s)]
            if _fresh:
                cycle_signals = {**sig, "signals": _fresh}

        email_data = {
            "today_label": today_label,
            "books": books,
            "cycle": cycle,
            "cycle_signals": cycle_signals,
            "trades": trades,
            "reflection": reflection,
        }

        # ── Subject: lead with the day's top curated news headline ─────────────
        # News-led subject earns the open; fall back to the dated digest title
        # when no signals were captured that day.
        try:
            _short_date = today.strftime("%b %-d")
        except Exception:
            _short_date = today_label
        subject = f"Monet Daily Digest - {today_label}"
        _top_signals = (cycle_signals or {}).get("signals") or []
        if _top_signals:
            _hl = (_top_signals[0].get("headline") or "").strip()
            if _hl:
                if len(_hl) > 64:
                    _hl = _hl[:63].rsplit(" ", 1)[0].rstrip(",.;:—- ") + "…"
                subject = f"Monet · {_hl} · {_short_date}"

        sent_ids: list[str] = []

        with httpx.Client(timeout=20.0) as client:
            for subscription in due_subscriptions:
                # Build per-subscriber HTML so the unsubscribe link is personalised.
                html_body, text_body = _build_subscription_email(
                    email_data,
                    recipient_email=subscription["email"],
                )
                response = client.post(
                    "https://api.resend.com/emails",
                    headers={
                        "Authorization": f"Bearer {resend_api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "from": from_email,
                        "to": [subscription["email"]],
                        "subject": subject,
                        "html": html_body,
                        "text": text_body,
                    },
                )
                response.raise_for_status()
                sent_ids.append(subscription["id"])

        if sent_ids:
            (
                sb.table("email_subscriptions")
                .update({"last_sent_at": datetime.now().isoformat()})
                .in_("id", sent_ids)
                .execute()
            )

        return {
            "status": "ok",
            "sent": len(sent_ids),
            "message": f"Sent daily recap email to {len(sent_ids)} subscribers.",
        }
    except Exception as e:
        logger.error("Failed to send daily subscription emails: %s", e)
        return {"status": "error", "error": str(e)}


def send_weekly_cycle_report(agent_commentary: str = "") -> dict:
    """Send the weekly AI cycle durability report to all active subscribers.

    Reads the latest ai_cycle_durability and ai_bubble_risk from agent_memory,
    renders the WeeklyCycleReportEmail template, and sends via Resend.

    Args:
        agent_commentary: Free-form commentary from the agent about what changed
            this week and what to watch for. Supports markdown bullet points.

    Returns:
        Dict with status, sent count, and any errors.
    """
    resend_api_key = os.environ.get("RESEND_API_KEY")
    from_email = os.environ.get("DAILY_RECAP_FROM_EMAIL")

    if not resend_api_key or not from_email:
        return {
            "status": "skipped",
            "message": "Email delivery not configured. Set RESEND_API_KEY and DAILY_RECAP_FROM_EMAIL.",
        }

    sb = get_supabase()
    today = datetime.now()
    week_label = today.strftime("%B %-d, %Y")

    try:
        # Fetch subscribers
        subs_result = (
            sb.table("email_subscriptions")
            .select("id, email")
            .eq("status", "active")
            .execute()
        )
        subscriptions = subs_result.data or []
        if not subscriptions:
            return {"status": "ok", "sent": 0, "message": "No active subscribers."}

        # Read cycle durability data
        cycle_row = (
            sb.table("agent_memory")
            .select("value")
            .eq("key", "ai_cycle_durability")
            .maybe_single()
            .execute()
        )
        cycle_data = cycle_row.data.get("value") if cycle_row.data else None
        if not cycle_data:
            return {"status": "skipped", "message": "No cycle durability data yet. Run assess_ai_cycle_durability first."}

        # Read heat data for companion context
        heat_row = (
            sb.table("agent_memory")
            .select("value")
            .eq("key", "ai_bubble_risk")
            .maybe_single()
            .execute()
        )
        heat_data = heat_row.data.get("value") if heat_row.data else {}

        # Read previous week's score for delta display
        prev_row = (
            sb.table("agent_memory")
            .select("value")
            .eq("key", "ai_cycle_durability_prev")
            .maybe_single()
            .execute()
        )
        prev_score = None
        if prev_row.data and prev_row.data.get("value"):
            prev_score = prev_row.data["value"].get("score")

        # Save current as prev for next week's delta
        sb.table("agent_memory").upsert(
            {"key": "ai_cycle_durability_prev", "value": {"score": cycle_data["score"], "as_of": today.isoformat()}},
            on_conflict="key",
        ).execute()

        signals = cycle_data.get("signals", {})
        stack = signals.get("stack_breadth", {})
        layers = stack.get("layers", {})

        app_url = os.environ.get("NEXT_APP_URL", "https://monet.app")
        subject = f"Monet AI Cycle Report — Week of {week_label}"
        sent_count = 0

        with httpx.Client(timeout=20.0) as client:
            for sub in subscriptions:
                import urllib.parse
                unsub_url = f"{app_url}/api/unsubscribe?email={urllib.parse.quote(sub['email'])}"

                # Build email payload for React Email renderer
                render_payload = {
                    "template": "weekly_cycle_report",
                    "weekLabel": week_label,
                    "cycleScore": cycle_data["score"],
                    "cyclePhaseLabel": cycle_data.get("phase_label", "Unknown"),
                    "cycleOutlook": cycle_data.get("outlook", ""),
                    "layersParticipating": stack.get("layers_participating", 0),
                    "totalLayers": stack.get("total_layers", 5),
                    "layers": layers,
                    "infraVsSpy": signals.get("infra_momentum", {}).get("vs_spy_pct"),
                    "memoryVsSpy": signals.get("memory_demand", {}).get("vs_spy_pct"),
                    "equipmentVsSpy": signals.get("equipment_demand", {}).get("vs_spy_pct"),
                    "capexDirection": signals.get("capex_signal", {}).get("direction", "unknown"),
                    "spyReturn3m": cycle_data.get("spy_return_3m_pct"),
                    "heatScore": heat_data.get("score"),
                    "heatLevel": heat_data.get("level"),
                    "prevCycleScore": prev_score,
                    "agentCommentary": agent_commentary,
                    "recipientEmail": sub["email"],
                }

                # Try React Email renderer first, fall back to plain HTML
                html_body = None
                text_body = None
                try:
                    render_resp = client.post(
                        f"{app_url}/api/email/render",
                        json=render_payload,
                        timeout=15.0,
                    )
                    if render_resp.status_code == 200:
                        rendered = render_resp.json()
                        html_body = rendered.get("html")
                        text_body = rendered.get("text")
                except Exception:
                    pass

                # Fallback plain text
                if not text_body:
                    text_body = (
                        f"Monet AI Cycle Report — {week_label}\n\n"
                        f"Cycle Durability: {cycle_data['score']} ({cycle_data.get('phase_label', '')})\n"
                        f"Sector Heat: {heat_data.get('score', '—')} ({heat_data.get('level', '—')})\n\n"
                        f"{cycle_data.get('outlook', '')}\n\n"
                        f"{agent_commentary}\n\n---\nUnsubscribe: {unsub_url}"
                    )
                if not html_body:
                    html_body = text_body.replace("\n", "<br>")

                response = client.post(
                    "https://api.resend.com/emails",
                    headers={
                        "Authorization": f"Bearer {resend_api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "from": from_email,
                        "to": [sub["email"]],
                        "subject": subject,
                        "html": html_body,
                        "text": text_body,
                    },
                )
                response.raise_for_status()
                sent_count += 1

        return {
            "status": "ok",
            "sent": sent_count,
            "message": f"Sent weekly cycle report to {sent_count} subscribers.",
        }
    except Exception as e:
        logger.error("Failed to send weekly cycle report: %s", e)
        return {"status": "error", "error": str(e)}


# ============================================================
# Bracket / Position Protection tools
# ============================================================

def attach_bracket_to_position(
    symbol: str,
    quantity: float,
    stop_loss_price: float,
    take_profit_price: float | None = None,
    portfolio: str = "quant",
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
        portfolio: Which book the position belongs to — "quant" (default) or "conviction".

    Returns:
        Dict with order details.
    """
    client = get_trading_client(portfolio)

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
        portfolio=portfolio,
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

def record_daily_snapshot(portfolio: str = "quant") -> dict:
    """Record today's portfolio equity and SPY close for benchmark tracking.

    Call this during EOD reflection (4 PM ET) to log a daily data point. Each book
    ("quant" = Quant Core, "conviction" = Conviction) records its own equity curve;
    cumulative returns vs SPY are auto-computed from that book's first snapshot.

    Returns:
        Dict with today's snapshot including portfolio return, SPY return, and alpha.
    """
    portfolio_state = get_portfolio(portfolio)
    equity = float(portfolio_state.get("equity", 0))
    cash = float(portfolio_state.get("cash", 0))

    # Use yfinance for SPY close — Alpaca quotes return 0 bid/ask at market close
    try:
        spy_ticker = yf.Ticker("SPY")
        spy_hist = spy_ticker.history(period="1d")
        spy_close = round(float(spy_hist["Close"].iloc[-1]), 2) if not spy_hist.empty else 0.0
    except Exception:
        spy_close = 0.0

    # Fallback: try Alpaca quote if yfinance failed
    if spy_close == 0.0:
        spy_quote = get_quote("SPY")
        bid = float(spy_quote.get("bid_price", 0))
        ask = float(spy_quote.get("ask_price", 0))
        spy_close = round((bid + ask) / 2, 2) if bid and ask else 0.0

    today = datetime.now().strftime("%Y-%m-%d")
    snapshot = db_record_equity_snapshot(today, equity, cash, spy_close, portfolio=portfolio)

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

    # One-time corporate-action corrections (Quant Core): add back a fixed-$ artifact
    # to every snapshot on/after its date, so a broker bug (e.g. KLAC's split being
    # mishandled) doesn't drag the strategy's measured return. Matches dashboard + email.
    try:
        _pa = get_supabase().table("agent_memory").select("value").eq("key", "performance_adjustments").maybe_single().execute()
        _adjs = [a for a in ((_pa.data or {}).get("value", {}).get("adjustments", []) if _pa and _pa.data else []) if (a.get("portfolio") or "quant") == "quant"]
    except Exception:
        _adjs = []

    def _adj_at(date_str: str) -> float:
        return sum(float(a.get("amount") or 0) for a in _adjs if a.get("date") and a["date"] <= date_str)

    def _eq(s) -> float:
        return float(s["portfolio_equity"]) + _adj_at(s["snapshot_date"])

    latest = snapshots[-1]
    oldest = snapshots[0]

    # Period return (this window) on adjusted equity
    oldest_equity = _eq(oldest)
    latest_equity = _eq(latest)
    oldest_spy = float(oldest["spy_close"])
    latest_spy = float(latest["spy_close"])

    period_portfolio_return = round((latest_equity / oldest_equity - 1) * 100, 2) if oldest_equity else 0
    period_spy_return = round((latest_spy / oldest_spy - 1) * 100, 2) if oldest_spy else 0
    period_alpha = round(period_portfolio_return - period_spy_return, 2)

    # Max drawdown (on adjusted equity)
    peak = 0
    max_dd = 0
    for s in snapshots:
        eq = _eq(s)
        peak = max(peak, eq)
        dd = (peak - eq) / peak * 100 if peak > 0 else 0
        max_dd = max(max_dd, dd)

    # Time series for charting (adjusted cumulative return; +$/100k → pp)
    series = [
        {
            "date": s["snapshot_date"],
            "portfolio": round(float(s.get("portfolio_cumulative_return") or 0) + _adj_at(s["snapshot_date"]) / 1000, 4),
            "spy": float(s.get("spy_cumulative_return") or 0),
            "alpha": round(float(s.get("alpha") or 0) + _adj_at(s["snapshot_date"]) / 1000, 4),
        }
        for s in snapshots
    ]

    latest_adj_pp = _adj_at(latest["snapshot_date"]) / 1000
    cum_port = round(float(latest.get("portfolio_cumulative_return") or 0) + latest_adj_pp, 2)
    cum_spy = round(float(latest.get("spy_cumulative_return") or 0), 2)
    total_adj = sum(float(a.get("amount") or 0) for a in _adjs)

    return {
        "period_days": len(snapshots),
        "portfolio_return_pct": period_portfolio_return,
        "spy_return_pct": period_spy_return,
        "alpha_pct": period_alpha,
        "max_drawdown_pct": round(max_dd, 2),
        "latest_equity": round(latest_equity, 2),
        "latest_date": latest["snapshot_date"],
        "cumulative_portfolio_return": cum_port,
        "cumulative_spy_return": cum_spy,
        "cumulative_alpha": round(cum_port - cum_spy, 2),
        "adjustment_applied_usd": round(total_adj, 2),
        "adjustment_note": (
            f"Includes a +${total_adj / 1000:.1f}k one-time corporate-action correction (KLAC split artifact)."
            if total_adj else None
        ),
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

    # Peak price and drawdown since entry — gives the agent visibility into
    # "this position was at +12% and is now at +5%" oscillation patterns.
    peak_price = None
    peak_pnl_pct = None
    drawdown_from_peak_pct = None
    try:
        # Get the entry date from the most recent buy trade
        sb_peek = get_supabase()
        entry_trade = (
            sb_peek.table("trades")
            .select("created_at")
            .eq("symbol", symbol.upper())
            .eq("side", "buy")
            .or_("status.ilike.%filled%,status.ilike.%FILLED%")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        if entry_trade.data:
            entry_date = entry_trade.data[0]["created_at"][:10]
            from datetime import datetime as _dt

            days_since = (_dt.now() - _dt.strptime(entry_date, "%Y-%m-%d")).days + 1
            df = get_historical_bars(symbol, days=max(days_since + 5, 10))
            if df is not None and len(df) > 0:
                # Filter to bars on or after entry date
                df_since = df[df.index >= entry_date] if hasattr(df.index, '__ge__') else df.tail(days_since)
                if len(df_since) > 0:
                    peak_price = round(float(df_since["high"].max()), 2)
                    if avg_entry > 0:
                        peak_pnl_pct = round((peak_price / avg_entry - 1) * 100, 2)
                    if peak_price > 0 and current_price > 0:
                        drawdown_from_peak_pct = round((current_price / peak_price - 1) * 100, 2)
    except Exception:
        pass

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
        "peak_price": peak_price,
        "peak_pnl_pct": peak_pnl_pct,
        "drawdown_from_peak_pct": drawdown_from_peak_pct,
    }


# ============================================================
# Factor-Based Scoring tools
# ============================================================


def _percentile_rank(series: pd.Series) -> pd.Series:
    """Compute percentile rank (0-100) for each value in a Series."""
    return series.rank(pct=True, na_option="keep") * 100


_DEFAULT_FACTOR_WEIGHTS = {"momentum": 0.35, "quality": 0.30, "value": 0.20, "eps_revision": 0.15}


def _load_factor_weights() -> dict:
    """Load factor weights from agent_memory, falling back to defaults."""
    try:
        result = read_memory("factor_weights")
        if result and result.get("value"):
            stored = result["value"]
            return {
                "momentum": float(stored.get("momentum", _DEFAULT_FACTOR_WEIGHTS["momentum"])),
                "quality": float(stored.get("quality", _DEFAULT_FACTOR_WEIGHTS["quality"])),
                "value": float(stored.get("value", _DEFAULT_FACTOR_WEIGHTS["value"])),
                "eps_revision": float(stored.get("eps_revision", _DEFAULT_FACTOR_WEIGHTS["eps_revision"])),
            }
    except Exception:
        logger.warning("Failed to load factor_weights from memory, using defaults")
    return _DEFAULT_FACTOR_WEIGHTS.copy()


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

    # Step 1: Bulk download 1Y of daily closes (auto_adjust=True → split/dividend
    # adjusted, so events like KLAC's 10:1 split don't read as a 90% crash).
    try:
        price_data = yf.download(tickers, period="1y", progress=False, threads=True, auto_adjust=True)
    except Exception as e:
        return {"error": f"Price download failed: {e}", "rankings": []}

    if price_data.empty:
        return {"error": "No price data returned", "rankings": []}

    close = price_data["Close"]

    # Step 2: Compute momentum on full universe (lets us pre-filter below)
    from .factor_scoring import (
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
    reconcile_positions,
    adjust_for_corporate_actions,
    check_trade_risk,
    query_database,
    send_daily_recap,
    send_daily_subscription_emails,
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
    # Catalyst discovery
    discover_catalysts,
    # Earnings intelligence
    get_earnings_results,
    # AI bubble / concentration risk
    assess_ai_bubble_risk,
    # AI cycle durability
    assess_ai_cycle_durability,
    # AI super-cycle: automated capex trend + daily history snapshot + structured news
    compute_ai_capex_trend,
    record_ai_cycle_snapshot,
    get_ai_infra_news,
    # Conviction portfolio: concentrated cyclical sizing
    size_cycle_position,
    send_weekly_cycle_report,
    # Tier 1 strategy health monitoring
    audit_factor_ic,
    check_live_vs_backtest_divergence,
    suggest_factor_weight_adjustment,
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
