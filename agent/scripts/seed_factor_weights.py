"""Seed the factor_weights memory entry for the factor-based trading system."""

from dotenv import load_dotenv
load_dotenv()

from stock_agent.db import write_memory


def main():
    weights = {
        "momentum": 0.35,
        "quality": 0.30,
        "value": 0.20,
        "eps_revision": 0.15,
        "adjusted_at": "2026-03-12",
        "reason": "Initial factor weights — balanced across momentum, quality, value, and EPS revisions",
    }

    result = write_memory("factor_weights", weights)
    print(f"Seeded factor_weights (id={result.get('id', 'ok')})")
    for k, v in weights.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
