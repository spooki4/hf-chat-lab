"""
보안 가드 테스트 — 입력 검증/크기 제한, JWT 비밀키 시작 가드, 보안 응답 헤더.
"""

import pytest

import auth
import main


# --- JWT 비밀키 시작 가드 ----------------------------------------------------
def test_jwt_guard_blocks_default_secret_in_production():
    """운영 환경에서 기본 비밀키면 실행을 거부한다."""
    with pytest.raises(RuntimeError):
        auth.check_jwt_secret(auth._DEFAULT_JWT_SECRET, "production")


def test_jwt_guard_blocks_empty_secret_in_production():
    with pytest.raises(RuntimeError):
        auth.check_jwt_secret("", "production")


def test_jwt_guard_allows_strong_secret_in_production():
    """운영이라도 제대로 된 비밀키면 통과."""
    auth.check_jwt_secret("a-very-long-random-secret", "production")  # 예외 없음


def test_jwt_guard_warns_but_allows_default_in_dev(caplog):
    """개발 환경에서는 기본키여도 막지 않고 경고만 남긴다."""
    auth.check_jwt_secret(auth._DEFAULT_JWT_SECRET, "development")  # 예외 없음


# --- 보안 응답 헤더 ----------------------------------------------------------
def test_security_headers_present(client):
    r = client.get("/")
    assert r.headers.get("X-Content-Type-Options") == "nosniff"
    assert r.headers.get("X-Frame-Options") == "DENY"
    assert r.headers.get("Referrer-Policy") == "no-referrer"
    assert "Permissions-Policy" in r.headers


# --- 입력 검증/크기 제한 -----------------------------------------------------
def test_chat_empty_message_rejected(client, auth_headers):
    """빈 메시지는 422로 거부된다."""
    r = client.post("/chat", headers=auth_headers, json={"message": ""})
    assert r.status_code == 422


def test_chat_oversized_message_rejected(client, auth_headers):
    """상한(MAX_MESSAGE_CHARS)을 넘는 메시지는 422."""
    big = "가" * (main.MAX_MESSAGE_CHARS + 1)
    r = client.post("/chat", headers=auth_headers, json={"message": big})
    assert r.status_code == 422


def test_register_invalid_email_rejected(client):
    r = client.post(
        "/auth/register",
        json={"email": "not-an-email", "password": "pass1234", "name": "이름"},
    )
    assert r.status_code == 422


def test_register_oversized_name_rejected(client):
    r = client.post(
        "/auth/register",
        json={
            "email": "ok@example.com",
            "password": "pass1234",
            "name": "가" * (main.MAX_NAME_CHARS + 1),
        },
    )
    assert r.status_code == 422


def test_register_oversized_password_rejected(client):
    r = client.post(
        "/auth/register",
        json={
            "email": "ok@example.com",
            "password": "a" * (main.MAX_PASSWORD_CHARS + 1),
            "name": "이름",
        },
    )
    assert r.status_code == 422


def test_register_valid_email_still_works(client):
    """정상 이메일은 그대로 통과(가드가 정상 입력을 막지 않음)."""
    r = client.post(
        "/auth/register",
        json={"email": "fine@example.com", "password": "pass1234", "name": "정상"},
    )
    assert r.status_code == 200


def test_title_update_oversized_rejected(client, user):
    """제목 길이 상한 초과는 422(그 이하는 저장 시 255로 잘림)."""
    from conftest import _auth_header
    from database import SessionLocal
    from models import Conversation

    s = SessionLocal()
    try:
        c = Conversation(title="t", user_id=user.id)
        s.add(c)
        s.commit()
        cid = c.id
    finally:
        s.close()

    r = client.patch(
        f"/conversations/{cid}",
        headers=_auth_header(user),
        json={"title": "가" * (main.MAX_TITLE_CHARS + 1)},
    )
    assert r.status_code == 422
