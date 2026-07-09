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

import anthropic
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from langgraph_sdk import get_client
from pydantic import BaseModel, ValidationError

ASSISTANT_ID = "monet_agent"
STOCK_HANDLE = "@evo_stock_agent_bot"
JUDGE_MODEL = "claude-opus-4-8"

# Fixed namespace so a given session_id always maps to the same thread UUID.
_THREAD_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "monet-agent/telegram-bridge")

app = FastAPI()


class ChatInfo(BaseModel):
    kind: str = "dm"


class SenderInfo(BaseModel):
    kind: str = "human"


class HandleRequest(BaseModel):
    """The bridge-contract fields the endpoint acts on; extras are ignored.

    The agent has one persistent identity and conversation memory is keyed
    per thread (session_id), not per user account — so sender identity
    needs no account mapping. chat.kind and sender.kind gate which
    group-only context note gets prepended.
    """

    session_id: str
    text: str
    chat: ChatInfo | None = None
    sender: SenderInfo | None = None


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

# Variants used when the incoming message itself came from the other agent:
# the asker only receives the answer if the reply @mentions it. The routing
# directive goes AFTER the message text (models follow trailing directives
# far more reliably than leading preambles), phrased as a format default
# with an explicit opt-out — a conditional "if answering, include..." was
# ignored in live testing by both sonnet-4.5 and gpt-4o.
FROM_AGENT_HEADER = (
    "[Message from stock-agent (@evo_stock_agent_bot) — another AI agent in "
    "this chat (action-capable stock-market simulator), not a human.]\n\n"
)
FROM_AGENT_FOOTER = (
    "\n\n[Reply routing: stock-agent cannot see your reply unless it contains "
    "@evo_stock_agent_bot. You are replying to stock-agent, so your FINAL "
    "message — the last one you write, after any tool use — must begin with "
    "@evo_stock_agent_bot. Omit it ONLY if the exchange is truly complete and "
    "your reply is meant for the humans instead. Never reply with pure "
    "courtesy or acknowledgment.]"
)


def thread_id_for_session(session_id: str) -> str:
    """Map an opaque bridge session_id to a stable LangGraph thread UUID."""
    return str(uuid.uuid5(_THREAD_NAMESPACE, session_id))


def _ai_text(message: dict) -> str | None:
    """Text of an AI message, or None if the message isn't AI-typed."""
    if message.get("type") != "ai":
        return None
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return None


def extract_reply(state: dict) -> str:
    """Pull the final AI reply text from a chat run's output state."""
    for message in reversed((state or {}).get("messages") or []):
        text = _ai_text(message)
        if text is not None:
            return text
    raise RuntimeError("Chat run produced no AI reply")


async def run_chat_pipeline(session_id: str, text: str) -> tuple[str, list[str]]:
    """Run text through the chat graph on the session's persistent thread.

    Returns (final reply, texts of ALL AI messages produced by this run).
    The full list matters: in multi-step tool runs the model may address
    its reply (e.g. "@evo_stock_agent_bot ...") in an intermediate message
    that never gets posted — only the final one does.
    """
    client = get_client()  # in-process connection to this server's API
    thread_id = thread_id_for_session(session_id)
    await client.threads.create(
        thread_id=thread_id,
        if_exists="do_nothing",
        metadata={"origin": "telegram-bridge", "session_id": session_id},
    )
    before = await client.threads.get_state(thread_id)
    prior_count = len(((before or {}).get("values") or {}).get("messages") or [])
    state = await client.runs.wait(
        thread_id,
        ASSISTANT_ID,
        input={"messages": [{"role": "user", "content": text}]},
    )
    run_messages = ((state or {}).get("messages") or [])[prior_count:]
    run_ai_texts = [t for m in run_messages if (t := _ai_text(m)) is not None]
    return extract_reply(state), run_ai_texts


async def judge_should_route(incoming: str, reply: str) -> bool:
    """Content-judge fallback for the reply-routing decision.

    Runs only when the model never emitted the handle anywhere in the run.
    Fails open (route): an extra hop is bounded by the bridge's hop cap,
    while a dropped reply silently ends the conversation.
    """
    try:
        client = anthropic.AsyncAnthropic()
        response = await client.messages.create(
            model=JUDGE_MODEL,
            max_tokens=8,
            messages=[{
                "role": "user",
                "content": (
                    "Two AI agents share a Telegram group chat with humans. "
                    "stock-agent sent monet this message:\n\n"
                    f"{incoming[:2000]}\n\n"
                    f"monet replied:\n\n{reply[:2000]}\n\n"
                    "Decide the routing for monet's reply:\n"
                    "- ROUTE: deliver it back to stock-agent, which will then "
                    "respond again. Choose this if the reply answers a "
                    "question stock-agent is waiting on, asks stock-agent "
                    "something, or moves their exchange forward.\n"
                    "- END: post it to the group only; stock-agent never sees "
                    "it and the bot-to-bot exchange stops. Choose this if the "
                    "exchange has concluded — the reply only acknowledges, "
                    "agrees, thanks, or restates an already-settled outcome "
                    "for the humans.\n"
                    "Reply with exactly one word: ROUTE or END."
                ),
            }],
        )
        verdict = "".join(
            block.text for block in response.content if block.type == "text"
        )
        return not verdict.strip().upper().startswith("END")
    except Exception:
        return True


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

    in_group = payload.chat is not None and payload.chat.kind == "group"
    from_agent = (
        in_group and payload.sender is not None and payload.sender.kind == "agent"
    )
    text = payload.text
    if from_agent:
        text = FROM_AGENT_HEADER + text + FROM_AGENT_FOOTER
    elif in_group:
        text = OTHER_AGENTS_NOTE + text

    reply, run_ai_texts = await run_chat_pipeline(payload.session_id, text)

    # Reply-routing checker: only the final AI message gets posted, so the
    # model's addressing can be lost between its own messages — or never
    # emitted at all. Deterministic fast paths first; the judge runs only
    # when the handle appeared nowhere in the run.
    if from_agent and STOCK_HANDLE not in reply:
        carried = any(STOCK_HANDLE in t for t in run_ai_texts)
        if carried or await judge_should_route(payload.text, reply):
            reply = f"{STOCK_HANDLE}\n\n{reply}"

    return {"text": reply, "done": True}
