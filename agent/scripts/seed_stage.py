"""Seed the agent_stage memory entry to initialize the explore/exploit lifecycle."""

from dotenv import load_dotenv
load_dotenv()

from stock_agent.db import write_memory


def main():
    stage = {
        "stage": "explore",
        "started_at": "2026-03-07",
        "watchlist_profiles": 0,
        "total_trades": 0,
        "cycles_completed": 0,
    }

    result = write_memory("agent_stage", stage)
    print(f"Seeded agent_stage to 'explore' (id={result.get('id', 'ok')})")
    print(f"  Stage: {stage['stage']}")
    print(f"  Started: {stage['started_at']}")
    print(f"  Profiles: {stage['watchlist_profiles']}")
    print(f"  Trades: {stage['total_trades']}")
    print(f"  Cycles: {stage['cycles_completed']}")


if __name__ == "__main__":
    main()
