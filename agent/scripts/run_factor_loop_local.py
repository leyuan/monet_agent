"""One-off: fire the morning factor loop against the LOCAL dev server.

Mirrors the cron payload (assistant_id='autonomous_loop', morning message).
Used to manually trigger a run since `langgraph dev` does not execute crons.
"""

import asyncio

from langgraph_sdk import get_client

LOCAL_URL = "http://127.0.0.1:2024"

MESSAGE = (
    "Run the factor-based trading loop. Execute this phase:\n\n"
    "1. **Factor Loop** — Read /skills/factor-loop/SKILL.md and execute ALL steps (0-5)\n\n"
    "This is the systematic pipeline: load context → market regime → "
    "score_universe → enrich_eps_revisions → generate_factor_rankings → "
    "earnings guard → execute signals → record.\n\n"
    "When writing journal entries, set run_source='factor_loop'."
)


async def main():
    client = get_client(url=LOCAL_URL)
    thread = await client.threads.create()
    print(f"Thread: {thread['thread_id']}", flush=True)

    final = await client.runs.wait(
        thread["thread_id"],
        "autonomous_loop",
        input={"messages": [{"role": "user", "content": MESSAGE}]},
    )

    msgs = final.get("messages", []) if isinstance(final, dict) else []
    print(f"\n=== Run complete. {len(msgs)} messages ===", flush=True)
    # Print the last AI message content
    for m in reversed(msgs):
        if m.get("type") == "ai" or m.get("role") == "assistant":
            content = m.get("content")
            if isinstance(content, list):
                content = " ".join(
                    p.get("text", "") for p in content if isinstance(p, dict)
                )
            print("\n--- FINAL AI MESSAGE ---")
            print(content)
            break


asyncio.run(main())
