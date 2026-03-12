"""Create Monet Agent's scheduled cron jobs on LangGraph Platform.

Factor-based trading system — all trading runs use factor-loop.

Weekdays (Mon-Fri) — 3 runs/day = 15/week:
- 10:00 AM ET (14:00 UTC) — Factor loop (score_universe → signals → execute)
- 1:00 PM ET  (17:00 UTC) — Factor loop (reuses 4hr cache, checks earnings reactions)
- 4:00 PM ET  (20:00 UTC) — Reflection (factor performance evaluation, recap)

Weekends — 1 run/day = 2/week:
- Sat 11:00 AM ET (15:00 UTC) — Factor loop weekend mode (full 50-stock ranking, no execution)
- Sun 11:00 AM ET (15:00 UTC) — Weekly Review (factor weight optimization, performance review)

All times EDT (UTC-4). Adjust for EST (UTC-5) when DST ends.
"""

import asyncio
import os

from dotenv import load_dotenv
from langgraph_sdk import get_client

load_dotenv()

LANGGRAPH_URL = "https://monet-0f211e9ce05255c2a85f92d6847873b5.us.langgraph.app"
LANGSMITH_API_KEY = os.environ["LANGSMITH_API_KEY"]


CRONS = [
    {
        "name": "Morning Factor Loop (10 AM ET, Mon-Fri)",
        "schedule": "0 14 * * 1-5",
        "message": (
            "Run the factor-based trading loop. Execute this phase:\n\n"
            "1. **Factor Loop** — Read /skills/factor-loop/SKILL.md and execute ALL steps (0-5)\n\n"
            "This is the systematic pipeline: load context → market regime → "
            "score_universe → enrich_eps_revisions → generate_factor_rankings → "
            "earnings guard → execute signals → record.\n\n"
            "When writing journal entries, set run_source='factor_loop'."
        ),
    },
    {
        "name": "Midday Factor Loop (1 PM ET, Mon-Fri)",
        "schedule": "0 17 * * 1-5",
        "message": (
            "Run the factor-based trading loop. Execute this phase:\n\n"
            "1. **Factor Loop** — Read /skills/factor-loop/SKILL.md and execute ALL steps (0-5)\n\n"
            "This is the systematic pipeline: load context → market regime → "
            "score_universe → enrich_eps_revisions → generate_factor_rankings → "
            "earnings guard → execute signals → record.\n\n"
            "IMPORTANT: Start by loading all memory and recent journal entries so you "
            "build on the morning's work instead of repeating it. The 4-hour cache "
            "means score_universe() will reuse the morning's data if the legacy loop ran at 10am.\n\n"
            "When writing journal entries, set run_source='factor_loop'."
        ),
    },
    {
        "name": "End of Day Reflection (4 PM ET, Mon-Fri)",
        "schedule": "0 20 * * 1-5",
        "message": (
            "Run the end-of-day reflection. Execute this phase:\n\n"
            "1. **Reflection** — Read /skills/reflection/SKILL.md and execute ALL steps\n\n"
            "This is a lightweight review — NO research, NO trading. Focus on:\n"
            "- Reviewing today's decisions and their outcomes\n"
            "- Factor performance evaluation (did high-composite stocks outperform?)\n"
            "- Factor weight assessment (which factors contributing to winners?)\n"
            "- Updating beliefs and risk appetite\n"
            "- Cleaning up stale orders and watchlist\n"
            "- Sending daily recap (LAST STEP)\n\n"
            "When writing journal entries, set run_source='eod_reflection'."
        ),
    },
    {
        "name": "Saturday Factor Loop — Weekend Mode (11 AM ET, Sat)",
        "schedule": "0 15 * * 6",
        "message": (
            "Run the Saturday factor loop in weekend mode. Execute this phase:\n\n"
            "1. **Factor Loop** — Read /skills/factor-loop/SKILL.md and execute ALL steps\n\n"
            "This is the WEEKEND variant:\n"
            "- Run score_universe(top_n=50) for a broader view\n"
            "- Still enrich top 20 with EPS revisions\n"
            "- NO trade execution (market is closed) — skip Step 4 entirely\n"
            "- Write comprehensive journal entry with full top 50 ranking\n"
            "- Compare rankings vs last week's factor_rankings memory\n"
            "- Note which stocks entered/exited the top 20\n\n"
            "When writing journal entries, set run_source='factor_loop_weekend'."
        ),
    },
    {
        "name": "Sunday Weekly Review (11 AM ET, Sun)",
        "schedule": "0 15 * * 0",
        "message": (
            "Run the Sunday weekly review. Execute this phase:\n\n"
            "1. **Weekly Review** — Read /skills/weekly-review/SKILL.md\n"
            "   - Full portfolio performance review vs SPY\n"
            "   - Factor system evaluation: which factors drove winners/losers\n"
            "   - Factor weight optimization (±0.05 max per week)\n"
            "   - Sector concentration check\n"
            "   - Ranking stability analysis (top 20 turnover)\n"
            "   - Write comprehensive weekly reflection journal entry\n\n"
            "This is your most important session of the week. Be data-driven and honest.\n\n"
            "When writing journal entries, set run_source='weekly_review'."
        ),
    },
    {
        "name": "Price Alert Check (every 15 min, market hours)",
        "schedule": "*/15 14-20 * * 1-5",
        "message": (
            "Run the price alert check. Execute this phase:\n\n"
            "1. **Price Check** — Read /skills/price-check/SKILL.md\n\n"
            "This is a LIGHTWEIGHT check. Only check watchlist prices against targets.\n"
            "Do NOT do research, analysis, or screening.\n"
            "If a stock is near target, execute the decision gate for that symbol only.\n"
            "If no alerts, exit immediately with minimal output."
        ),
    },
]


async def main():
    client = get_client(
        url=LANGGRAPH_URL,
        api_key=LANGSMITH_API_KEY,
    )

    # Delete existing crons first
    existing = await client.crons.search()
    for c in existing:
        await client.crons.delete(c["cron_id"])
        print(f"Deleted existing cron: {c['cron_id']} (schedule: {c['schedule']})")

    if existing:
        print()

    # Create new crons
    for cron_def in CRONS:
        cron = await client.crons.create(
            assistant_id="autonomous_loop",
            schedule=cron_def["schedule"],
            input={
                "messages": [
                    {
                        "role": "user",
                        "content": cron_def["message"],
                    }
                ]
            },
        )
        print(f"Created: {cron_def['name']}")
        print(f"  Cron ID:  {cron['cron_id']}")
        print(f"  Schedule: {cron['schedule']}")
        print(f"  Next run: {cron.get('next_run_date')}")
        print()

    print(f"Done! {len(CRONS)} cron jobs configured.")


asyncio.run(main())
