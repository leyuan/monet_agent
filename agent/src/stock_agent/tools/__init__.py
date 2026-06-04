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
from stock_agent.tools._shared import _avg_return, _DEFAULT_FACTOR_WEIGHTS, _load_factor_weights
from stock_agent.tools.research import assess_ai_bubble_risk, assess_ai_cycle_durability
from stock_agent.tools.strategy_health import (
    audit_factor_ic,
    check_live_vs_backtest_divergence,
    suggest_factor_weight_adjustment,
)
from stock_agent.tools.reports import (
    send_daily_recap,
    send_daily_subscription_emails,
    send_weekly_cycle_report,
    record_daily_snapshot,
    get_performance_comparison,
    position_health_check,
)

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


def reconcile_positions() -> dict:
    """Reconcile Alpaca positions against trades table to detect bracket stop-loss/take-profit fills.

    Call this at the start of every factor loop and EOD reflection. It compares
    Alpaca's live positions to the trades table and detects positions that were
    closed by bracket orders (stop-loss or take-profit) without the agent knowing.

    For each detected exit:
    - Updates the protective sell order in trades table to 'filled'
    - Creates a new 'sell' trade record with the fill details
    - Writes a journal entry noting the bracket execution

    Returns:
        Dict with reconciled exits and any errors.
    """
    from alpaca.trading.requests import GetOrdersRequest
    from alpaca.trading.enums import QueryOrderStatus

    client = get_trading_client()
    sb = get_supabase()

    # 1. Get live Alpaca positions
    live_positions = client.get_all_positions()
    live_symbols = {pos.symbol for pos in live_positions}

    # 2. Find symbols we think we hold (open buy fills) but Alpaca says we don't
    open_buys = (
        sb.table("trades")
        .select("symbol, broker_order_id, quantity, filled_avg_price, created_at")
        .eq("side", "buy")
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

                # Record the exit trade
                exit_trade = create_trade(
                    symbol=sym,
                    side="sell",
                    quantity=fill_qty,
                    order_type="market",
                    thesis=f"Bracket {exit_type} executed by Alpaca at ${fill_price:.2f}",
                    order_class="bracket_fill",
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
                    .or_("order_class.eq.oco,order_class.eq.bracket,order_class.eq.stop")
                    .or_("status.ilike.%new%,status.ilike.%accepted%,status.ilike.%pending%")
                    .execute()
                ).data or []
                for po in protective_orders:
                    update_trade(po["id"], {"status": "OrderStatus.FILLED"})

                reconciled.append({
                    "symbol": sym,
                    "exit_type": exit_type,
                    "fill_price": fill_price,
                    "fill_qty": fill_qty,
                    "entry_price": entry_price,
                    "pnl": round(pnl, 2) if pnl is not None else None,
                    "alpaca_order_id": str(fill_order.id),
                })

                # Save exit context for re-entry guard (stop-losses only)
                if exit_type == "stop_loss":
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
