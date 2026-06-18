"""
인증(Authentication) 유틸리티 — 비밀번호 해싱 + JWT 토큰 + 현재 사용자 판별

흐름 요약:
  회원가입: 비밀번호를 bcrypt로 '해시'해서 저장 (원문은 저장/복원 불가)
  로그인:   입력 비밀번호를 저장된 해시와 대조 → 맞으면 'JWT 토큰' 발급
  이후 요청: 프론트가 Authorization: Bearer <토큰> 헤더로 토큰을 보냄
            → get_current_user 가 토큰을 검증해 '지금 로그인한 사용자'를 찾아준다

왜 이렇게?
  - 비밀번호를 평문으로 두면 DB가 유출됐을 때 그대로 노출된다. 해시는 단방향이라 안전.
  - JWT는 '서명된' 토큰이라, 서버가 매 요청마다 세션을 저장하지 않아도
    토큰만 검증하면 누구인지 알 수 있다(상태 없는 인증).
"""

import os
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from models import User

# --- 설정 -------------------------------------------------------------------
# JWT 서명에 쓰는 비밀키. 이 값이 유출되면 누구나 토큰을 위조할 수 있으므로 .env로 관리.
# (개발 편의를 위한 기본값을 두지만, 실제로는 .env의 JWT_SECRET를 반드시 설정해야 한다)
JWT_SECRET = os.getenv("JWT_SECRET", "dev-secret-change-me")
JWT_ALGORITHM = "HS256"
# 토큰 유효기간(일). 지나면 다시 로그인해야 한다.
JWT_EXPIRE_DAYS = 7

# 관리자로 자동 승격할 이메일 목록(.env의 ADMIN_EMAILS, 쉼표로 구분).
#   예) ADMIN_EMAILS=admin@a.com, boss@b.com
# 여기 적힌 이메일은 가입/로그인 시 자동으로 role=admin + status=approved 가 된다.
ADMIN_EMAILS = {
    e.strip().lower()
    for e in os.getenv("ADMIN_EMAILS", "").split(",")
    if e.strip()
}


def is_admin_email(email: str) -> bool:
    """이 이메일이 .env에 지정된 관리자 이메일인지 여부."""
    return email.strip().lower() in ADMIN_EMAILS


# --- 비밀번호 해싱 -----------------------------------------------------------
def hash_password(plain: str) -> str:
    """평문 비밀번호를 bcrypt 해시 문자열로 변환한다(저장용)."""
    # gensalt()가 매번 다른 salt를 섞어주므로, 같은 비밀번호라도 해시는 매번 다르다.
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """입력한 평문이 저장된 해시와 일치하는지 검사한다(로그인용)."""
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        # 해시 형식이 깨진 경우 등 → 그냥 불일치로 처리
        return False


# --- JWT 토큰 ---------------------------------------------------------------
def create_access_token(user_id: int) -> str:
    """user_id를 담은 JWT 토큰을 발급한다. (sub=주인, exp=만료시각)"""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),  # 토큰의 주인(누구의 토큰인지)
        "exp": now + timedelta(days=JWT_EXPIRE_DAYS),  # 만료 시각
        "iat": now,  # 발급 시각
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def _decode_token(token: str) -> int:
    """토큰을 검증하고 user_id를 돌려준다. 잘못/만료된 토큰이면 401 에러."""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return int(payload["sub"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="로그인이 만료되었습니다. 다시 로그인해 주세요.")
    except (jwt.InvalidTokenError, KeyError, ValueError):
        raise HTTPException(status_code=401, detail="유효하지 않은 인증 정보입니다.")


# --- 현재 사용자 판별 (의존성) ----------------------------------------------
def get_current_user(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    """
    요청 헤더의 'Authorization: Bearer <토큰>'을 읽어 현재 로그인한 사용자를 반환한다.
    엔드포인트에 Depends(get_current_user)로 끼우면, 그 엔드포인트는 '로그인 필수'가 된다.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")

    token = authorization[len("Bearer ") :].strip()
    user_id = _decode_token(token)

    user = db.get(User, user_id)
    if not user:
        # 토큰은 유효하지만 해당 사용자가 사라진 경우(탈퇴 등)
        raise HTTPException(status_code=401, detail="사용자를 찾을 수 없습니다.")
    return user


def get_current_admin(current_user: User = Depends(get_current_user)) -> User:
    """
    현재 사용자가 '관리자'인지까지 확인하는 의존성.
    관리 전용 엔드포인트에 Depends(get_current_admin)으로 끼우면,
    관리자가 아니면 403으로 막힌다(로그인 사용자라도 차단).
    """
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="관리자 권한이 필요합니다.")
    return current_user
