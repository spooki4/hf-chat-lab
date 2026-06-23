"""
대화(conversation) 엔드포인트 테스트 — 생성/목록/조회/제목변경/삭제 + 소유권 격리.
핵심: 남의 대화는 보거나 건드릴 수 없어야 한다(404로 존재 자체를 숨김).
"""

from conftest import _auth_header
from database import SessionLocal
from models import Conversation, Message


def _make_convo(user_id: int, title: str = "테스트 대화") -> int:
    """DB에 대화를 직접 만들고 id를 돌려준다."""
    s = SessionLocal()
    try:
        c = Conversation(title=title, user_id=user_id)
        s.add(c)
        s.commit()
        s.refresh(c)
        return c.id
    finally:
        s.close()


def _add_message(convo_id: int, role: str, content: str):
    s = SessionLocal()
    try:
        s.add(Message(conversation_id=convo_id, role=role, content=content))
        s.commit()
    finally:
        s.close()


# --- 생성/목록 --------------------------------------------------------------
def test_create_conversation(client, auth_headers):
    r = client.post("/conversations", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["title"] == "새 대화"
    assert "id" in body


def test_list_requires_auth(client):
    assert client.get("/conversations").status_code == 401


def test_list_returns_only_own_conversations(client, user, make_user):
    """목록에는 내 대화만 나온다(남의 대화 제외)."""
    other = make_user("other@example.com")
    _make_convo(user.id, "내 대화")
    _make_convo(other.id, "남의 대화")

    r = client.get("/conversations", headers=_auth_header(user))
    titles = [c["title"] for c in r.json()]
    assert "내 대화" in titles
    assert "남의 대화" not in titles


def test_list_ordered_by_recent_activity(client, user):
    """updated_at 최신순으로 정렬된다."""
    from datetime import datetime, timedelta, timezone

    old = _make_convo(user.id, "오래된")
    new = _make_convo(user.id, "최근")
    s = SessionLocal()
    try:
        base = datetime.now(timezone.utc)
        s.get(Conversation, old).updated_at = base - timedelta(hours=2)
        s.get(Conversation, new).updated_at = base
        s.commit()
    finally:
        s.close()

    r = client.get("/conversations", headers=_auth_header(user))
    titles = [c["title"] for c in r.json()]
    assert titles.index("최근") < titles.index("오래된")


# --- 메시지 조회 ------------------------------------------------------------
def test_get_messages_in_order(client, user):
    convo_id = _make_convo(user.id)
    _add_message(convo_id, "user", "안녕")
    _add_message(convo_id, "bot", "반가워요")

    r = client.get(f"/conversations/{convo_id}/messages", headers=_auth_header(user))
    assert r.status_code == 200
    msgs = r.json()
    assert [m["role"] for m in msgs] == ["user", "bot"]
    assert msgs[0]["content"] == "안녕"


def test_get_messages_of_others_404(client, user, make_user):
    """남의 대화 메시지는 404."""
    other = make_user("other@example.com")
    convo_id = _make_convo(other.id)
    r = client.get(f"/conversations/{convo_id}/messages", headers=_auth_header(user))
    assert r.status_code == 404


def test_get_messages_nonexistent_404(client, auth_headers):
    assert (
        client.get("/conversations/99999/messages", headers=auth_headers).status_code
        == 404
    )


# --- 제목 변경 --------------------------------------------------------------
def test_rename_conversation(client, user):
    convo_id = _make_convo(user.id)
    r = client.patch(
        f"/conversations/{convo_id}",
        headers=_auth_header(user),
        json={"title": "새 제목"},
    )
    assert r.status_code == 200
    assert r.json()["title"] == "새 제목"


def test_rename_empty_title_rejected(client, user):
    convo_id = _make_convo(user.id)
    r = client.patch(
        f"/conversations/{convo_id}", headers=_auth_header(user), json={"title": "   "}
    )
    assert r.status_code == 400


def test_rename_truncates_long_title(client, user):
    """제목은 컬럼 길이(255)를 넘지 않게 잘린다."""
    convo_id = _make_convo(user.id)
    r = client.patch(
        f"/conversations/{convo_id}",
        headers=_auth_header(user),
        json={"title": "가" * 300},
    )
    assert r.status_code == 200
    assert len(r.json()["title"]) == 255


def test_rename_others_conversation_404(client, user, make_user):
    other = make_user("other@example.com")
    convo_id = _make_convo(other.id)
    r = client.patch(
        f"/conversations/{convo_id}", headers=_auth_header(user), json={"title": "탈취"}
    )
    assert r.status_code == 404


# --- 삭제 -------------------------------------------------------------------
def test_delete_conversation_cascades_messages(client, user, db):
    convo_id = _make_convo(user.id)
    _add_message(convo_id, "user", "지워질 메시지")

    r = client.delete(f"/conversations/{convo_id}", headers=_auth_header(user))
    assert r.status_code == 200
    # 대화와 메시지 모두 사라졌는지 확인
    assert db.get(Conversation, convo_id) is None
    assert (
        db.query(Message).filter(Message.conversation_id == convo_id).count() == 0
    )


def test_delete_others_conversation_404(client, user, make_user, db):
    other = make_user("other@example.com")
    convo_id = _make_convo(other.id)
    r = client.delete(f"/conversations/{convo_id}", headers=_auth_header(user))
    assert r.status_code == 404
    # 남의 대화는 그대로 남아 있어야 한다
    assert db.get(Conversation, convo_id) is not None
