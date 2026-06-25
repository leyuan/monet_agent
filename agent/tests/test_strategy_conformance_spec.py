from review_agent.strategy_conformance import (
    resolve_spec, run_severity, VERIFIED_RULES, UNVERIFIABLE_RULES, KNOWN_STRATEGY_RULES,
)


def test_resolve_spec_picks_effective_dated_version():
    spec = resolve_spec("2026-06-19")
    assert spec["min_hold_trading_days"] == 5
    assert spec["max_positions"] == 8
    assert spec["min_positions_soft"] == 5


def test_resolve_spec_falls_back_to_oldest_for_early_dates():
    spec = resolve_spec("2000-01-01")           # predates all versions
    assert spec["max_positions"] == 8           # oldest version, not a crash


def test_rule_partition_is_clean():
    assert VERIFIED_RULES.isdisjoint(UNVERIFIABLE_RULES)
    assert KNOWN_STRATEGY_RULES == VERIFIED_RULES | UNVERIFIABLE_RULES
    assert "anti_churn" in VERIFIED_RULES
    assert "risk_limit_leak" in UNVERIFIABLE_RULES   # v1 deviation


def test_run_severity_is_worst_and_unverifiable_never_raises():
    facts = [
        {"rule": "a", "status": "conformant", "severity": "pass"},
        {"rule": "b", "status": "unverifiable", "severity": "info"},
        {"rule": "c", "status": "violated", "severity": "warn"},
    ]
    assert run_severity(facts) == "warn"
    assert run_severity([{"rule": "x", "status": "unverifiable", "severity": "info"}]) == "info"


def test_resolve_spec_returns_independent_copy():
    a = resolve_spec("2026-06-19")
    a["max_positions"] = 999                     # mutate the returned dict
    b = resolve_spec("2026-06-19")
    assert b["max_positions"] == 8               # module spec is unaffected
