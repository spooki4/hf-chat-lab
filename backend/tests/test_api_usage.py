"""
토큰 사용량 조회 엔드포인트 테스트 — /usage/me (내 사용량), /admin/usage (전체).
TokenUsage 행을 직접 심어두고 집계(요약/일별/모델별/사용자별)가 맞는지 검증한다.
"""

from conftest import _auth_header
from database import SessionLocal
from models import TokenUsage


def _seed_usage(user_id, day, model, prompt, completion, total, count=1):
    s = SessionLocal()
    try:
        s.add(
            TokenUsage(
                user_id=user_id,
                day=day,
                model=model,
                prompt_tokens=prompt,
                completion_tokens=completion,
                total_tokens=total,
                request_count=count,
            )
        )
        s.commit()
    finally:
        s.close()


# --- /usage/me ---------------------------------------------------------------
def test_usage_me_requires_auth(client):
    assert client.get("/usage/me").status_code == 401


def test_usage_me_totals_and_breakdown(client, user):
    day = "2026-06-10"
    _seed_usage(user.id, day, "model-a", 10, 5, 15, count=2)
    _seed_usage(user.id, day, "model-b", 20, 10, 30, count=1)

    r = client.get(
        "/usage/me?start=2026-06-01&end=2026-06-30", headers=_auth_header(user)
    )
    assert r.status_code == 200
    body = r.json()
    assert body["totals"]["total_tokens"] == 45
    assert body["totals"]["request_count"] == 3
    # 모델별: 사용량 많은 순(model-b가 위)
    assert body["by_model"][0]["model"] == "model-b"
    # 모델 필터 드롭다운 목록
    assert set(body["models"]) == {"model-a", "model-b"}


def test_usage_me_excludes_other_users(client, user, make_user):
    """내 사용량만 보여야 한다(남의 사용량 제외)."""
    other = make_user("other@example.com")
    day = "2026-06-10"
    _seed_usage(user.id, day, "m", 10, 5, 15)
    _seed_usage(other.id, day, "m", 100, 100, 200)

    r = client.get(
        "/usage/me?start=2026-06-01&end=2026-06-30", headers=_auth_header(user)
    )
    assert r.json()["totals"]["total_tokens"] == 15


def test_usage_me_model_filter(client, user):
    day = "2026-06-10"
    _seed_usage(user.id, day, "model-a", 10, 5, 15)
    _seed_usage(user.id, day, "model-b", 20, 10, 30)

    r = client.get(
        "/usage/me?start=2026-06-01&end=2026-06-30&model=model-a",
        headers=_auth_header(user),
    )
    assert r.json()["totals"]["total_tokens"] == 15


def test_usage_me_date_range_excludes_outside(client, user):
    """조회 기간 밖의 사용량은 합계에서 빠진다."""
    _seed_usage(user.id, "2026-06-10", "m", 10, 5, 15)
    _seed_usage(user.id, "2026-01-01", "m", 99, 99, 198)

    r = client.get(
        "/usage/me?start=2026-06-01&end=2026-06-30", headers=_auth_header(user)
    )
    assert r.json()["totals"]["total_tokens"] == 15


# --- /admin/usage ------------------------------------------------------------
def test_admin_usage_forbidden_for_normal_user(client, auth_headers):
    assert client.get("/admin/usage", headers=auth_headers).status_code == 403


def test_admin_usage_aggregates_all_users(client, admin, user):
    day = "2026-06-10"
    _seed_usage(user.id, day, "m", 10, 5, 15, count=1)
    _seed_usage(admin.id, day, "m", 20, 10, 30, count=1)

    r = client.get(
        "/admin/usage?start=2026-06-01&end=2026-06-30", headers=_auth_header(admin)
    )
    assert r.status_code == 200
    body = r.json()
    assert body["totals"]["total_tokens"] == 45
    # 사용자별 합계(많은 순): admin이 위
    assert body["by_user"][0]["user_id"] == admin.id
    assert body["by_user"][0]["total_tokens"] == 30


def test_admin_usage_user_filter(client, admin, user):
    day = "2026-06-10"
    _seed_usage(user.id, day, "m", 10, 5, 15)
    _seed_usage(admin.id, day, "m", 20, 10, 30)

    r = client.get(
        f"/admin/usage?start=2026-06-01&end=2026-06-30&user_id={user.id}",
        headers=_auth_header(admin),
    )
    assert r.json()["totals"]["total_tokens"] == 15
