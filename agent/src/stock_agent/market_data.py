"""Market data fetching helpers — yfinance for historical data, Alpaca for live quotes & portfolio."""

import logging
import time
from datetime import datetime, timedelta

import pandas as pd
import yfinance as yf

from stock_agent.alpaca_client import get_data_client, get_trading_client

logger = logging.getLogger(__name__)

# --- S&P 500 + S&P 400 ticker cache ---

_ticker_cache: dict = {"tickers": None, "timestamp": 0.0}
_CACHE_TTL = 86400  # 24 hours


def get_sp500_sp400_tickers() -> list[str]:
    """Fetch S&P 500 + S&P 400 tickers from Wikipedia, cached for 24h."""
    now = time.time()
    if _ticker_cache["tickers"] and (now - _ticker_cache["timestamp"]) < _CACHE_TTL:
        return _ticker_cache["tickers"]

    import io
    import urllib.request

    headers = {"User-Agent": "Mozilla/5.0 (compatible; MonetAgent/1.0)"}
    tickers = []
    try:
        req = urllib.request.Request("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies", headers=headers)
        with urllib.request.urlopen(req) as resp:
            sp500 = pd.read_html(io.StringIO(resp.read().decode("utf-8")))[0]
        tickers.extend(sp500["Symbol"].str.replace(".", "-", regex=False).tolist())
    except Exception:
        logger.warning("Failed to fetch S&P 500 tickers from Wikipedia")

    try:
        req = urllib.request.Request("https://en.wikipedia.org/wiki/List_of_S%26P_400_companies", headers=headers)
        with urllib.request.urlopen(req) as resp:
            sp400 = pd.read_html(io.StringIO(resp.read().decode("utf-8")))[0]
        col = "Symbol" if "Symbol" in sp400.columns else sp400.columns[0]
        tickers.extend(sp400[col].str.replace(".", "-", regex=False).tolist())
    except Exception:
        logger.warning("Failed to fetch S&P 400 tickers from Wikipedia")

    if tickers:
        _ticker_cache["tickers"] = sorted(set(tickers))
        _ticker_cache["timestamp"] = now

    return _ticker_cache["tickers"] or []


def get_quote(symbol: str) -> dict:
    """Get the latest quote for a symbol.

    Uses Alpaca for regular stocks, yfinance for indices (^VIX, ^GSPC, etc.)
    """
    # Handle VIX and other indices — Alpaca doesn't support these
    index_map = {"VIX": "^VIX", "GSPC": "^GSPC", "DJI": "^DJI", "IXIC": "^IXIC"}
    if symbol in index_map or symbol.startswith("^"):
        yf_symbol = index_map.get(symbol, symbol)
        ticker = yf.Ticker(yf_symbol)
        info = ticker.info
        price = info.get("regularMarketPrice") or info.get("previousClose", 0)
        return {
            "symbol": symbol,
            "price": float(price),
            "previous_close": float(info.get("previousClose", 0)),
            "change_pct": float(info.get("regularMarketChangePercent", 0)),
            "timestamp": str(datetime.now()),
        }

    # Regular stocks via Alpaca
    from alpaca.data.requests import StockLatestQuoteRequest
    client = get_data_client()
    request = StockLatestQuoteRequest(symbol_or_symbols=symbol)
    quotes = client.get_stock_latest_quote(request)
    quote = quotes[symbol]
    return {
        "symbol": symbol,
        "ask_price": float(quote.ask_price),
        "ask_size": int(quote.ask_size),
        "bid_price": float(quote.bid_price),
        "bid_size": int(quote.bid_size),
        "timestamp": str(quote.timestamp),
    }


def get_historical_bars(
    symbol: str,
    days: int = 90,
) -> pd.DataFrame:
    """Get historical OHLCV bars as a DataFrame using yfinance."""
    period_map = {
        7: "5d",
        30: "1mo",
        90: "3mo",
        180: "6mo",
        365: "1y",
        730: "2y",
    }
    # Find the smallest period that covers the requested days
    period = "1y"
    for threshold, p in sorted(period_map.items()):
        if days <= threshold:
            period = p
            break

    ticker = yf.Ticker(symbol)
    df = ticker.history(period=period, auto_adjust=True)  # split/dividend adjusted

    if df.empty:
        return pd.DataFrame()

    # Normalize column names to lowercase (yfinance returns capitalized)
    df.columns = [c.lower() for c in df.columns]
    return df


def get_portfolio(portfolio: str = "quant") -> dict:
    """Get current Alpaca portfolio state for a portfolio ("quant" or "conviction")."""
    client = get_trading_client(portfolio)
    account = client.get_account()
    positions = client.get_all_positions()

    position_list = []
    for pos in positions:
        position_list.append({
            "symbol": pos.symbol,
            "qty": float(pos.qty),
            "market_value": float(pos.market_value),
            "cost_basis": float(pos.cost_basis),
            "unrealized_pl": float(pos.unrealized_pl),
            "unrealized_plpc": float(pos.unrealized_plpc),
            "current_price": float(pos.current_price),
            "avg_entry_price": float(pos.avg_entry_price),
        })

    return {
        "equity": float(account.equity),
        "cash": float(account.cash),
        "buying_power": float(account.buying_power),
        "portfolio_value": float(account.portfolio_value),
        "daily_pnl": float(account.equity) - float(account.last_equity),
        "positions": position_list,
    }


def get_historical_data_dict(symbol: str, days: int = 90) -> dict:
    """Get historical data as a serializable dict for tool output."""
    df = get_historical_bars(symbol, days=days)
    if df.empty:
        return {"symbol": symbol, "bars": [], "count": 0}

    bars = []
    for idx, row in df.iterrows():
        bars.append({
            "date": str(idx),
            "open": round(float(row["open"]), 2),
            "high": round(float(row["high"]), 2),
            "low": round(float(row["low"]), 2),
            "close": round(float(row["close"]), 2),
            "volume": int(row["volume"]),
        })

    return {
        "symbol": symbol,
        "bars": bars[-60:],  # Last 60 bars
        "count": len(bars),
        "latest_close": bars[-1]["close"] if bars else None,
    }
