from review_agent.strategy_conformance import (
    _check_factor_weights_conformance, _check_regime_gate, classify_conformance,
    KNOWN_STRATEGY_RULES, UNVERIFIABLE_RULES,
)

SPEC = {"min_hold_trading_days": 5, "max_positions": 8, "min_positions_soft": 5}


def _base_ctx(**over):
    ctx = {"spec": SPEC, "trades_window": [], "trades_history": [],
           "run_end": "2026-06-30T00:00:00+00:00",
           "factor_weights": None, "factor_weights_stale": False,
           "factor_rankings": None, "market_regime": None, "market_regime_in_window": False}
    ctx.update(over)
    return ctx


def test_factor_weights_conformant_when_matching():
    w = {"momentum": 0.35, "quality": 0.30, "value": 0.20, "eps_revision": 0.15}
    f = _check_factor_weights_conformance(_base_ctx(
        factor_weights=w, factor_rankings={"factor_weights": dict(w)}))
    assert f["status"] == "conformant"


def test_factor_weights_violated_when_run_used_stale_weights():
    active = {"momentum": 0.45, "quality": 0.30, "value": 0.15, "eps_revision": 0.10}
    used = {"momentum": 0.35, "quality": 0.30, "value": 0.20, "eps_revision": 0.15}
    f = _check_factor_weights_conformance(_base_ctx(
        factor_weights=active, factor_rankings={"factor_weights": used}))
    assert f["status"] == "violated" and f["severity"] == "warn"
    assert "momentum" in f["evidence"]["diffs"]


def test_factor_weights_unverifiable_when_active_changed_after_run():
    w = {"momentum": 0.35}
    f = _check_factor_weights_conformance(_base_ctx(
        factor_weights=w, factor_rankings={"factor_weights": {"momentum": 0.40}},
        factor_weights_stale=True))
    assert f["status"] == "unverifiable" and f["severity"] == "info"


def test_regime_gate_violated_when_buy_during_hard_block():
    buy = {"symbol": "AAPL", "side": "buy", "created_at": "2026-06-19T14:00:00+00:00",
           "filled_quantity": 1, "quantity": 1, "stop_loss_price": 1.0, "order_class": "simple"}
    f = _check_regime_gate(_base_ctx(
        trades_window=[buy], market_regime={"vix": 30, "breadth_pct": 20},
        market_regime_in_window=True))
    assert f["status"] == "violated" and f["severity"] == "fail"


def test_regime_gate_unverifiable_when_no_regime_in_window():
    f = _check_regime_gate(_base_ctx(market_regime=None, market_regime_in_window=False))
    assert f["status"] == "unverifiable"


def test_classify_emits_exactly_the_known_rule_set():
    facts = classify_conformance(_base_ctx())
    emitted = {f["rule"] for f in facts}
    assert emitted == KNOWN_STRATEGY_RULES               # runtime coverage guarantee
    # every unverifiable rule reports unverifiable
    by = {f["rule"]: f for f in facts}
    for r in UNVERIFIABLE_RULES:
        assert by[r]["status"] == "unverifiable"
