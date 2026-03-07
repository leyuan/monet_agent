"""Create Monet Agent's scheduled cron jobs on LangGraph Platform.

Explore/Exploit lifecycle with 17 runs/week:

Weekdays (Mon-Fri) — 3 runs/day = 15/week:
- 10:00 AM ET (14:00 UTC) — Research only (market health, earnings, news scan)
- 1:00 PM ET  (17:00 UTC) — Research + Analysis (deep company dive, set price targets)
- 4:00 PM ET  (20:00 UTC) — Execution + Reflection (check targets, trade if hit, daily reflection)

Weekends — 1 run/day = 2/week:
- Sat 11:00 AM ET (15:00 UTC) — Weekend Research (batch deep dives, sector analysis)
- Sun 11:00 AM ET (15:00 UTC) — Weekly Review (performance, stage management, priorities)

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
        "name": "Morning Scout (10 AM ET, Mon-Fri)",
        "schedule": "0 14 * * 1-5",
        "message": (
            "Run the morning research loop. Execute this phase only:\n\n"
            "1. **Research** — Read /skills/research/SKILL.md and execute the research phase\n\n"
            "This is a scouting run — gather intelligence on market health, "
            "check earnings calendar, scan for developments. "
            "Adjust depth based on your current agent_stage (explore/balanced/exploit). "
            "Do NOT execute trades or analysis."
        ),
    },
    {
        "name": "Midday Deep Dive (1 PM ET, Mon-Fri)",
        "schedule": "0 17 * * 1-5",
        "message": (
            "Run the midday research + analysis loop. Execute these phases:\n\n"
            "1. **Research** — Read /skills/research/SKILL.md and execute the research phase\n"
            "2. **Analysis** — Read /skills/analysis/SKILL.md and analyze candidates from your research\n\n"
            "Focus on deep company analysis (1-2 stocks based on stage). "
            "Set or update price targets on the watchlist for every stock you analyze. "
            "Do NOT execute trades."
        ),
    },
    {
        "name": "End of Day Execution (4 PM ET, Mon-Fri)",
        "schedule": "0 20 * * 1-5",
        "message": (
            "Run the end-of-day execution + reflection loop. Execute these phases:\n\n"
            "1. **Trade Execution** — Read /skills/trade-execution/SKILL.md\n"
            "   - Check watchlist price targets against current prices\n"
            "   - Only trade stocks where current_price <= target_entry\n"
            "   - Manage existing positions first (cut losers, trim winners)\n"
            "   - Respect your stage's minimum confidence threshold\n"
            "2. **Reflection** — Read /skills/reflection/SKILL.md\n"
            "   - Daily reflection on today's activity\n"
            "   - Update stage counters (cycles_completed, watchlist_profiles, total_trades)\n"
            "   - Check stage transition thresholds\n\n"
            "Remember: doing nothing is the default. Only trade if price targets are hit "
            "and you have conviction from today's research and analysis."
        ),
    },
    {
        "name": "Saturday Batch Research (11 AM ET, Sat)",
        "schedule": "0 15 * * 6",
        "message": (
            "Run the Saturday batch research session. Execute these phases:\n\n"
            "1. **Weekend Research** — Read /skills/weekend-research/SKILL.md\n"
            "   - Run sector analysis with longer periods (3mo AND 6mo) for trend identification\n"
            "   - Batch deep-dive 3-5 companies (adjusted by stage)\n"
            "   - Profile each with company_profile, peer_comparison, technical_analysis, fundamental_analysis\n"
            "   - Store all profiles in memory as company_profile_{SYMBOL}\n"
            "   - Review all watchlist price targets vs current prices\n"
            "   - Build sector-level thesis in memory\n"
            "2. **Analysis** — Read /skills/analysis/SKILL.md\n"
            "   - Set/update price targets for all newly profiled stocks\n\n"
            "Take your time — markets are closed. Depth over speed."
        ),
    },
    {
        "name": "Sunday Weekly Review (11 AM ET, Sun)",
        "schedule": "0 15 * * 0",
        "message": (
            "Run the Sunday weekly review. Execute this phase:\n\n"
            "1. **Weekly Review** — Read /skills/weekly-review/SKILL.md\n"
            "   - Full portfolio performance review\n"
            "   - Trade win/loss analysis and confidence calibration\n"
            "   - Strategy assessment: what's working, what's not\n"
            "   - Stage management: update counters, check transition thresholds\n"
            "   - Set 3-5 specific priorities for the coming week\n"
            "   - Write comprehensive weekly reflection journal entry\n\n"
            "This is your most important session of the week. Be thorough and honest."
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

    print(f"Done! {len(CRONS)} cron jobs configured (17 runs/week).")


asyncio.run(main())
