from review_agent.strategy_conformance import trading_days_between, reconstruct_open_positions


def _t(symbol, side, qty, created_at, stop=None, order_class="simple"):
    return {"symbol": symbol, "side": side, "filled_quantity": qty, "quantity": qty,
            "stop_loss_price": stop, "created_at": created_at, "order_class": order_class}


def test_trading_days_between_counts_weekdays():
    # Fri 2026-06-19 -> Wed 2026-06-24: Mon22, Tue23, Wed24 = 3 trading days
    assert trading_days_between("2026-06-19T14:00:00+00:00", "2026-06-24T14:00:00+00:00") == 3


def test_trading_days_between_handles_bad_or_reversed_input():
    assert trading_days_between("nonsense", "2026-06-24T00:00:00+00:00") == 0
    assert trading_days_between("2026-06-24T00:00:00+00:00", "2026-06-19T00:00:00+00:00") == 0


def test_reconstruct_open_positions_nets_buys_and_sells():
    trades = [
        _t("AAPL", "buy", 10, "2026-06-10T14:00:00+00:00", stop=180.0),
        _t("MSFT", "buy", 5, "2026-06-11T14:00:00+00:00", stop=400.0),
        _t("AAPL", "sell", 10, "2026-06-15T14:00:00+00:00"),   # closes AAPL
    ]
    held = reconstruct_open_positions(trades, "2026-06-20T00:00:00+00:00")
    assert set(held) == {"MSFT"}
    assert held["MSFT"]["opened_at"] == "2026-06-11T14:00:00+00:00"
    assert held["MSFT"]["stop_loss_price"] == 400.0


def test_reconstruct_is_point_in_time():
    trades = [
        _t("AAPL", "buy", 10, "2026-06-10T14:00:00+00:00", stop=180.0),
        _t("AAPL", "sell", 10, "2026-06-15T14:00:00+00:00"),
    ]
    # as_of before the sell → still held
    assert set(reconstruct_open_positions(trades, "2026-06-12T00:00:00+00:00")) == {"AAPL"}
    # as_of after the sell → flat
    assert reconstruct_open_positions(trades, "2026-06-16T00:00:00+00:00") == {}
