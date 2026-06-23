"""
채팅 엔드포인트 테스트 — /chat, /chat/stream, /chat/stream/regenerate.
실제 HuggingFace는 부르지 않고 목으로 대체한다.
  - /chat: call_hf / resolve_model 을 목으로 → 메시지 저장·응답·토큰 적재 검증
  - 스트리밍: stream_chat_and_save 를 가짜 제너레이터로 → 사전 로직(소유권/재생성)만 검증
"""

import pytest

import main
from conftest import _auth_header
from database import SessionLocal
from models import Conversation, Message, TokenUsage


@pytest.fixture
def mock_hf(monkeypatch):
    """call_hf / resolve_model 을 목으로 교체. usage를 바꿔가며 쓸 수 있게 dict로 노출."""
    state = {"reply": "안녕하세요!", "usage": None, "model": "test/model"}

    async def fake_call_hf(messages, model, **kwargs):
        return state["reply"], state["usage"]

    async def fake_resolve_model(requested):
        return state["model"]

    monkeypatch.setattr(main, "call_hf", fake_call_hf)
    monkeypatch.setattr(main, "resolve_model", fake_resolve_model)
    return state


# --- /chat (비스트리밍) ------------------------------------------------------
def test_chat_requires_auth(client):
    assert client.post("/chat", json={"message": "안녕"}).status_code == 401


def test_chat_creates_conversation_and_saves_messages(client, auth_headers, mock_hf):
    r = client.post("/chat", headers=auth_headers, json={"message": "안녕"})
    assert r.status_code == 200
    body = r.json()
    assert body["reply"] == "안녕하세요!"
    convo_id = body["conversation_id"]

    # 대화에 사용자 메시지 + 봇 응답이 저장됐는지
    msgs = client.get(
        f"/conversations/{convo_id}/messages", headers=auth_headers
    ).json()
    assert [m["role"] for m in msgs] == ["user", "bot"]
    assert msgs[1]["content"] == "안녕하세요!"
    assert msgs[1]["model"] == "test/model"  # 어떤 모델이 답했는지 기록


def test_chat_continues_existing_conversation(client, user, mock_hf):
    headers = _auth_header(user)
    first = client.post("/chat", headers=headers, json={"message": "첫 질문"}).json()
    convo_id = first["conversation_id"]

    client.post(
        "/chat",
        headers=headers,
        json={"message": "두 번째 질문", "conversation_id": convo_id},
    )
    msgs = client.get(f"/conversations/{convo_id}/messages", headers=headers).json()
    # user, bot, user, bot
    assert len(msgs) == 4


def test_chat_on_others_conversation_404(client, user, make_user, mock_hf):
    other = make_user("other@example.com")
    s = SessionLocal()
    try:
        c = Conversation(title="남의 대화", user_id=other.id)
        s.add(c)
        s.commit()
        convo_id = c.id
    finally:
        s.close()

    r = client.post(
        "/chat",
        headers=_auth_header(user),
        json={"message": "침입", "conversation_id": convo_id},
    )
    assert r.status_code == 404


def test_chat_records_token_usage_from_api(client, user, mock_hf, db):
    """API usage가 오면 그 값으로 토큰 사용량이 적재된다."""
    mock_hf["usage"] = {
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "total_tokens": 15,
    }
    client.post("/chat", headers=_auth_header(user), json={"message": "안녕"})

    row = db.query(TokenUsage).filter(TokenUsage.user_id == user.id).first()
    assert row is not None
    assert row.total_tokens == 15
    assert row.request_count == 1
    assert row.model == "test/model"


def test_chat_records_token_usage_estimated(client, user, mock_hf, db):
    """API usage가 없으면 추정치로 적재된다(0보다 큼)."""
    mock_hf["usage"] = None
    client.post("/chat", headers=_auth_header(user), json={"message": "안녕하세요 반갑습니다"})

    row = db.query(TokenUsage).filter(TokenUsage.user_id == user.id).first()
    assert row is not None
    assert row.total_tokens > 0


