"""Alpaca API clients for paper trading — one trading client per portfolio.

Two portfolios run on two separate Alpaca paper accounts for clean P&L isolation:
  - "quant"      → Quant Core (systematic factor strategy)  → ALPACA_API_KEY / ALPACA_SECRET_KEY
  - "conviction" → Conviction (concentrated cyclical book)  → ALPACA_API_KEY_CONVICTION / ALPACA_SECRET_KEY_CONVICTION

The market-data client is account-agnostic (prices are the same for everyone),
so it stays a single shared client keyed off the primary (quant) credentials.
"""

import os

from alpaca.trading.client import TradingClient
from alpaca.data.historical.stock import StockHistoricalDataClient

# Per-portfolio credential env-var names. Falls back to "quant" for unknown slugs.
_CREDS: dict[str, tuple[str, str]] = {
    "quant": ("ALPACA_API_KEY", "ALPACA_SECRET_KEY"),
    "conviction": ("ALPACA_API_KEY_CONVICTION", "ALPACA_SECRET_KEY_CONVICTION"),
}

_trading_clients: dict[str, TradingClient] = {}
_data_client: StockHistoricalDataClient | None = None


def get_trading_client(portfolio: str = "quant") -> TradingClient:
    """Get or create the Alpaca trading client for a portfolio (lazy, cached).

    portfolio: "quant" (default, Quant Core) or "conviction" (Conviction book).
    TradingClient(paper=True) targets paper-api.alpaca.markets and appends /v2
    automatically — no base URL is passed.
    """
    if portfolio not in _trading_clients:
        key_env, secret_env = _CREDS.get(portfolio, _CREDS["quant"])
        _trading_clients[portfolio] = TradingClient(
            api_key=os.environ[key_env],
            secret_key=os.environ[secret_env],
            paper=True,
        )
    return _trading_clients[portfolio]


def get_data_client() -> StockHistoricalDataClient:
    """Get or create the shared Alpaca historical data client (account-agnostic)."""
    global _data_client
    if _data_client is None:
        _data_client = StockHistoricalDataClient(
            api_key=os.environ["ALPACA_API_KEY"],
            secret_key=os.environ["ALPACA_SECRET_KEY"],
        )
    return _data_client
