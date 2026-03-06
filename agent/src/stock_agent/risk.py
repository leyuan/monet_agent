"""Risk management engine."""

import logging

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

    # Check 4: Sufficient buying power
    if side == "buy" and trade_value > portfolio["buying_power"]:
        return {
            "approved": False,
            "reason": f"Insufficient buying power. Need {trade_value:.2f}, have {portfolio['buying_power']:.2f}",
        }

    return {
        "approved": True,
        "metrics": {
            "trade_value": trade_value,
            "position_pct": (existing_position_value + trade_value) / equity * 100 if side == "buy" else 0,
            "total_exposure_pct": (total_exposure + (trade_value if side == "buy" else -trade_value)) / equity * 100,
            "daily_pnl": daily_pnl,
            "buying_power_remaining": portfolio["buying_power"] - (trade_value if side == "buy" else 0),
        },
    }
