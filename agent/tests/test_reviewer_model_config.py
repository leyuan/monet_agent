"""The reviewer resolves its own model so it can be decorrelated from the trader.

Precedence: REVIEWER_MODEL_NAME → MODEL_NAME (shared with the trader) → default.
A different model family gives the reviewer independent blind spots; see the
shared-model correlation risk discussed in the reviewer design.

`_resolve_model_name` is a pure function, but importing `review_agent.reviewer`
builds the graph at module load — so import it ONCE here under the ambient env
(default Anthropic model), then monkeypatch + call per test. Setting a keyless
provider before the first import would fail graph construction, not the function.
"""
from review_agent.reviewer import _resolve_model_name


def test_reviewer_model_name_overrides_shared_model(monkeypatch):
    """REVIEWER_MODEL_NAME wins even when MODEL_NAME is also set."""
    monkeypatch.setenv("REVIEWER_MODEL_NAME", "openai:gpt-x")
    monkeypatch.setenv("MODEL_NAME", "anthropic:claude-sonnet-4-5-20250929")
    assert _resolve_model_name() == "openai:gpt-x"


def test_falls_back_to_shared_model_name(monkeypatch):
    """No REVIEWER_MODEL_NAME → use the trader's MODEL_NAME (stay shared)."""
    monkeypatch.delenv("REVIEWER_MODEL_NAME", raising=False)
    monkeypatch.setenv("MODEL_NAME", "anthropic:claude-sonnet-4-6")
    assert _resolve_model_name() == "anthropic:claude-sonnet-4-6"


def test_falls_back_to_default_when_unset(monkeypatch):
    """Neither var set → the built-in default."""
    monkeypatch.delenv("REVIEWER_MODEL_NAME", raising=False)
    monkeypatch.delenv("MODEL_NAME", raising=False)
    assert _resolve_model_name() == "anthropic:claude-sonnet-4-5-20250929"
