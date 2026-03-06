"""Agent middleware for tool error handling and retry logic."""

import logging

import httpx
import requests.exceptions
from langchain.agents.middleware import ToolRetryMiddleware, wrap_tool_call
from langchain_core.messages import ToolMessage
from tavily.errors import (
    TimeoutError as TavilyTimeoutError,
    UsageLimitExceededError,
)

logger = logging.getLogger(__name__)


def _is_retryable(exc: Exception) -> bool:
    return isinstance(
        exc,
        (
            TavilyTimeoutError,
            UsageLimitExceededError,
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
            httpx.TimeoutException,
            httpx.ConnectError,
        ),
    )


retry_middleware = ToolRetryMiddleware(
    max_retries=2,
    tools=["internet_search", "get_quote", "get_historical_data"],
    retry_on=_is_retryable,
    on_failure="continue",
    backoff_factor=2.0,
    initial_delay=1.0,
)


@wrap_tool_call
async def handle_tool_errors(request, handler):
    try:
        return await handler(request)
    except Exception as exc:
        tool_name = request.tool.name if request.tool else request.tool_call["name"]
        logger.error(
            "Unhandled tool error in %s: %s",
            tool_name,
            exc,
            exc_info=True,
        )
        return ToolMessage(
            content=f"Tool error: {exc}. Please try a different approach.",
            tool_call_id=request.tool_call["id"],
            name=tool_name,
            status="error",
        )
