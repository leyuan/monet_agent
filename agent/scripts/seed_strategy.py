"""One-time script to seed Monet Agent's founding strategy."""

from dotenv import load_dotenv
load_dotenv()

from stock_agent.db import write_memory, write_journal
from stock_agent.supabase_client import get_supabase


def seed_memory():
    """Seed the 3 founding memory entries."""
    entries = {
        "strategy": {
            "summary": (
                "Momentum + mean reversion hybrid on US large/mid-caps. "
                "Buy quality at support, breakouts with volume. "
                "Goal: beat S&P 500 consistently with disciplined risk management."
            ),
            "approach": "momentum_mean_reversion",
            "universe": "US large/mid-cap",
            "max_positions": 8,
        },
        "market_outlook": {
            "summary": (
                "Fresh start. No positions yet. Need to assess current macro conditions, "
                "sector rotation, and market regime in first research cycle."
            ),
            "regime": "unknown",
            "assessed_at": None,
        },
        "risk_appetite": {
            "summary": (
                "Moderate-conservative. Capital preservation first, alpha second. "
                "Start with smaller positions until track record is established. "
                "Scale up as confidence calibration improves."
            ),
            "level": "moderate-conservative",
        },
    }

    for key, value in entries.items():
        result = write_memory(key, value)
        print(f"  Memory '{key}' written (id={result.get('id', 'ok')})")


def seed_journal():
    """Seed the founding journal entry."""
    content = """\
## Benchmark
S&P 500 total return — not chasing home runs, just consistent alpha.

## Core Approach: Momentum + Mean Reversion
- Buy strong stocks pulling back to support (50-day SMA)
- Breakout entries with volume confirmation
- Sell at resistance, trailing stops, or thesis invalidation

## Position Sizing
- Max 5-8 positions at a time
- 10% max per position
- 20% cash buffer always maintained

## Risk Rules
- 5% stop loss per trade
- 80% max total exposure
- $500 daily loss limit

## Edge
Systematic 4-phase loop: research, analyze, trade, reflect.
Learning from every outcome — wins and losses alike.

## Self-Improvement Commitment
After each cycle:
1. Compare outcomes to thesis
2. Calibrate confidence scores
3. Update beliefs in memory
4. Journal what I learned"""

    result = write_journal(
        entry_type="reflection",
        title="Founding Strategy: Disciplined Momentum to Beat the S&P 500",
        content=content,
    )
    print(f"  Journal entry written (id={result.get('id', 'ok')})")


def seed_risk_settings():
    """Upsert the risk settings row."""
    sb = get_supabase()
    row = {
        "max_position_pct": 10.0,
        "max_daily_loss": 500.0,
        "max_total_exposure_pct": 80.0,
        "default_stop_loss_pct": 5.0,
    }
    # Delete any existing rows, then insert fresh
    sb.table("risk_settings").delete().neq("id", "00000000-0000-0000-0000-000000000000").execute()
    result = sb.table("risk_settings").insert(row).execute()
    print(f"  Risk settings upserted (rows={len(result.data)})")


def main():
    print("Seeding Monet Agent's founding strategy...\n")

    print("[1/3] Writing memory entries...")
    seed_memory()

    print("\n[2/3] Writing founding journal entry...")
    seed_journal()

    print("\n[3/3] Upserting risk settings...")
    seed_risk_settings()

    print("\nDone! Monet Agent is ready to trade.")


if __name__ == "__main__":
    main()
