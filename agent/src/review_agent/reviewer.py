"""Reviewer Agent — graph definition (minimal stub; tools/prompt added later)."""
import os
from pathlib import Path

from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend

from stock_agent.middleware import handle_tool_errors, retry_middleware
from stock_agent.tools.memory import query_database

# review_agent/ — skills/ is co-located here, so skills=["/skills/"] resolves to
# review_agent/skills/. NOTE: unlike stock_agent (root_dir=agent/), the reviewer roots
# the backend at its OWN package dir to keep its skills separate from the trader's.
PACKAGE_ROOT = Path(__file__).parent

REVIEW_SYSTEM_PROMPT = "You are an independent reviewer agent. (stub — see Task 7)"

model_name = os.environ.get("MODEL_NAME", "anthropic:claude-sonnet-4-5-20250929")
backend = FilesystemBackend(root_dir=PACKAGE_ROOT, virtual_mode=True)

review_graph = create_deep_agent(
    model=model_name,
    tools=[query_database],
    system_prompt=REVIEW_SYSTEM_PROMPT,
    backend=backend,
    skills=["/skills/"],
    middleware=[handle_tool_errors, retry_middleware],
)
