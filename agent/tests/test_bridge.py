"""Tests for the Telegram-bridge endpoints (stock_agent.bridge).

The bridge is an external sidecar that POSTs chat messages to /handle.
These tests cover the API-key gate (401), the happy path (full reply,
done=true), the session_id -> thread mapping that keys conversation
memory, and the reply-routing checker for bot-to-bot exchanges. The chat
pipeline and the routing judge are stubbed — no LLM or LangGraph server
is needed.
"""

import asyncio
import uuid

import pytest
from fastapi.testclient import TestClient

from stock_agent import bridge

API_KEY = "test-bridge-key"


def make_body(**overrides):
    body = {
        "session_id": "tg:-1001234",
        "message_id": "tg:842",
        "sender": {"id": "tg:5551234", "name": "Bo", "kind": "human"},
        "chat": {"kind": "dm", "title": None},
        "text": "hello",
        "mentioned_as": None,
        "reply_to": None,
        "stream": False,
    }
    body.update(overrides)
    return body


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("BRIDGE_API_KEY", API_KEY)
    return TestClient(bridge.app)


def test_health_returns_ok_without_auth(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_handle_rejects_missing_api_key(client):
    response = client.post("/handle", json=make_body())
    assert response.status_code == 401


def test_handle_rejects_wrong_api_key(client):
    response = client.post(
        "/handle", json=make_body(), headers={"X-API-Key": "wrong-key"}
    )
    assert response.status_code == 401


def test_handle_rejects_empty_body_without_key(client):
    # Auth is checked before body validation: '{}' with no key is 401, not 422.
    response = client.post("/handle", json={})
    assert response.status_code == 401


def test_handle_rejects_when_key_not_configured(monkeypatch):
    monkeypatch.delenv("BRIDGE_API_KEY", raising=False)
    client = TestClient(bridge.app)
    response = client.post(
        "/handle", json=make_body(), headers={"X-API-Key": API_KEY}
    )
    assert response.status_code == 401


AGENT_SENDER = {"id": "tg:8942443150", "name": "stock-agent", "kind": "agent"}


def agent_body(**overrides):
    return make_body(
        chat={"kind": "group", "title": "trading floor"},
        sender=AGENT_SENDER,
        **overrides,
    )


def stub_pipeline(monkeypatch, reply, run_texts=(), calls=None):
    async def fake_pipeline(session_id, text):
        if calls is not None:
            calls.append(text)
        return reply, list(run_texts)

    monkeypatch.setattr(bridge, "run_chat_pipeline", fake_pipeline)


def forbid_judge(monkeypatch):
    async def no_judge(incoming, reply):
        raise AssertionError("judge must not be called on a deterministic path")

    monkeypatch.setattr(bridge, "judge_should_route", no_judge)


def test_handle_happy_path_returns_full_reply(client, monkeypatch):
    calls = []

    async def fake_pipeline(session_id, text):
        calls.append((session_id, text))
        return "AAPL is up 2% today.", []

    monkeypatch.setattr(bridge, "run_chat_pipeline", fake_pipeline)

    response = client.post(
        "/handle", json=make_body(), headers={"X-API-Key": API_KEY}
    )
    assert response.status_code == 200
    assert response.json() == {"text": "AAPL is up 2% today.", "done": True}
    assert calls == [("tg:-1001234", "hello")]


def test_handle_group_chat_prepends_other_agents_note(client, monkeypatch):
    calls = []
    stub_pipeline(monkeypatch, "noted", calls=calls)

    body = make_body(chat={"kind": "group", "title": "trading floor"})
    response = client.post("/handle", json=body, headers={"X-API-Key": API_KEY})
    assert response.status_code == 200
    assert len(calls) == 1
    assert "@evo_stock_agent_bot" in calls[0]
    assert calls[0].endswith("hello")  # raw text preserved after the note


def test_handle_group_message_from_agent_gets_answering_note(client, monkeypatch):
    calls = []
    stub_pipeline(monkeypatch, "@evo_stock_agent_bot noted", calls=calls)
    forbid_judge(monkeypatch)

    response = client.post("/handle", json=agent_body(), headers={"X-API-Key": API_KEY})
    assert response.status_code == 200
    assert len(calls) == 1
    wrapped = calls[0]
    assert "from stock-agent" in wrapped
    assert "hello" in wrapped
    # Routing directive must come AFTER the message text — models follow
    # trailing directives far more reliably than leading preambles.
    assert wrapped.index("hello") < wrapped.rindex("@evo_stock_agent_bot")


def test_handle_group_message_from_human_keeps_initiate_note(client, monkeypatch):
    calls = []
    stub_pipeline(monkeypatch, "noted", calls=calls)

    body = make_body(chat={"kind": "group", "title": "trading floor"})
    response = client.post("/handle", json=body, headers={"X-API-Key": API_KEY})
    assert response.status_code == 200
    assert "from stock-agent" not in calls[0]
    assert "@evo_stock_agent_bot" in calls[0]


def test_handle_without_chat_field_passes_text_through(client, monkeypatch):
    calls = []
    stub_pipeline(monkeypatch, "noted", calls=calls)

    body = make_body()
    del body["chat"]
    response = client.post("/handle", json=body, headers={"X-API-Key": API_KEY})
    assert response.status_code == 200
    assert calls == ["hello"]


# ── Reply-routing checker (bot-to-bot @-back) ───────────────────────────────


def test_agent_reply_already_mentioning_passes_through(client, monkeypatch):
    stub_pipeline(monkeypatch, "@evo_stock_agent_bot here you go")
    forbid_judge(monkeypatch)

    response = client.post("/handle", json=agent_body(), headers={"X-API-Key": API_KEY})
    assert response.json()["text"] == "@evo_stock_agent_bot here you go"


def test_agent_reply_carries_forward_mention_lost_in_extraction(client, monkeypatch):
    stub_pipeline(
        monkeypatch,
        "Final assessment.",
        run_texts=["@evo_stock_agent_bot NVDA quant check: pulling data..."],
    )
    forbid_judge(monkeypatch)

    response = client.post("/handle", json=agent_body(), headers={"X-API-Key": API_KEY})
    text = response.json()["text"]
    assert text.startswith("@evo_stock_agent_bot")
    assert "Final assessment." in text


def test_agent_reply_without_any_mention_judge_says_route(client, monkeypatch):
    stub_pipeline(monkeypatch, "Final assessment.", run_texts=["let me check"])
    judged = []

    async def fake_judge(incoming, reply):
        judged.append((incoming, reply))
        return True

    monkeypatch.setattr(bridge, "judge_should_route", fake_judge)

    response = client.post("/handle", json=agent_body(), headers={"X-API-Key": API_KEY})
    assert response.json()["text"].startswith("@evo_stock_agent_bot")
    # Judge sees the raw incoming text (not the wrapped version) and the reply
    assert judged == [("hello", "Final assessment.")]


def test_agent_reply_without_any_mention_judge_says_end(client, monkeypatch):
    stub_pipeline(monkeypatch, "All wrapped up, nothing further.")

    async def fake_judge(incoming, reply):
        return False

    monkeypatch.setattr(bridge, "judge_should_route", fake_judge)

    response = client.post("/handle", json=agent_body(), headers={"X-API-Key": API_KEY})
    assert response.json()["text"] == "All wrapped up, nothing further."


def test_human_sender_reply_is_never_modified(client, monkeypatch):
    stub_pipeline(monkeypatch, "no handle here")
    forbid_judge(monkeypatch)

    body = make_body(chat={"kind": "group", "title": "trading floor"})
    response = client.post("/handle", json=body, headers={"X-API-Key": API_KEY})
    assert response.json()["text"] == "no handle here"


def test_judge_error_defaults_to_route(monkeypatch):
    class BrokenAnthropicModule:
        def AsyncAnthropic(self):
            raise RuntimeError("no api available")

    monkeypatch.setattr(bridge, "anthropic", BrokenAnthropicModule())
    assert asyncio.run(bridge.judge_should_route("question", "answer")) is True


def test_handle_rejects_body_missing_text(client):
    body = make_body()
    del body["text"]
    response = client.post("/handle", json=body, headers={"X-API-Key": API_KEY})
    assert response.status_code == 422


def test_thread_id_for_session_is_deterministic():
    first = bridge.thread_id_for_session("tg:-1001234")
    second = bridge.thread_id_for_session("tg:-1001234")
    other = bridge.thread_id_for_session("tg:999")
    assert first == second
    assert first != other
    uuid.UUID(first)  # valid UUID, usable as a LangGraph thread_id


def test_extract_reply_string_content():
    state = {"messages": [{"type": "ai", "content": "hi there"}]}
    assert bridge.extract_reply(state) == "hi there"


def test_extract_reply_content_blocks():
    state = {
        "messages": [
            {
                "type": "ai",
                "content": [
                    {"type": "text", "text": "part one. "},
                    {"type": "text", "text": "part two."},
                ],
            }
        ]
    }
    assert bridge.extract_reply(state) == "part one. part two."


def test_extract_reply_picks_last_ai_message():
    state = {
        "messages": [
            {"type": "human", "content": "question"},
            {"type": "ai", "content": "thinking + tool call"},
            {"type": "tool", "content": "tool result"},
            {"type": "ai", "content": "final answer"},
        ]
    }
    assert bridge.extract_reply(state) == "final answer"
