"""Alpaca API client singleton for paper trading."""

import os

from alpaca.trading.client import TradingClient
from alpaca.data.historical.stock import StockHistoricalDataClient

_trading_client: TradingClient | None = None
_data_client: StockHistoricalDataClient | None = None


def get_trading_client() -> TradingClient:
    """Get or create the Alpaca trading client (lazy singleton)."""
    global _trading_client
    if _trading_client is None:
        _trading_client = TradingClient(
            api_key=os.environ["ALPACA_API_KEY"],
            secret_key=os.environ["ALPACA_SECRET_KEY"],
            paper=True,
        )
    return _trading_client


def get_data_client() -> StockHistoricalDataClient:
    """Get or create the Alpaca historical data client (lazy singleton)."""
    global _data_client
    if _data_client is None:
        _data_client = StockHistoricalDataClient(
            api_key=os.environ["ALPACA_API_KEY"],
            secret_key=os.environ["ALPACA_SECRET_KEY"],
        )
    return _data_client
