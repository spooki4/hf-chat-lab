"""
관리자 전용 엔드포인트 테스트 — 사용자 목록/권한·상태 변경/삭제.
핵심: 관리자만 접근 가능(일반 사용자 403), 자기 자신은 강등/삭제 불가.
"""

from conftest import _auth_header
from models import User


# --- 접근 제어 --------------------------------------------------------------
def test_admin_users_requires_auth(client):
    assert client.get("/admin/users").status_code == 401


def test_admin_users_forbidden_for_normal_user(client, auth_headers):
    assert client.get("/admin/users", headers=auth_headers).status_code == 403


def test_admin_users_allowed_for_admin(client, admin_headers):
    assert client.get("/admin/users", headers=admin_headers).status_code == 200


# --- 목록 정렬 --------------------------------------------------------------
def test_admin_users_pending_listed_first(client, admin, make_user):
    """승인 대기(pending)가 목록 맨 위에 온다(관리자가 먼저 처리하도록)."""
    make_user("approved@example.com", status="approved")
    make_user("pending@example.com", status="pending")

    r = client.get("/admin/users", headers=_auth_header(admin))
    statuses = [u["status"] for u in r.json()]
    assert statuses[0] == "pending"


# --- 권한/상태 변경 ----------------------------------------------------------
def test_admin_approve_user(client, admin, make_user):
    target = make_user("p@example.com", status="pending")
    r = client.patch(
        f"/admin/users/{target.id}",
        headers=_auth_header(admin),
        json={"status": "approved"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "approved"


def test_admin_promote_user_to_admin(client, admin, make_user):
    target = make_user("u@example.com")
    r = client.patch(
        f"/admin/users/{target.id}",
        headers=_auth_header(admin),
        json={"role": "admin"},
    )
    assert r.status_code == 200
    assert r.json()["role"] == "admin"


def test_admin_cannot_change_self(client, admin):
    """자기 자신의 권한/상태는 바꿀 수 없다(스스로 잠기는 사고 방지)."""
    r = client.patch(
        f"/admin/users/{admin.id}",
        headers=_auth_header(admin),
        json={"role": "user"},
    )
    assert r.status_code == 400


def test_admin_invalid_role_rejected(client, admin, make_user):
    target = make_user("u@example.com")
    r = client.patch(
        f"/admin/users/{target.id}",
        headers=_auth_header(admin),
        json={"role": "superuser"},
    )
    assert r.status_code == 400


def test_admin_invalid_status_rejected(client, admin, make_user):
    target = make_user("u@example.com")
    r = client.patch(
        f"/admin/users/{target.id}",
        headers=_auth_header(admin),
        json={"status": "banned"},
    )
    assert r.status_code == 400


def test_admin_update_nonexistent_user_404(client, admin):
    r = client.patch(
        "/admin/users/99999", headers=_auth_header(admin), json={"status": "approved"}
    )
    assert r.status_code == 404


def test_admin_update_forbidden_for_normal_user(client, auth_headers, make_user):
    target = make_user("victim@example.com")
    r = client.patch(
        f"/admin/users/{target.id}", headers=auth_headers, json={"role": "admin"}
    )
    assert r.status_code == 403


# --- 삭제 -------------------------------------------------------------------
def test_admin_delete_user(client, admin, make_user, db):
    target = make_user("gone@example.com")
    r = client.delete(f"/admin/users/{target.id}", headers=_auth_header(admin))
    assert r.status_code == 200
    assert db.get(User, target.id) is None


def test_admin_cannot_delete_self(client, admin):
    r = client.delete(f"/admin/users/{admin.id}", headers=_auth_header(admin))
    assert r.status_code == 400


def test_admin_delete_nonexistent_404(client, admin):
    assert (
        client.delete("/admin/users/99999", headers=_auth_header(admin)).status_code
        == 404
    )
