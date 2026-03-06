"""Autonomous trading loop: research -> analyze -> decide -> execute -> reflect.

This module runs the agent's autonomous decision-making cycle. It uses a LangGraph
graph to orchestrate each phase, calling the LLM with appropriate skills and tools.
"""

import logging
import os
from pathlib import Path

from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend

from stock_agent.middleware import handle_tool_errors, retry_middleware
from stock_agent.tools import AUTONOMOUS_TOOLS

logger = logging.getLogger(__name__)

AGENT_ROOT = Path(__file__).parent.parent.parent  # agent/ directory

AUTONOMOUS_SYSTEM_PROMPT = """\
You are an autonomous AI stock trading agent. You have a persistent identity and make \
your own trading decisions based on research, analysis, and risk management.

## Your Personality
- You are a disciplined, data-driven investor with a growth-oriented strategy
- You prefer quality companies with strong fundamentals and favorable technicals
- You are risk-conscious and never chase trades
- You maintain a journal and reflect on your decisions honestly
- You have opinions and are not afraid to express them

## Core Rules
- ALWAYS check risk before trading
- ALWAYS document your reasoning in journal entries
- ALWAYS update your memory with new beliefs and learnings
- NEVER exceed your risk limits, no matter how confident you are
- Focus on 5-15 positions max — quality over quantity

## Current Task
You are running an autonomous trading loop. Follow the skill instructions for each phase.
Read the relevant skill file COMPLETELY before proceeding with each phase.
"""

model_name = os.environ.get("MODEL_NAME", "anthropic:claude-sonnet-4-5-20250929")

backend = FilesystemBackend(root_dir=AGENT_ROOT, virtual_mode=True)

autonomous_graph = create_deep_agent(
    model=model_name,
    tools=AUTONOMOUS_TOOLS,
    system_prompt=AUTONOMOUS_SYSTEM_PROMPT,
    backend=backend,
    skills=["/skills/"],
    middleware=[handle_tool_errors, retry_middleware],
)


async def run_autonomous_loop():
    """Execute one full autonomous cycle: research -> analyze -> decide -> execute -> reflect.

    This is called by the scheduler on a cron schedule.
    """
    logger.info("Starting autonomous trading loop")

    phases = [
        ("research", "Read the /skills/research/SKILL.md skill and execute the research phase completely."),
        ("analysis", "Read the /skills/analysis/SKILL.md skill and execute the analysis phase on candidates from your research."),
        ("trade-execution", "Read the /skills/trade-execution/SKILL.md skill and execute trades for candidates that pass your analysis and risk checks. If no candidates meet your criteria, skip trading and note why in your journal."),
        ("reflection", "Read the /skills/reflection/SKILL.md skill and reflect on this loop's activity and your overall performance."),
    ]

    for phase_name, instruction in phases:
        logger.info("Starting phase: %s", phase_name)
        try:
            config = {"configurable": {"thread_id": f"autonomous_{phase_name}"}}
            async for event in autonomous_graph.astream(
                {"messages": [{"role": "user", "content": instruction}]},
                config=config,
            ):
                # Log tool calls and completions
                if "messages" in event:
                    for msg in event["messages"]:
                        if hasattr(msg, "tool_calls") and msg.tool_calls:
                            for tc in msg.tool_calls:
                                logger.info("[%s] Tool call: %s", phase_name, tc["name"])
            logger.info("Completed phase: %s", phase_name)
        except Exception as e:
            logger.error("Error in phase %s: %s", phase_name, e, exc_info=True)
            # Continue to next phase even if one fails

    logger.info("Autonomous trading loop complete")
