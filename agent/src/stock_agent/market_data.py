"""Market data fetching helpers using Alpaca."""

import logging
from datetime import datetime, timedelta

import pandas as pd
from alpaca.data.requests import StockLatestQuoteRequest, StockBarsRequest
from alpaca.data.timeframe import TimeFrame

from stock_agent.alpaca_client import get_data_client, get_trading_client

logger = logging.getLogger(__name__)


def get_quote(symbol: str) -> dict:
    """Get the latest quote for a symbol."""
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
    timeframe: str = "1Day",
) -> pd.DataFrame:
    """Get historical OHLCV bars as a DataFrame."""
    client = get_data_client()

    tf_map = {
        "1Min": TimeFrame.Minute,
        "5Min": TimeFrame(5, "Min"),
        "15Min": TimeFrame(15, "Min"),
        "1Hour": TimeFrame.Hour,
        "1Day": TimeFrame.Day,
        "1Week": TimeFrame.Week,
    }
    tf = tf_map.get(timeframe, TimeFrame.Day)

    end = datetime.now()
    start = end - timedelta(days=days)

    request = StockBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=tf,
        start=start,
        end=end,
    )
    bars = client.get_stock_bars(request)
    df = bars.df
    if isinstance(df.index, pd.MultiIndex):
        df = df.droplevel(0)
    return df


def get_portfolio() -> dict:
    """Get current Alpaca portfolio state."""
    client = get_trading_client()
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
