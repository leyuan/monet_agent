"""Cross-category helpers shared by more than one tools submodule."""

import logging

from stock_agent.db import read_memory

logger = logging.getLogger(__name__)


def _avg_return(sectors: list[dict], etf_set: set[str]) -> float:
    """Average return for a set of sector ETFs."""
    vals = [s["total_return"] for s in sectors if s["etf"] in etf_set]
    return sum(vals) / len(vals) if vals else 0.0


_DEFAULT_FACTOR_WEIGHTS = {"momentum": 0.35, "quality": 0.30, "value": 0.20, "eps_revision": 0.15}


def _load_factor_weights() -> dict:
    """Load factor weights from agent_memory, falling back to defaults."""
    try:
        result = read_memory("factor_weights")
        if result and result.get("value"):
            stored = result["value"]
            return {
                "momentum": float(stored.get("momentum", _DEFAULT_FACTOR_WEIGHTS["momentum"])),
                "quality": float(stored.get("quality", _DEFAULT_FACTOR_WEIGHTS["quality"])),
                "value": float(stored.get("value", _DEFAULT_FACTOR_WEIGHTS["value"])),
                "eps_revision": float(stored.get("eps_revision", _DEFAULT_FACTOR_WEIGHTS["eps_revision"])),
            }
    except Exception:
        logger.warning("Failed to load factor_weights from memory, using defaults")
    return _DEFAULT_FACTOR_WEIGHTS.copy()
