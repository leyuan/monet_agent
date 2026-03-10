"""Stock Agent tools — autonomous-mode and chat-mode."""

import logging
import os
from datetime import datetime, timedelta
from typing import Literal

import time

import pandas as pd
import yfinance as yf
from alpaca.trading.requests import MarketOrderRequest, LimitOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
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
) -> dict:
    """Place a trade order via Alpaca paper trading.

    IMPORTANT: Always run check_trade_risk first. This tool should only be called
    from the autonomous loop, never from chat mode.

    Args:
        symbol: Stock ticker symbol.
        side: "buy" or "sell".
        quantity: Number of shares.
        order_type: "market" or "limit".
        limit_price: Required if order_type is "limit".
        thesis: The reasoning behind this trade.
        confidence: Confidence score 0.0-1.0.

    Returns:
        Dict with order details and trade record.
    """
    # Risk check
    risk = check_risk(symbol, side, quantity, limit_price)
    if not risk["approved"]:
        return {"error": f"Risk check failed: {risk['reason']}", "risk": risk}

    # Place order with Alpaca
    client = get_trading_client()
    order_side = OrderSide.BUY if side == "buy" else OrderSide.SELL

    if order_type == "limit" and limit_price is not None:
        request = LimitOrderRequest(
            symbol=symbol,
            qty=quantity,
            side=order_side,
            time_in_force=TimeInForce.DAY,
            limit_price=limit_price,
        )
    else:
        request = MarketOrderRequest(
            symbol=symbol,
            qty=quantity,
            side=order_side,
            time_in_force=TimeInForce.DAY,
        )

    order = client.submit_order(request)

    # Record in database
    trade = create_trade(
        symbol=symbol,
        side=side,
        quantity=quantity,
        order_type=order_type,
        limit_price=limit_price,
        thesis=thesis,
        confidence=confidence,
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
        "status": final_status,
        "filled_avg_price": filled_avg_price,
        "filled_quantity": filled_qty,
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
        f"Today is {today}. This is an automated end-of-day recap request.\n\n"
        "Query today's journal entries:\n"
        "```sql\n"
        "SELECT entry_type, title, content, symbols, created_at\n"
        "FROM agent_journal\n"
        "WHERE created_at >= CURRENT_DATE\n"
        "ORDER BY created_at\n"
        "```\n\n"
        "Also check today's trades:\n"
        "```sql\n"
        "SELECT symbol, side, quantity, order_type, limit_price, status, thesis, confidence, created_at\n"
        "FROM trades\n"
        "WHERE created_at >= CURRENT_DATE\n"
        "ORDER BY created_at\n"
        "```\n\n"
        "Based on the data, write a concise daily recap covering:\n"
        "1. **Research highlights** — what did you look into today and why?\n"
        "2. **Analysis** — key findings, price targets set or updated\n"
        "3. **Trades & orders** — any orders placed (market or limit), positions managed, or why you stood pat\n"
        "4. **Self-improvement** — this is the most important part. Be specific about what you could do better:\n"
        "   - Were there missed opportunities? (e.g. stock hit target but you weren't running)\n"
        "   - Could you have used a different order type? (e.g. limit orders to catch intraday dips)\n"
        "   - Were your price targets realistic or too tight/wide?\n"
        "   - Did you over-research or under-research anything?\n"
        "   - Any process changes that would help tomorrow?\n"
        "5. **Tomorrow's watchlist** — 2-3 things you're watching for\n\n"
        "Keep it short and punchy — a few sentences per section. "
        "I'll dig into the journal if something catches my eye."
    )

    try:
        client = get_sync_client()
        thread = client.threads.create(
            metadata={"title": f"Daily Recap — {today}"},
        )
        client.runs.create(
            thread["thread_id"],
            assistant_id="monet_agent",
            input={"messages": [{"role": "user", "content": recap_prompt}]},
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
    market_breadth,
    place_order,
    cancel_order,
    get_open_orders,
    read_agent_memory,
    read_all_agent_memory,
    write_agent_memory,
    write_journal_entry,
    manage_watchlist,
    get_portfolio_state,
    check_trade_risk,
    query_database,
    send_daily_recap,
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
    submit_user_insight,
]
