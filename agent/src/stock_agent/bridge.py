"""Telegram-bridge HTTP endpoints.

An external Telegram sidecar POSTs chat messages to /handle. Each message
runs through the existing chat graph (`monet_agent`) via the in-process
LangGraph API. The bridge's opaque session_id maps deterministically to a
LangGraph thread UUID, so the same session always continues the same
conversation.

Registered as a custom app in langgraph.json (`http.app`) — served
alongside the LangGraph API routes without modifying them or their auth.
Auth here is a shared secret: the X-API-Key header must equal the
BRIDGE_API_KEY env var. Nothing in this module logs the key or message
contents.
"""

import hmac
import os
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from langgraph_sdk import get_client
from pydantic import BaseModel, ValidationError

ASSISTANT_ID = "monet_agent"

# Fixed namespace so a given session_id always maps to the same thread UUID.
_THREAD_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "monet-agent/telegram-bridge")

app = FastAPI()


class ChatInfo(BaseModel):
    kind: str = "dm"


class HandleRequest(BaseModel):
    """The bridge-contract fields the endpoint acts on; extras are ignored.

    The agent has one persistent identity and conversation memory is keyed
    per thread (session_id), not per user account — so sender metadata
    needs no account mapping and is accepted but unused. chat.kind gates
    the group-only OTHER_AGENTS_NOTE.
    """

    session_id: str
    text: str
    chat: ChatInfo | None = None


# Prepended to group-chat messages only — in a DM the mention would go
# nowhere. The other bot only receives messages that @mention it, so
# omitting the mention is what ends a bot-to-bot exchange.
OTHER_AGENTS_NOTE = (
    "[Group-chat context: another AI agent is in this chat — stock-agent "
    "(@evo_stock_agent_bot), an action-capable stock-market-simulator agent "
    "(portfolio, live market data, trade execution). Mention "
    "@evo_stock_agent_bot in your reply when a market/portfolio/execution "
    "question needs it — it only sees messages that mention it. When nothing "
    "more is needed from it, do NOT mention it: a reply without the mention "
    "ends the bot-to-bot exchange.]\n\n"
)


def thread_id_for_session(session_id: str) -> str:
    """Map an opaque bridge session_id to a stable LangGraph thread UUID."""
    return str(uuid.uuid5(_THREAD_NAMESPACE, session_id))


def extract_reply(state: dict) -> str:
    """Pull the final AI reply text from a chat run's output state."""
    for message in reversed((state or {}).get("messages") or []):
        if message.get("type") != "ai":
            continue
        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "".join(
                block.get("text", "")
                for block in content
                if isinstance(block, dict) and block.get("type") == "text"
            )
    raise RuntimeError("Chat run produced no AI reply")


async def run_chat_pipeline(session_id: str, text: str) -> str:
    """Run text through the chat graph on the session's persistent thread."""
    client = get_client()  # in-process connection to this server's API
    thread_id = thread_id_for_session(session_id)
    await client.threads.create(
        thread_id=thread_id,
        if_exists="do_nothing",
        metadata={"origin": "telegram-bridge", "session_id": session_id},
    )
    state = await client.runs.wait(
        thread_id,
        ASSISTANT_ID,
        input={"messages": [{"role": "user", "content": text}]},
    )
    return extract_reply(state)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/handle")
async def handle(request: Request):
    # Auth before body parsing: an unauthenticated request is always 401,
    # never 422. Compare in constant time; fail closed if the key is unset.
    expected = os.environ.get("BRIDGE_API_KEY", "")
    provided = request.headers.get("X-API-Key", "")
    if not expected or not hmac.compare_digest(provided, expected):
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)

    try:
        payload = HandleRequest.model_validate(await request.json())
    except ValidationError as exc:
        detail = [
            {"loc": err.get("loc"), "msg": err.get("msg"), "type": err.get("type")}
            for err in exc.errors(include_input=False)
        ]
        return JSONResponse({"detail": detail}, status_code=422)
    except ValueError:
        return JSONResponse({"detail": "Request body is not valid JSON"}, status_code=422)

    text = payload.text
    if payload.chat is not None and payload.chat.kind == "group":
        text = OTHER_AGENTS_NOTE + text
    reply = await run_chat_pipeline(payload.session_id, text)
    return {"text": reply, "done": True}
