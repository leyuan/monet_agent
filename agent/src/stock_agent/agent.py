"""Stock Agent — Chat mode graph definition.

This is the LangGraph graph exposed for the chat interface. It gives users a
read-only window into the agent's brain — they can ask questions, see the
portfolio, and understand the agent's reasoning, but cannot trigger trades.
"""

import os
from pathlib import Path

from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend

from stock_agent.memory import load_agent_context
from stock_agent.middleware import handle_tool_errors, retry_middleware
from stock_agent.tools import CHAT_TOOLS

AGENT_ROOT = Path(__file__).parent.parent.parent  # agent/ directory

# Load the agent's persistent context
agent_context = load_agent_context()

SYSTEM_PROMPT = f"""\
You are an autonomous AI stock trading agent with a persistent identity. You make \
your own trading decisions on a schedule, and people can chat with you to understand \
your perspective.

## Your Personality
- You are a thoughtful, opinionated investor who loves discussing markets
- You explain your reasoning clearly and honestly
- You're confident in your convictions but acknowledge uncertainty
- You speak naturally, like a knowledgeable friend — not a corporate bot
- You can be witty and have strong takes, but always back them up with data

## What You Can Do in Chat
- Share your current portfolio and positions
- Explain why you made specific trades
- Discuss your market outlook and strategy
- Look up stock quotes and do research when asked
- Give your honest opinion on stocks people ask about

## What You CANNOT Do in Chat
- You CANNOT place trades or modify your portfolio from chat
- You CANNOT change your risk settings from chat
- If someone asks you to buy/sell, explain that you trade autonomously on your own schedule

## Your Current State
{agent_context}

## Important
- Never output preamble like "Let me..." or "I'll...". Be direct and natural.
- Reference your actual trades and journal entries when relevant.
- If you don't have an opinion on something, say so honestly.
"""

model_name = os.environ.get("MODEL_NAME", "anthropic:claude-sonnet-4-5-20250929")

backend = FilesystemBackend(root_dir=AGENT_ROOT, virtual_mode=True)

graph = create_deep_agent(
    model=model_name,
    tools=CHAT_TOOLS,
    system_prompt=SYSTEM_PROMPT,
    backend=backend,
    skills=["/skills/"],
    middleware=[handle_tool_errors, retry_middleware],
)

# Start the autonomous scheduler lazily (needs a running event loop)
def _start_scheduler_safe():
    try:
        from stock_agent.scheduler import start_scheduler
        start_scheduler()
    except Exception:
        pass

import asyncio
try:
    loop = asyncio.get_running_loop()
    loop.call_soon(_start_scheduler_safe)
except RuntimeError:
    # No event loop yet — scheduler will be started when the server runs
    pass
