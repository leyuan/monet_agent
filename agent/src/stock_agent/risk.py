"""Risk management engine."""

import logging
from datetime import datetime, timedelta

from stock_agent.db import get_risk_settings
from stock_agent.market_data import get_portfolio, get_quote

logger = logging.getLogger(__name__)


def check_risk(symbol: str, side: str, quantity: float, limit_price: float | None = None) -> dict:
    """Validate a proposed trade against risk rules.

    Returns:
        Dict with 'approved' bool, 'reason' if rejected, and risk metrics.
    """
    settings = get_risk_settings()
    portfolio = get_portfolio()

    equity = portfolio["equity"]
    if equity <= 0:
        return {"approved": False, "reason": "Account equity is zero or negative"}

    # Get current price
    quote = get_quote(symbol)
    price = limit_price or quote["ask_price"]
    trade_value = price * quantity

    # Check 1: Position size limit
    max_position_value = equity * (float(settings["max_position_pct"]) / 100)
    existing_position_value = 0
    for pos in portfolio["positions"]:
        if pos["symbol"] == symbol:
            existing_position_value = pos["market_value"]
            break

    if side == "buy":
        new_position_value = existing_position_value + trade_value
        if new_position_value > max_position_value:
            return {
                "approved": False,
                "reason": f"Position would be {new_position_value:.0f} ({new_position_value/equity*100:.1f}% of equity), exceeds {settings['max_position_pct']}% limit of {max_position_value:.0f}",
                "metrics": {
                    "trade_value": trade_value,
                    "existing_position": existing_position_value,
                    "new_position": new_position_value,
                    "max_allowed": max_position_value,
                },
            }

    # Check 2: Total exposure limit
    total_exposure = sum(pos["market_value"] for pos in portfolio["positions"])
    if side == "buy":
        new_exposure = total_exposure + trade_value
        max_exposure = equity * (float(settings["max_total_exposure_pct"]) / 100)
        if new_exposure > max_exposure:
            return {
                "approved": False,
                "reason": f"Total exposure would be {new_exposure:.0f} ({new_exposure/equity*100:.1f}%), exceeds {settings['max_total_exposure_pct']}% limit",
                "metrics": {
                    "current_exposure": total_exposure,
                    "new_exposure": new_exposure,
                    "max_allowed": max_exposure,
                },
            }

    # Check 3: Daily loss limit
    daily_pnl = portfolio["daily_pnl"]
    max_daily_loss = float(settings["max_daily_loss"])
    if daily_pnl < -max_daily_loss:
        return {
            "approved": False,
            "reason": f"Daily loss of {daily_pnl:.2f} exceeds max daily loss limit of {max_daily_loss:.2f}",
            "metrics": {"daily_pnl": daily_pnl, "max_daily_loss": max_daily_loss},
        }

    # Check 4: Sufficient cash (use actual cash, not margin buying power)
    cash = portfolio["cash"]
    if side == "buy" and trade_value > cash:
        return {
            "approved": False,
            "reason": f"Insufficient cash. Need {trade_value:.2f}, have {cash:.2f} (not using margin)",
        }

    # Check 5: Earnings proximity — HARD BLOCK for buys within 2 days
    # Uses Finnhub first, then yfinance as fallback (Finnhub misses dates).
    earnings_warning = None
    earnings_date_str = None
    days_until_earnings = None

    if side == "buy":
        today = datetime.now()

        # Try Finnhub
        try:
            from stock_agent.finnhub_client import get_finnhub
            fh = get_finnhub()
            cal = fh.earnings_calendar(
                _from=today.strftime("%Y-%m-%d"),
                to=(today + timedelta(days=7)).strftime("%Y-%m-%d"),
                symbol=symbol,
            )
            upcoming = cal.get("earningsCalendar", [])
            if upcoming:
                earnings_date_str = upcoming[0]["date"]
                days_until_earnings = (datetime.strptime(earnings_date_str, "%Y-%m-%d") - today).days
        except Exception:
            pass

        # Fallback: yfinance if Finnhub returned nothing
        if days_until_earnings is None:
            try:
                import yfinance as yf_lib
                ticker = yf_lib.Ticker(symbol)
                cal_data = ticker.calendar
                if cal_data is not None:
                    raw_date = None
                    if isinstance(cal_data, dict):
                        raw = cal_data.get("Earnings Date", [])
                        raw_date = raw[0] if raw else None
                    elif hasattr(cal_data, "loc"):
                        try:
                            raw = cal_data.loc["Earnings Date"]
                            raw_date = raw.iloc[0] if hasattr(raw, "iloc") else raw
                        except (KeyError, IndexError):
                            pass

                    if raw_date is not None:
                        from pandas import Timestamp
                        if isinstance(raw_date, Timestamp):
                            raw_date = raw_date.to_pydatetime()
                        if isinstance(raw_date, datetime):
                            days_until_earnings = (raw_date - today).days
                            earnings_date_str = raw_date.strftime("%Y-%m-%d")
                            logger.info("yfinance fallback found earnings for %s on %s (risk check)", symbol, earnings_date_str)
            except Exception:
                pass

        if days_until_earnings is not None and earnings_date_str:
            if days_until_earnings <= 2:
                return {
                    "approved": False,
                    "reason": f"EARNINGS GUARD: {symbol} reports earnings on {earnings_date_str} ({days_until_earnings} day(s) away). Buying within 2 days of earnings is blocked — binary risk.",
                    "metrics": {
                        "trade_value": trade_value,
                        "earnings_date": earnings_date_str,
                        "days_until_earnings": days_until_earnings,
                    },
                }
            elif days_until_earnings <= 5:
                earnings_warning = f"{symbol} reports earnings in {days_until_earnings} day(s) on {earnings_date_str}. Pre-earnings caution advised."

    return {
        "approved": True,
        "earnings_warning": earnings_warning,
        "metrics": {
            "trade_value": trade_value,
            "position_pct": (existing_position_value + trade_value) / equity * 100 if side == "buy" else 0,
            "total_exposure_pct": (total_exposure + (trade_value if side == "buy" else -trade_value)) / equity * 100,
            "daily_pnl": daily_pnl,
            "cash_remaining": cash - (trade_value if side == "buy" else 0),
        },
    }
