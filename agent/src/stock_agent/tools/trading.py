"""Trading tools: order placement/cancellation, brackets, position reconciliation, pre-trade risk."""

import logging
import time
from datetime import datetime
from typing import Literal

import pandas as pd
from alpaca.trading.requests import (
    MarketOrderRequest,
    LimitOrderRequest,
    TakeProfitRequest,
    StopLossRequest,
)
from alpaca.trading.enums import OrderSide, TimeInForce, OrderClass

from stock_agent.alpaca_client import get_trading_client
from common.db import (
    create_trade,
    update_trade,
    get_risk_settings,
    read_memory,
    write_journal as db_write_journal,
    write_memory as db_write_memory,
)
from stock_agent.market_data import get_portfolio, get_quote
from stock_agent.risk import check_risk
from common.supabase_client import get_supabase
from stock_agent.tools.market import get_historical_data

logger = logging.getLogger(__name__)

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
            from ..factor_scoring import BASELINE_VARIANT
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
            from common.db import delete_memory

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

