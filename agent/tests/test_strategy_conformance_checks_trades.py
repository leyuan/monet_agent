from review_agent.strategy_conformance import (
    _check_anti_churn, _check_position_count, _check_stops_present,
)

SPEC = {"min_hold_trading_days": 5, "max_positions": 8, "min_positions_soft": 5}


def _t(symbol, side, qty, created_at, stop=180.0, order_class="simple"):
    return {"symbol": symbol, "side": side, "filled_quantity": qty, "quantity": qty,
            "stop_loss_price": stop, "created_at": created_at, "order_class": order_class}


def _ctx(window, history=None, run_end="2026-06-30T00:00:00+00:00"):
    return {"spec": SPEC, "trades_window": window,
            "trades_history": history if history is not None else window, "run_end": run_end}


def test_anti_churn_flags_early_discretionary_sell():
    buy = _t("AAPL", "buy", 10, "2026-06-15T14:00:00+00:00")
    sell = _t("AAPL", "sell", 10, "2026-06-17T14:00:00+00:00")        # 2 trading days < 5
    f = _check_anti_churn(_ctx([buy, sell]))
    assert f["status"] == "violated" and f["severity"] == "fail"


def test_anti_churn_exempts_bracket_fill_exits():
    buy = _t("AAPL", "buy", 10, "2026-06-15T14:00:00+00:00")
    stop_exit = _t("AAPL", "sell", 10, "2026-06-16T14:00:00+00:00", order_class="bracket_fill")
    f = _check_anti_churn(_ctx([buy, stop_exit]))
    assert f["status"] == "conformant"


def test_anti_churn_passes_when_held_long_enough():
    buy = _t("AAPL", "buy", 10, "2026-06-08T14:00:00+00:00")
    sell = _t("AAPL", "sell", 10, "2026-06-17T14:00:00+00:00")        # 7 trading days >= 5
    f = _check_anti_churn(_ctx([buy, sell]))
    assert f["status"] == "conformant"


def test_position_count_warns_when_over_cap():
    hist = [_t(f"S{i}", "buy", 1, f"2026-06-1{i}T14:00:00+00:00") for i in range(9)]  # 9 > 8
    last_buy = hist[-1]
    f = _check_position_count(_ctx([last_buy], history=hist))
    assert f["status"] == "violated" and f["severity"] == "warn"
    assert f["evidence"]["overages"]


def test_position_count_conformant_within_band():
    hist = [_t(f"S{i}", "buy", 1, f"2026-06-1{i}T14:00:00+00:00") for i in range(6)]  # 6 in [5,8]
    f = _check_position_count(_ctx([hist[-1]], history=hist))
    assert f["status"] == "conformant"


def test_stops_present_flags_missing_stop():
    buy = _t("AAPL", "buy", 10, "2026-06-15T14:00:00+00:00", stop=None)
    f = _check_stops_present(_ctx([buy]))
    assert f["status"] == "violated" and f["severity"] == "fail"


def test_stops_present_passes_when_all_buys_have_stops():
    buy = _t("AAPL", "buy", 10, "2026-06-15T14:00:00+00:00", stop=170.0)
    f = _check_stops_present(_ctx([buy]))
    assert f["status"] == "conformant"
