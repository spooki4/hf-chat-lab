"""
pytest 공용 설정 + 픽스처.

핵심 아이디어:
  - 진짜 MySQL/HuggingFace에 붙지 않는다. DB는 임시 SQLite 파일, HF 호출은 목(mock).
  - 그러려면 app(main.py)을 import 하기 '전에' 환경변수를 먼저 세팅해야 한다.
    (database.py / auth.py 가 import 시점에 환경변수를 읽기 때문)
  - 그래서 이 파일 맨 위에서 os.environ 을 먼저 채운 뒤 main 을 import 한다.
"""

import os
import tempfile

# --- 1) app import 전에 환경 구성 --------------------------------------------
# 임시 SQLite 파일을 테스트 DB로 사용 (실제 MySQL과 분리).
_db_fd, _db_path = tempfile.mkstemp(suffix=".db", prefix="hfchat_test_")
os.close(_db_fd)
os.environ["DATABASE_URL"] = f"sqlite:///{_db_path}"
# 토큰 서명 키 고정(테스트 재현성).
os.environ["JWT_SECRET"] = "test-secret"
# 관리자 자동 승격 이메일(아래 admin 픽스처에서 사용).
os.environ["ADMIN_EMAILS"] = "boss@example.com"
# HF 토큰이 있어야 require_token()이 통과한다(실제 호출은 목으로 막는다).
os.environ["HF_TOKEN"] = "hf_test_token"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import auth  # noqa: E402
import main  # noqa: E402
from database import Base, SessionLocal, engine  # noqa: E402
from models import User  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    """
    매 테스트마다 깨끗한 DB로 시작한다(테스트 간 격리).
    모든 테이블을 지웠다가 다시 만든다.
    """
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db():
    """테스트에서 DB를 직접 조작하고 싶을 때 쓰는 세션."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client():
    """엔드포인트를 호출하는 테스트 클라이언트."""
    with TestClient(main.app) as c:
        yield c


# --- 사용자/인증 헬퍼 --------------------------------------------------------
def _create_user(
    email: str,
    password: str = "pass1234",
    name: str = "테스터",
    role: str = "user",
    status: str = "approved",
) -> User:
    """DB에 사용자를 바로 만든다(가입 흐름을 거치지 않고 원하는 상태로)."""
    session = SessionLocal()
    try:
        user = User(
            email=email,
            password_hash=auth.hash_password(password),
            name=name,
            role=role,
            status=status,
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        return user
    finally:
        session.close()


def _auth_header(user: User) -> dict:
    """해당 사용자로 로그인한 것과 동일한 Authorization 헤더를 만든다."""
    token = auth.create_access_token(user.id)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def make_user():
    """테스트에서 임의의 사용자를 만드는 팩토리."""
    return _create_user


@pytest.fixture
def user(make_user):
    """승인된 일반 사용자 1명."""
    return make_user("user@example.com")


@pytest.fixture
def auth_headers(user):
    """일반 사용자의 인증 헤더."""
    return _auth_header(user)


@pytest.fixture
def admin(make_user):
    """승인된 관리자 1명."""
    return make_user("boss@example.com", role="admin")


@pytest.fixture
def admin_headers(admin):
    """관리자의 인증 헤더."""
    return _auth_header(admin)
