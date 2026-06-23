"""
auth.py 단위 테스트 — 비밀번호 해싱 / JWT 토큰 / 관리자 이메일 판별.
(DB나 네트워크 없이 순수 함수만 검증)
"""

import jwt
import pytest

import auth


# --- 비밀번호 해싱 -----------------------------------------------------------
def test_hash_password_is_not_plaintext():
    """해시 결과는 원문과 달라야 한다(평문 저장 금지)."""
    hashed = auth.hash_password("secret123")
    assert hashed != "secret123"
    assert hashed.startswith("$2")  # bcrypt 해시 형식


def test_hash_password_is_salted():
    """같은 비밀번호라도 매번 다른 해시가 나와야 한다(salt)."""
    assert auth.hash_password("same") != auth.hash_password("same")


def test_verify_password_correct():
    """올바른 비밀번호는 검증을 통과한다."""
    hashed = auth.hash_password("correct-horse")
    assert auth.verify_password("correct-horse", hashed) is True


def test_verify_password_wrong():
    """틀린 비밀번호는 거부된다."""
    hashed = auth.hash_password("correct-horse")
    assert auth.verify_password("wrong", hashed) is False


def test_verify_password_malformed_hash():
    """해시 형식이 깨져 있어도 예외 없이 False를 반환한다."""
    assert auth.verify_password("anything", "not-a-real-hash") is False


# --- JWT 토큰 ---------------------------------------------------------------
def test_create_and_decode_token_roundtrip():
    """발급한 토큰을 디코드하면 같은 user_id가 나와야 한다."""
    token = auth.create_access_token(42)
    assert auth._decode_token(token) == 42


def test_decode_invalid_token_raises_401():
    """망가진 토큰은 401."""
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        auth._decode_token("garbage.token.value")
    assert exc.value.status_code == 401


def test_decode_token_wrong_secret_raises_401():
    """다른 비밀키로 서명된 토큰은 거부된다(위조 방지)."""
    from fastapi import HTTPException

    forged = jwt.encode({"sub": "1"}, "other-secret", algorithm=auth.JWT_ALGORITHM)
    with pytest.raises(HTTPException) as exc:
        auth._decode_token(forged)
    assert exc.value.status_code == 401


def test_decode_expired_token_raises_401():
    """만료된 토큰은 401."""
    from datetime import datetime, timedelta, timezone

    from fastapi import HTTPException

    past = datetime.now(timezone.utc) - timedelta(days=1)
    expired = jwt.encode(
        {"sub": "1", "exp": past}, auth.JWT_SECRET, algorithm=auth.JWT_ALGORITHM
    )
    with pytest.raises(HTTPException) as exc:
        auth._decode_token(expired)
    assert exc.value.status_code == 401


# --- 관리자 이메일 판별 ------------------------------------------------------
def test_is_admin_email_match_case_insensitive():
    """대소문자/공백과 무관하게 관리자 이메일을 인식한다."""
    # conftest에서 ADMIN_EMAILS=boss@example.com 로 설정됨
    assert auth.is_admin_email("boss@example.com") is True
    assert auth.is_admin_email("  BOSS@Example.com  ") is True


def test_is_admin_email_non_admin():
    """관리자 목록에 없으면 False."""
    assert auth.is_admin_email("someone@example.com") is False
