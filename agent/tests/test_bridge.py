"""Tests for the Telegram-bridge endpoints (stock_agent.bridge).

The bridge is an external sidecar that POSTs chat messages to /handle.
These tests cover the API-key gate (401), the happy path (full reply,
done=true), and the session_id -> thread mapping that keys conversation
memory. The chat pipeline itself is stubbed — no LLM or LangGraph server
is needed.
"""

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


def test_handle_happy_path_returns_full_reply(client, monkeypatch):
    calls = []

    async def fake_pipeline(session_id, text):
        calls.append((session_id, text))
        return "AAPL is up 2% today."

    monkeypatch.setattr(bridge, "run_chat_pipeline", fake_pipeline)

    response = client.post(
        "/handle", json=make_body(), headers={"X-API-Key": API_KEY}
    )
    assert response.status_code == 200
    assert response.json() == {"text": "AAPL is up 2% today.", "done": True}
    assert calls == [("tg:-1001234", "hello")]


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