def test_chat_accumulates_usage_same_day_model(client, user, mock_hf, db):
    """같은 (사용자, 날짜, 모델)이면 한 행에 누적된다."""
    mock_hf["usage"] = {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}
    headers = _auth_header(user)
    client.post("/chat", headers=headers, json={"message": "1"})
    client.post("/chat", headers=headers, json={"message": "2"})

    rows = db.query(TokenUsage).filter(TokenUsage.user_id == user.id).all()
    assert len(rows) == 1
    assert rows[0].request_count == 2
    assert rows[0].total_tokens == 4


# --- 스트리밍: 사전 로직만 검증 (실제 스트림 본문은 가짜로 대체) -------------
@pytest.fixture
def mock_stream(monkeypatch):
    """stream_chat_and_save 를 '아무 것도 저장 않고 닫기만 하는' 가짜로 교체."""
    async def fake_stream(db, convo_id, history, model, user_id):
        db.close()
        yield "ok"

    async def fake_resolve_model(requested):
        return "test/model"

    monkeypatch.setattr(main, "stream_chat_and_save", fake_stream)
    monkeypatch.setattr(main, "resolve_model", fake_resolve_model)


def test_chat_stream_returns_conversation_id_header(client, auth_headers, mock_stream):
    r = client.post("/chat/stream", headers=auth_headers, json={"message": "안녕"})
    assert r.status_code == 200
    assert "X-Conversation-Id" in r.headers
    # 사용자 메시지는 스트리밍 시작 전에 저장된다
    convo_id = int(r.headers["X-Conversation-Id"])
    msgs = client.get(
        f"/conversations/{convo_id}/messages", headers=auth_headers
    ).json()
    assert msgs[0]["role"] == "user"


def test_chat_stream_others_conversation_404(client, user, make_user, mock_stream):
    other = make_user("other@example.com")
    s = SessionLocal()
    try:
        c = Conversation(title="남의 대화", user_id=other.id)
        s.add(c)
        s.commit()
        convo_id = c.id
    finally:
        s.close()

    r = client.post(
        "/chat/stream",
        headers=_auth_header(user),
        json={"message": "침입", "conversation_id": convo_id},
    )
    assert r.status_code == 404


# --- 재생성 ------------------------------------------------------------------
def _convo_with(user_id, messages):
    """(role, content) 목록으로 대화를 만들고 id 반환."""
    s = SessionLocal()
    try:
        c = Conversation(title="재생성 테스트", user_id=user_id)
        s.add(c)
        s.flush()
        for role, content in messages:
            s.add(Message(conversation_id=c.id, role=role, content=content))
        s.commit()
        return c.id
    finally:
        s.close()


def test_regenerate_deletes_last_bot_message(client, user, mock_stream, db):
    """재생성은 마지막 봇 답변을 지운 뒤(질문만 남기고) 다시 스트리밍한다."""
    convo_id = _convo_with(user.id, [("user", "질문"), ("bot", "예전 답변")])
    r = client.post(
        "/chat/stream/regenerate",
        headers=_auth_header(user),
        json={"conversation_id": convo_id},
    )
    assert r.status_code == 200
    # 가짜 스트림은 새 답변을 저장하지 않으므로, 봇 메시지가 사라지고 질문만 남는다
    msgs = db.query(Message).filter(Message.conversation_id == convo_id).all()
    assert [m.role for m in msgs] == ["user"]


def test_regenerate_without_user_message_400(client, user, mock_stream):
    """사용자 메시지가 없으면 재생성할 수 없다."""
    convo_id = _convo_with(user.id, [])
    r = client.post(
        "/chat/stream/regenerate",
        headers=_auth_header(user),
        json={"conversation_id": convo_id},
    )
    assert r.status_code == 400


def test_regenerate_others_conversation_404(client, user, make_user, mock_stream):
    other = make_user("other@example.com")
    convo_id = _convo_with(other.id, [("user", "질문"), ("bot", "답변")])
    r = client.post(
        "/chat/stream/regenerate",
        headers=_auth_header(user),
        json={"conversation_id": convo_id},
    )
    assert r.status_code == 404
