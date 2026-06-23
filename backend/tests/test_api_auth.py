"""
인증 관련 엔드포인트 테스트 — 회원가입 / 로그인 / 내 정보 조회·수정.
승인 흐름(가입은 pending, 관리자 승인 후 로그인 가능)을 중점적으로 검증한다.
"""


# --- 회원가입 ----------------------------------------------------------------
def test_register_normal_user_is_pending(client):
    """일반 사용자는 가입 시 승인 대기 상태가 된다(토큰 미발급)."""
    r = client.post(
        "/auth/register",
        json={"email": "new@example.com", "password": "pass1234", "name": "신규"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "pending"


def test_register_admin_email_is_approved(client):
    """ADMIN_EMAILS에 속한 이메일은 가입 즉시 승인된다."""
    r = client.post(
        "/auth/register",
        json={"email": "boss@example.com", "password": "pass1234", "name": "보스"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "approved"


def test_register_duplicate_email_conflicts(client):
    body = {"email": "dup@example.com", "password": "pass1234", "name": "중복"}
    assert client.post("/auth/register", json=body).status_code == 200
    r = client.post("/auth/register", json=body)
    assert r.status_code == 409


def test_register_short_password_rejected(client):
    r = client.post(
        "/auth/register",
        json={"email": "x@example.com", "password": "1", "name": "짧음"},
    )
    assert r.status_code == 400


def test_register_missing_name_rejected(client):
    r = client.post(
        "/auth/register",
        json={"email": "x@example.com", "password": "pass1234", "name": "  "},
    )
    assert r.status_code == 400


def test_register_normalizes_email_lowercase(client, db):
    """이메일은 소문자로 정규화되어 저장된다."""
    from models import User

    client.post(
        "/auth/register",
        json={"email": "MiXeD@Example.com", "password": "pass1234", "name": "케이스"},
    )
    assert db.query(User).filter(User.email == "mixed@example.com").first() is not None


# --- 로그인 ------------------------------------------------------------------
def test_login_success_returns_token_and_role(client, make_user):
    make_user("login@example.com", password="pass1234")
    r = client.post(
        "/auth/login", json={"email": "login@example.com", "password": "pass1234"}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["access_token"]
    assert body["role"] == "user"


def test_login_wrong_password_401(client, make_user):
    make_user("login@example.com", password="pass1234")
    r = client.post(
        "/auth/login", json={"email": "login@example.com", "password": "nope"}
    )
    assert r.status_code == 401


def test_login_unknown_email_401(client):
    r = client.post(
        "/auth/login", json={"email": "ghost@example.com", "password": "pass1234"}
    )
    assert r.status_code == 401


def test_login_pending_user_blocked_403(client, make_user):
    make_user("pending@example.com", status="pending")
    r = client.post(
        "/auth/login", json={"email": "pending@example.com", "password": "pass1234"}
    )
    assert r.status_code == 403


def test_login_rejected_user_blocked_403(client, make_user):
    make_user("rej@example.com", status="rejected")
    r = client.post(
        "/auth/login", json={"email": "rej@example.com", "password": "pass1234"}
    )
    assert r.status_code == 403


def test_register_then_login_full_flow(client, db):
    """가입(대기) → 승인 → 로그인 성공 의 전체 흐름."""
    from models import User

    client.post(
        "/auth/register",
        json={"email": "flow@example.com", "password": "pass1234", "name": "흐름"},
    )
    # 로그인 시도 → 아직 대기라 차단
    assert (
        client.post(
            "/auth/login", json={"email": "flow@example.com", "password": "pass1234"}
        ).status_code
        == 403
    )
    # 관리자가 승인했다고 가정
    u = db.query(User).filter(User.email == "flow@example.com").first()
    u.status = "approved"
    db.commit()
    # 이제 로그인 성공
    assert (
        client.post(
            "/auth/login", json={"email": "flow@example.com", "password": "pass1234"}
        ).status_code
        == 200
    )


# --- 내 정보 (auth/me) -------------------------------------------------------
def test_me_requires_auth(client):
    assert client.get("/auth/me").status_code == 401


def test_me_invalid_token_401(client):
    r = client.get("/auth/me", headers={"Authorization": "Bearer garbage"})
    assert r.status_code == 401


def test_me_returns_current_user(client, auth_headers):
    r = client.get("/auth/me", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["email"] == "user@example.com"


def test_update_me_changes_name_and_phone(client, auth_headers):
    r = client.patch(
        "/auth/me", headers=auth_headers, json={"name": "새이름", "phone": "010-0000"}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "새이름"
    assert body["phone"] == "010-0000"


def test_update_me_password_requires_current(client, auth_headers):
    """새 비밀번호를 바꾸려면 현재 비밀번호 확인이 필요하다."""
    r = client.patch(
        "/auth/me", headers=auth_headers, json={"new_password": "newpass"}
    )
    assert r.status_code == 400


def test_update_me_password_wrong_current(client, auth_headers):
    r = client.patch(
        "/auth/me",
        headers=auth_headers,
        json={"current_password": "wrong", "new_password": "newpass"},
    )
    assert r.status_code == 400


def test_update_me_password_success(client, auth_headers):
    """현재 비밀번호가 맞으면 변경되고, 새 비밀번호로 로그인된다."""
    r = client.patch(
        "/auth/me",
        headers=auth_headers,
        json={"current_password": "pass1234", "new_password": "brandnew"},
    )
    assert r.status_code == 200
    assert (
        client.post(
            "/auth/login", json={"email": "user@example.com", "password": "brandnew"}
        ).status_code
        == 200
    )
