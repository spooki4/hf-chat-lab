"""
FastAPI 백엔드 - HuggingFace 챗봇 (대화 기록 저장 + 멀티턴)

핵심 흐름:
  프론트엔드 → POST /chat (대화ID + 메시지)
            → DB에 사용자 메시지 저장
            → 그 대화의 "이전 메시지 전체"를 모델에 함께 전달(=멀티턴/맥락 기억)
            → 모델 응답을 DB에 저장
            → 응답 반환

엔드포인트:
  GET  /                              헬스 체크
  POST /auth/register                 회원가입 → 토큰 발급
  POST /auth/login                    로그인 → 토큰 발급
  GET  /auth/me                       현재 로그인한 사용자 정보
  GET  /models                        선택 가능한 모델 목록 (드롭다운용)
  GET  /conversations                 대화 목록 (사이드바용, 로그인 사용자 것만)
  POST /conversations                 새 대화 생성
  GET  /conversations/{id}/messages   특정 대화의 메시지 전체
  DELETE /conversations/{id}          대화 삭제
  POST /chat                          메시지 전송 → 모델 응답 (한 번에)
  POST /chat/stream                   메시지 전송 → 응답을 토큰 단위로 스트리밍
  POST /chat/stream/regenerate        마지막 봇 답변을 버리고 같은 질문으로 다시 스트리밍
"""

import json
import os
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from auth import (
    create_access_token,
    get_current_admin,
    get_current_user,
    hash_password,
    is_admin_email,
    verify_password,
)
from database import SessionLocal, get_db, run_migrations
from models import Conversation, Message, TokenUsage, User

# 토큰 사용량을 '하루 단위'로 묶을 때 기준이 되는 시간대(한국).
KST = ZoneInfo("Asia/Seoul")


def now_utc() -> datetime:
    """현재 UTC 시각(대화 최근 활동 시각 갱신용)."""
    return datetime.now(timezone.utc)

load_dotenv()

# --- 환경변수 ----------------------------------------------------------------
HF_TOKEN = os.getenv("HF_TOKEN")
# HF_MODEL: (선택) 처음에 기본 선택될 모델을 고정하고 싶을 때만 설정.
#           없으면 아래 FALLBACK_MODEL → 라이브 목록 첫 모델 순으로 자동 결정된다.
HF_MODEL = os.getenv("HF_MODEL")  # 미설정이면 None
HF_API_URL = "https://router.huggingface.co/v1/chat/completions"

# 최후의 보루: HF_MODEL도 없고 목록 조회도 실패했을 때 시도할 모델
FALLBACK_MODEL = "meta-llama/Llama-3.1-8B-Instruct"

# 채팅 생성 파라미터.
#   temperature: 낮을수록 일관적/안정적. (기본값 1.0은 작은 모델에서 응답이 무너지기 쉬움)
CHAT_TEMPERATURE = 0.7
CHAT_MAX_TOKENS = 512

# 모델에 함께 보낼 '최근 메시지' 개수 상한 (토큰 절약용).
#   대화가 길어질수록 전체 히스토리를 매번 보내면 토큰(=비용/사용량 한도)이 빠르게 늘어난다.
#   그래서 system 프롬프트는 항상 유지하되, 그 외 메시지는 '최근 N개'만 모델에 전달한다.
#   트레이드오프: 값이 작을수록 토큰은 아끼지만 오래된 맥락을 잊는다(멀티턴 기억이 짧아짐).
#   주의: DB에는 항상 전체가 저장된다. 잘리는 것은 '모델에 보내는 입력'뿐이라 화면/기록엔 영향 없음.
#   0 이하로 두면 제한 없이 전체를 전달한다(기존 동작).
HISTORY_WINDOW = 10

# 모델에게 주는 기본 지시(성격/규칙)
SYSTEM_PROMPT = "You are a helpful assistant. 한국어로 친절하게 답하세요."

# HF의 모델 가용성은 수시로 바뀐다(provider가 빠지거나 모델 버전이 교체됨).
# 그래서 드롭다운 목록을 하드코딩하지 않고, 라우터의 '실시간 목록'에서 가져온다.
HF_MODELS_URL = "https://router.huggingface.co/v1/models"

# 기본으로 선택할 모델 후보(살아있으면 우선 사용). 없으면 목록 첫 모델로 폴백.
PREFERRED_DEFAULTS = [FALLBACK_MODEL]

# 매 요청마다 HF에 묻지 않도록 메모리에 잠깐 캐싱(10분).
_MODELS_TTL = 600  # 초
_models_cache: dict = {"data": None, "ts": 0.0}


async def fetch_available_models() -> list[dict]:
    """
    라우터에서 '지금 사용 가능한' 텍스트 채팅 모델 목록을 가져온다.
    필터 기준: 입력에 text 포함 + 출력이 text + provider 중 하나라도 status=live
    결과는 캐싱하여 잦은 호출을 피한다.
    """
    now = time.monotonic()
    if _models_cache["data"] is not None and now - _models_cache["ts"] < _MODELS_TTL:
        return _models_cache["data"]

    require_token()
    headers = {"Authorization": f"Bearer {HF_TOKEN}"}
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(HF_MODELS_URL, headers=headers)
        resp.raise_for_status()

    models = []
    for m in resp.json().get("data", []):
        arch = m.get("architecture") or {}
        ins = arch.get("input_modalities") or []
        outs = arch.get("output_modalities") or []
        live = any(p.get("status") == "live" for p in (m.get("providers") or []))
        # 텍스트→텍스트 채팅 모델이고 살아있는 provider가 있는 것만
        if "text" in ins and outs == ["text"] and live:
            models.append({"id": m["id"], "label": m["id"]})

    models.sort(key=lambda x: x["id"].lower())
    _models_cache["data"] = models
    _models_cache["ts"] = now
    return models


async def safe_fetch_models() -> list[dict]:
    """fetch_available_models를 호출하되, 실패하면 빈 목록을 돌려준다(서비스 중단 방지)."""
    try:
        return await fetch_available_models()
    except Exception:
        return []


def pick_default(models: list[dict]) -> str:
    """살아있는 목록에서 기본 모델을 고른다."""
    ids = {m["id"] for m in models}
    if HF_MODEL and HF_MODEL in ids:  # .env로 지정한 모델이 살아있으면 우선
        return HF_MODEL
    for d in PREFERRED_DEFAULTS:  # 선호 후보
        if d in ids:
            return d
    return models[0]["id"] if models else FALLBACK_MODEL  # 그 외엔 첫 모델


async def resolve_model(requested: str | None) -> str:
    """요청한 모델이 '현재 사용 가능'하면 그대로, 아니면 살아있는 기본 모델로 폴백."""
    models = await safe_fetch_models()
    ids = {m["id"] for m in models}
    if requested and requested in ids:
        return requested
    if models:
        return pick_default(models)
    # 목록 자체를 못 가져온 경우: 요청값 → .env 기본값 → 최후 보루 순으로 시도
    return requested or HF_MODEL or FALLBACK_MODEL

# --- 앱 초기화 ---------------------------------------------------------------
app = FastAPI(title="hf-chat-lab backend")

# 앱이 처음 뜰 때, 모델 정의(models.py)에 맞춰 테이블/컬럼을 정리한다.
# (없는 테이블 생성 + 기존 테이블에 빠진 컬럼 추가. DB 자체는 미리 만들어져 있어야 함)
run_migrations()


def sync_admin_accounts():
    """
    .env의 ADMIN_EMAILS에 적힌 이메일을 가진 기존 사용자를
    관리자(admin) + 승인(approved) 상태로 맞춘다.
    (이미 가입돼 있던 본인 계정을 관리자로 만들기 위한 부트스트랩)
    """
    db = SessionLocal()
    try:
        changed = False
        for user in db.query(User).all():
            if is_admin_email(user.email) and (
                user.role != "admin" or user.status != "approved"
            ):
                user.role = "admin"
                user.status = "approved"
                changed = True
        if changed:
            db.commit()
    finally:
        db.close()


sync_admin_accounts()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
    # 스트리밍 응답에서 대화 ID를 헤더로 내려주므로, 브라우저 JS가 읽을 수 있게 노출
    expose_headers=["X-Conversation-Id"],
)


# --- 요청/응답 스키마 ---------------------------------------------------------
class ChatRequest(BaseModel):
    message: str
    # 이어서 대화할 대화방 ID. 없으면(None) 새 대화를 시작한다.
    conversation_id: int | None = None
    # 사용할 모델. 없으면 기본 모델(HF_MODEL) 사용.
    model: str | None = None


class ChatResponse(BaseModel):
    reply: str
    conversation_id: int  # 프론트가 이후 메시지를 같은 대화로 보낼 수 있게 돌려준다


class RegenerateRequest(BaseModel):
    # 어느 대화의 마지막 답변을 다시 만들지
    conversation_id: int
    # 재생성에 사용할 모델. 없으면 기본 모델 사용.
    model: str | None = None


class MessageOut(BaseModel):
    id: int
    role: str
    content: str
    # 메시지 작성 시각(UTC). 프론트가 사용자 로컬 시간으로 변환해 표기.
    created_at: datetime
    # 봇 응답을 만든 모델(사용자 메시지는 null)
    model: str | None = None

    # SQLAlchemy 모델 객체를 그대로 응답으로 변환할 수 있게 해주는 설정
    model_config = {"from_attributes": True}


class ConversationOut(BaseModel):
    id: int
    title: str
    # 최근 활동 시각(UTC). 사이드바 정렬/시각 표기에 사용.
    updated_at: datetime

    model_config = {"from_attributes": True}


class TitleUpdate(BaseModel):
    title: str  # 사용자가 직접 입력한 새 제목


# 회원가입/로그인 요청 본문
class RegisterRequest(BaseModel):
    email: str
    password: str
    name: str
    phone: str | None = None


class LoginRequest(BaseModel):
    email: str
    password: str


# 회원가입 결과(승인 대기 안내). 가입 직후에는 토큰을 주지 않는다.
class RegisterResponse(BaseModel):
    status: str  # "pending" | "approved"
    message: str


# 로그인 성공 시 돌려주는 토큰 + 사용자 정보
class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    email: str
    role: str  # 프론트가 관리자 메뉴 노출 여부를 판단하는 데 사용


class UserOut(BaseModel):
    id: int
    email: str
    name: str
    phone: str | None = None
    role: str
    status: str

    model_config = {"from_attributes": True}


# 관리자 화면에서 보여줄 사용자 정보(가입일 포함)
class AdminUserOut(BaseModel):
    id: int
    email: str
    name: str
    phone: str | None = None
    role: str
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


# 관리자가 사용자 권한/상태를 바꿀 때의 요청 본문(둘 다 선택)
class AdminUserUpdate(BaseModel):
    role: str | None = None  # "admin" | "user"
    status: str | None = None  # "pending" | "approved" | "rejected"


# 마이페이지: 내 정보 변경 요청 본문. 보낸 항목만 변경한다(부분 수정).
class ProfileUpdate(BaseModel):
    name: str | None = None
    phone: str | None = None
    # 비밀번호 변경 시에만 사용(현재 비밀번호 확인 후 새 비밀번호로 교체)
    current_password: str | None = None
    new_password: str | None = None


# --- 공용 헬퍼 ---------------------------------------------------------------
def build_history(convo: Conversation) -> list[dict]:
    """
    대화의 모든 메시지를 OpenAI 호환 형식으로 변환한다.
    우리 DB의 role "bot" → API의 "assistant" 로 매핑.
    (이 목록을 통째로 모델에 보내는 것이 '멀티턴/맥락 기억'의 핵심)
    """
    history = [{"role": "system", "content": SYSTEM_PROMPT}]

    msgs = list(convo.messages)
    # 토큰 절약: system 프롬프트는 항상 두고, 나머지는 '최근 HISTORY_WINDOW개'만 사용.
    # (HISTORY_WINDOW가 0 이하면 자르지 않고 전체를 보낸다)
    if HISTORY_WINDOW > 0:
        msgs = msgs[-HISTORY_WINDOW:]

    for m in msgs:
        role = "assistant" if m.role == "bot" else "user"
        history.append({"role": role, "content": m.content})
    return history


def get_owned_conversation(db: Session, convo_id: int, user: User) -> Conversation:
    """
    convo_id 대화를 가져오되 '현재 사용자 소유'인지 확인한다.
    남의 대화면 존재 자체를 숨기기 위해 404로 응답한다(403 대신).
    """
    convo = db.get(Conversation, convo_id)
    if not convo or convo.user_id != user.id:
        raise HTTPException(status_code=404, detail="대화를 찾을 수 없습니다.")
    return convo


def require_token():
    """HF 토큰이 없으면 친절한 에러를 던진다."""
    if not HF_TOKEN:
        raise HTTPException(
            status_code=500,
            detail="HF_TOKEN이 설정되지 않았습니다. backend/.env 파일을 확인하세요.",
        )


def friendly_hf_error(status: int, body: str, model: str) -> str:
    """HF 에러 응답을 사용자 친화적인 한국어 메시지로 변환."""
    code = ""
    try:
        code = (json.loads(body).get("error") or {}).get("code", "")
    except (json.JSONDecodeError, AttributeError):
        pass

    # 가장 흔한 케이스: provider가 일시적으로 빠졌을 때
    if code == "model_not_supported" or "not supported by any provider" in body:
        return (
            f"⚠️ '{model}' 모델을 지금 제공하는 provider가 없습니다. "
            "일시적인 경우가 많으니 잠시 후 다시 시도하거나, 위 드롭다운에서 다른 모델을 선택해 보세요."
        )
    if status in (401, 403):
        return "⚠️ 인증 오류입니다. backend/.env 의 HF_TOKEN을 확인해 주세요."
    if status == 429:
        return "⚠️ 사용량 한도(rate limit)에 도달했습니다. 잠시 후 다시 시도해 주세요."
    return f"⚠️ HuggingFace 오류({status}): {body[:200]}"


# --- 토큰 사용량 적재 --------------------------------------------------------
def today_kst() -> str:
    """오늘 날짜를 한국 시간 기준 'YYYY-MM-DD' 문자열로."""
    return datetime.now(KST).strftime("%Y-%m-%d")


def estimate_tokens(text: str) -> int:
    """
    provider가 usage(실제 토큰 수)를 안 줄 때 쓰는 '대략적인' 추정치.
    영어는 ~4자/토큰, 한국어는 더 촘촘하므로 중간값으로 3자/토큰으로 잡는다.
    (어디까지나 폴백용 근사치 — 정확한 값은 API가 주는 usage를 우선 사용한다)
    """
    if not text:
        return 0
    return max(1, len(text) // 3)


def estimate_messages_tokens(messages: list[dict]) -> int:
    """여러 메시지(입력 프롬프트)의 토큰 수 추정 합계."""
    return sum(estimate_tokens(m.get("content", "")) for m in messages)


def record_token_usage(
    db: Session, user_id: int, model: str, prompt: int, completion: int, total: int
) -> None:
    """
    (사용자, 오늘(KST), 모델) 그룹의 토큰 사용량을 누적한다.
    해당 그룹 행이 없으면 새로 만들고, 있으면 더한다(upsert 누적).
    """
    day = today_kst()
    row = (
        db.query(TokenUsage)
        .filter_by(user_id=user_id, day=day, model=model)
        .first()
    )
    if row is None:
        row = TokenUsage(user_id=user_id, day=day, model=model)
        db.add(row)
    row.prompt_tokens = (row.prompt_tokens or 0) + prompt
    row.completion_tokens = (row.completion_tokens or 0) + completion
    row.total_tokens = (row.total_tokens or 0) + total
    row.request_count = (row.request_count or 0) + 1
    db.commit()


def usage_from_api_or_estimate(
    usage: dict | None, prompt_messages: list[dict], reply_text: str
) -> tuple[int, int, int]:
    """API usage가 있으면 그대로, 없으면 추정치로 (prompt, completion, total)을 구한다."""
    if usage:
        p = int(usage.get("prompt_tokens") or 0)
        c = int(usage.get("completion_tokens") or 0)
        t = int(usage.get("total_tokens") or (p + c))
        return p, c, t
    p = estimate_messages_tokens(prompt_messages)
    c = estimate_tokens(reply_text)
    return p, c, p + c


# --- 토큰 사용량 조회(집계) --------------------------------------------------
def _parse_date(value: str | None):
    """'YYYY-MM-DD' 문자열을 date로. 형식이 틀리거나 없으면 None."""
    if not value:
        return None
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def normalize_range(start: str | None, end: str | None) -> tuple[str, str]:
    """
    조회 기간을 'YYYY-MM-DD' 문자열 (시작, 끝)으로 정규화한다.
    값이 없으면 끝=오늘(KST), 시작=끝-29일(최근 30일). 시작>끝이면 서로 바꾼다.
    """
    today = datetime.now(KST).date()
    e = _parse_date(end) or today
    s = _parse_date(start) or (e - timedelta(days=29))
    if s > e:
        s, e = e, s
    return s.isoformat(), e.isoformat()


def _usage_filter(query, s: str, e: str, model: str | None, user_id: int | None):
    """공통 필터: 기간 + (선택)모델 + (선택)사용자."""
    query = query.filter(TokenUsage.day >= s, TokenUsage.day <= e)
    if model:
        query = query.filter(TokenUsage.model == model)
    if user_id:
        query = query.filter(TokenUsage.user_id == user_id)
    return query


def _sum(col):
    """합계가 NULL(행 없음)이면 0이 되도록."""
    return func.coalesce(func.sum(col), 0)


def usage_daily(db, s, e, model=None, user_id=None) -> list[dict]:
    """일별 합계 추이 (그래프용)."""
    q = db.query(
        TokenUsage.day,
        _sum(TokenUsage.prompt_tokens),
        _sum(TokenUsage.completion_tokens),
        _sum(TokenUsage.total_tokens),
        _sum(TokenUsage.request_count),
    )
    rows = _usage_filter(q, s, e, model, user_id).group_by(TokenUsage.day).order_by(
        TokenUsage.day
    ).all()
    return [
        {
            "day": d,
            "prompt_tokens": int(p),
            "completion_tokens": int(c),
            "total_tokens": int(t),
            "request_count": int(r),
        }
        for d, p, c, t, r in rows
    ]


def usage_by_model(db, s, e, model=None, user_id=None) -> list[dict]:
    """모델별 합계 (사용량 많은 순)."""
    q = db.query(
        TokenUsage.model,
        _sum(TokenUsage.total_tokens),
        _sum(TokenUsage.request_count),
    )
    rows = _usage_filter(q, s, e, model, user_id).group_by(TokenUsage.model).order_by(
        _sum(TokenUsage.total_tokens).desc()
    ).all()
    return [
        {"model": m, "total_tokens": int(t), "request_count": int(r)} for m, t, r in rows
    ]


def usage_totals(db, s, e, model=None, user_id=None) -> dict:
    """기간 전체 합계."""
    q = db.query(
        _sum(TokenUsage.prompt_tokens),
        _sum(TokenUsage.completion_tokens),
        _sum(TokenUsage.total_tokens),
        _sum(TokenUsage.request_count),
    )
    p, c, t, r = _usage_filter(q, s, e, model, user_id).one()
    return {
        "prompt_tokens": int(p),
        "completion_tokens": int(c),
        "total_tokens": int(t),
        "request_count": int(r),
    }


# --- HuggingFace 호출 함수 ----------------------------------------------------
async def call_hf(
    messages: list[dict], model: str, max_tokens: int = 512, temperature: float | None = None
) -> tuple[str, dict | None]:
    """
    messages를 HF에 보내고 (완성된 응답 텍스트, usage)를 돌려준다. (비스트리밍)
    usage는 provider가 주면 {prompt_tokens, completion_tokens, total_tokens}, 없으면 None.
    temperature: 낮을수록 결정적(제목 생성처럼 일관성이 중요할 때 0에 가깝게).
    """
    require_token()

    payload = {"model": model, "messages": messages, "max_tokens": max_tokens}
    if temperature is not None:
        payload["temperature"] = temperature
    headers = {"Authorization": f"Bearer {HF_TOKEN}"}

    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            resp = await client.post(HF_API_URL, headers=headers, json=payload)
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise HTTPException(
                status_code=e.response.status_code,
                detail=f"HuggingFace API 오류: {e.response.text}",
            )
        except httpx.RequestError as e:
            raise HTTPException(status_code=502, detail=f"HuggingFace 연결 실패: {e}")

    data = resp.json()
    try:
        content = data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError):
        raise HTTPException(status_code=500, detail=f"예상치 못한 응답 형식: {data}")
    return content, data.get("usage")


async def stream_chat_and_save(
    db: Session, convo_id: int, history: list[dict], model: str, user_id: int
):
    """
    HF에 스트리밍 요청을 보내 토큰(delta)을 그대로 흘려보내고,
    스트림이 끝나면 모은 전체 응답을 DB에 'bot' 메시지로 저장 + 토큰 사용량을 적재한 뒤
    세션을 닫는다.

    /chat/stream(새 응답)과 /chat/stream/regenerate(응답 재생성)가 공유하는 공통 로직.
    호출 측에서 대화방 확보·사용자 메시지 저장을 끝낸 뒤, 이 제너레이터를
    StreamingResponse에 넘겨주면 된다. (db 세션의 소유권도 이 함수가 넘겨받아 닫는다)
    """
    collected = []  # 전체 응답을 모아 마지막에 DB 저장용
    usage = None  # provider가 마지막 청크로 주는 실제 토큰 사용량(있으면)
    payload = {
        "model": model,
        "messages": history,
        "max_tokens": CHAT_MAX_TOKENS,
        "temperature": CHAT_TEMPERATURE,  # 응답 안정성 향상
        "stream": True,  # ← HF에 스트리밍 요청
        # 마지막에 usage(토큰 수)를 담은 청크를 추가로 보내달라고 요청(OpenAI 호환 옵션).
        "stream_options": {"include_usage": True},
    }
    headers = {"Authorization": f"Bearer {HF_TOKEN}"}
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream("POST", HF_API_URL, headers=headers, json=payload) as resp:
                if resp.status_code != 200:
                    body = (await resp.aread()).decode(errors="ignore")
                    yield friendly_hf_error(resp.status_code, body, model)
                    return
                # HF는 SSE(Server-Sent Events) 형식으로 'data: {json}' 줄을 보낸다.
                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[len("data:") :].strip()
                    if data == "[DONE]":
                        break
                    try:
                        obj = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    # usage 청크는 choices가 비어 있을 수 있으므로 delta보다 먼저 확인.
                    if obj.get("usage"):
                        usage = obj["usage"]
                    try:
                        delta = obj["choices"][0]["delta"].get("content")
                    except (KeyError, IndexError):
                        continue
                    if delta:
                        collected.append(delta)
                        yield delta  # ← 받는 즉시 프론트로 전달
    except httpx.RequestError as e:
        yield f"⚠️ 연결 실패: {e}"
    finally:
        # 스트림 종료 후 전체 응답을 DB에 저장하고, 토큰 사용량을 적재한 뒤 세션 정리
        full = "".join(collected).strip()
        if full:
            db.add(Message(conversation_id=convo_id, role="bot", content=full, model=model))
            # 대화의 최근 활동 시각 갱신(사이드바를 최근순으로 정렬하기 위해)
            convo = db.get(Conversation, convo_id)
            if convo:
                convo.updated_at = now_utc()
            db.commit()
            # 토큰 사용량 적재 (실패해도 채팅 자체는 영향받지 않도록 보호)
            try:
                p, c, t = usage_from_api_or_estimate(usage, history, full)
                record_token_usage(db, user_id, model, p, c, t)
            except Exception:
                pass
        db.close()


async def generate_title(first_user_message: str, model: str) -> str:
    """
    첫 사용자 메시지로 짧은 대화 제목을 생성한다.
    (제목 생성은 채팅과 별개의 작은 LLM 호출 — max_tokens를 작게)
    """
    prompt = [
        {
            "role": "system",
            "content": (
                "사용자 메시지를 대표하는 짧은 제목을 한국어로 만들어라.\n"
                "규칙: 한 줄, 최대 6단어, 명사구로. 따옴표·마침표·설명 없이 제목만 출력.\n"
                "예) 입력: '파이썬으로 엑셀 읽는 법' → 출력: 파이썬 엑셀 파일 읽기"
            ),
        },
        {"role": "user", "content": first_user_message},
    ]
    raw, _ = await call_hf(prompt, model, max_tokens=24, temperature=0.0)
    # 첫 줄만 취하고 따옴표/공백 제거
    title = raw.strip().strip("\"'").splitlines()[0].strip().strip("\"'").strip()

    # 모델이 제목 대신 '문장'으로 답한 경우(예: "~다음과 같습니다.") 감지 → 폴백
    looks_like_sentence = title.endswith(".") or any(
        s in title for s in ("습니다", "입니다", "세요", "할까요")
    )
    if not title or looks_like_sentence:
        title = first_user_message.strip()

    return title[:40] or "새 대화"


# --- 엔드포인트 --------------------------------------------------------------
@app.get("/")
def health_check():
    return {"status": "ok", "default_model": HF_MODEL or "(auto)"}


@app.get("/models")
async def list_models():
    """드롭다운에 채울 '현재 사용 가능한' 모델 목록과 기본값을 반환."""
    models = await safe_fetch_models()
    return {"models": models, "default": pick_default(models)}


@app.post("/auth/register", response_model=RegisterResponse)
def register(body: RegisterRequest, db: Session = Depends(get_db)):
    """
    회원가입: 사용자를 만들되 기본적으로 '승인 대기(pending)' 상태로 둔다.
    가입했다고 바로 로그인되는 게 아니라, 관리자가 승인해야 로그인할 수 있다.
    (단, .env의 ADMIN_EMAILS에 해당하는 이메일은 자동으로 관리자+승인 처리)
    """
    email = body.email.strip().lower()
    name = body.name.strip()
    phone = (body.phone or "").strip() or None

    if not email or not body.password:
        raise HTTPException(status_code=400, detail="이메일과 비밀번호를 입력하세요.")
    if not name:
        raise HTTPException(status_code=400, detail="이름을 입력하세요.")
    if len(body.password) < 4:
        raise HTTPException(status_code=400, detail="비밀번호는 4자 이상이어야 합니다.")

    # 이미 가입된 이메일인지 확인 (users.email 은 unique)
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(status_code=409, detail="이미 가입된 이메일입니다.")

    # 관리자 이메일이면 자동 승격, 아니면 일반+대기
    admin = is_admin_email(email)
    user = User(
        email=email,
        password_hash=hash_password(body.password),
        name=name,
        phone=phone,
        role="admin" if admin else "user",
        status="approved" if admin else "pending",
    )
    db.add(user)
    db.commit()
    db.refresh(user)  # DB가 채워준 id 확보

    if user.status == "approved":
        return RegisterResponse(status="approved", message="가입이 완료되었습니다. 로그인해 주세요.")
    return RegisterResponse(
        status="pending",
        message="가입 신청이 접수되었습니다. 관리자 승인 후 로그인할 수 있습니다.",
    )


@app.post("/auth/login", response_model=TokenResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)):
    """로그인: 이메일/비밀번호가 맞고 '승인된' 사용자에게만 토큰을 발급한다."""
    email = body.email.strip().lower()
    user = db.query(User).filter(User.email == email).first()
    # 사용자 없음/비밀번호 불일치 모두 같은 메시지로 응답(어느 쪽이 틀렸는지 흘리지 않음)
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="이메일 또는 비밀번호가 올바르지 않습니다.")

    # 승인 상태 확인: 대기/거부 계정은 로그인 차단
    if user.status == "pending":
        raise HTTPException(status_code=403, detail="아직 승인 대기 중입니다. 관리자 승인 후 이용해 주세요.")
    if user.status == "rejected":
        raise HTTPException(status_code=403, detail="가입이 거부된 계정입니다. 관리자에게 문의해 주세요.")

    token = create_access_token(user.id)
    return TokenResponse(access_token=token, email=user.email, role=user.role)


@app.get("/auth/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user)):
    """현재 로그인한 사용자 정보 반환 (프론트가 토큰 유효성 확인 + 사용자 표시에 사용)."""
    return current_user


@app.patch("/auth/me", response_model=UserOut)
def update_me(
    body: ProfileUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    마이페이지: 내 정보(이름/연락처/비밀번호)를 변경한다.
    보낸 항목만 바꾼다. 비밀번호는 '현재 비밀번호' 확인을 통과해야 변경된다.
    """
    if body.name is not None:
        name = body.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="이름을 입력하세요.")
        current_user.name = name

    if body.phone is not None:
        current_user.phone = body.phone.strip() or None

    # 비밀번호 변경(요청에 new_password가 있을 때만)
    if body.new_password:
        if not body.current_password:
            raise HTTPException(status_code=400, detail="현재 비밀번호를 입력하세요.")
        if not verify_password(body.current_password, current_user.password_hash):
            raise HTTPException(status_code=400, detail="현재 비밀번호가 올바르지 않습니다.")
        if len(body.new_password) < 4:
            raise HTTPException(status_code=400, detail="새 비밀번호는 4자 이상이어야 합니다.")
        current_user.password_hash = hash_password(body.new_password)

    db.commit()
    db.refresh(current_user)
    return current_user


# --- 관리자 전용 엔드포인트 --------------------------------------------------
# 모두 Depends(get_current_admin)으로 보호된다 → 관리자만 호출 가능.

# 상태 정렬 우선순위: 승인 대기를 맨 위로 올려 관리자가 먼저 처리하게 한다.
_STATUS_ORDER = {"pending": 0, "approved": 1, "rejected": 2}


@app.get("/admin/users", response_model=list[AdminUserOut])
def admin_list_users(
    _admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """전체 사용자 목록. 승인 대기 → 승인 → 거부 순, 같은 상태면 최신 가입순."""
    users = db.query(User).all()
    users.sort(key=lambda u: (_STATUS_ORDER.get(u.status, 9), -u.id))
    return users


@app.patch("/admin/users/{user_id}", response_model=AdminUserOut)
def admin_update_user(
    user_id: int,
    body: AdminUserUpdate,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """사용자의 권한(role) 또는 승인 상태(status)를 변경한다(승인/거부/권한부여)."""
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")
    # 실수로 자기 자신을 강등/차단해 스스로 잠기는 것을 방지
    if user.id == admin.id:
        raise HTTPException(status_code=400, detail="자기 자신의 권한/상태는 변경할 수 없습니다.")

    if body.role is not None:
        if body.role not in ("admin", "user"):
            raise HTTPException(status_code=400, detail="권한 값이 올바르지 않습니다.")
        user.role = body.role
    if body.status is not None:
        if body.status not in ("pending", "approved", "rejected"):
            raise HTTPException(status_code=400, detail="상태 값이 올바르지 않습니다.")
        user.status = body.status

    db.commit()
    db.refresh(user)
    return user


@app.delete("/admin/users/{user_id}")
def admin_delete_user(
    user_id: int,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """사용자를 삭제한다(소유한 대화/메시지도 함께 삭제됨)."""
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="자기 자신은 삭제할 수 없습니다.")
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")
    db.delete(user)
    db.commit()
    return {"ok": True}


# --- 토큰 사용량 조회 엔드포인트 ---------------------------------------------
@app.get("/usage/me")
def usage_me(
    start: str | None = None,
    end: str | None = None,
    model: str | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """마이페이지: 내 토큰 사용량(기간/모델 필터). 요약 + 일별 추이 + 모델별 분포."""
    s, e = normalize_range(start, end)
    uid = current_user.id
    # 모델 필터 드롭다운용: 내가 (기간과 무관하게) 사용한 적 있는 모델 전체
    models = [
        m[0]
        for m in db.query(TokenUsage.model)
        .filter(TokenUsage.user_id == uid)
        .distinct()
        .order_by(TokenUsage.model)
        .all()
    ]
    return {
        "start": s,
        "end": e,
        "totals": usage_totals(db, s, e, model, uid),
        "daily": usage_daily(db, s, e, model, uid),
        "by_model": usage_by_model(db, s, e, model, uid),
        "models": models,
    }


@app.get("/admin/usage")
def admin_usage(
    start: str | None = None,
    end: str | None = None,
    model: str | None = None,
    user_id: int | None = None,
    _admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """관리페이지: 전체 사용자 토큰 사용량(기간/사용자/모델 필터). 요약 + 추이 + TOP."""
    s, e = normalize_range(start, end)

    # 사용자별 합계(사용량 많은 순). 프론트에서 TOP 5 + 전체 표로 활용.
    uq = (
        db.query(
            User.id,
            User.name,
            User.email,
            _sum(TokenUsage.total_tokens),
            _sum(TokenUsage.request_count),
        )
        .join(TokenUsage, TokenUsage.user_id == User.id)
        .filter(TokenUsage.day >= s, TokenUsage.day <= e)
    )
    if model:
        uq = uq.filter(TokenUsage.model == model)
    if user_id:
        uq = uq.filter(TokenUsage.user_id == user_id)
    by_user = [
        {
            "user_id": uid_,
            "name": n,
            "email": em,
            "total_tokens": int(t),
            "request_count": int(r),
        }
        for uid_, n, em, t, r in uq.group_by(User.id, User.name, User.email)
        .order_by(_sum(TokenUsage.total_tokens).desc())
        .all()
    ]

    # 필터 드롭다운용: 전체 사용자 목록 + 사용된 적 있는 모델 전체
    users = [
        {"id": u.id, "name": u.name, "email": u.email}
        for u in db.query(User).order_by(User.name).all()
    ]
    models = [
        m[0]
        for m in db.query(TokenUsage.model).distinct().order_by(TokenUsage.model).all()
    ]

    return {
        "start": s,
        "end": e,
        "totals": usage_totals(db, s, e, model, user_id),
        "daily": usage_daily(db, s, e, model, user_id),
        "by_user": by_user,
        "by_model": usage_by_model(db, s, e, model, user_id),
        "users": users,
        "models": models,
    }


@app.get("/conversations", response_model=list[ConversationOut])
def list_conversations(
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    """현재 사용자의 대화 목록을 '최근 활동순'으로 반환 (프론트 사이드바용)."""
    return (
        db.query(Conversation)
        .filter(Conversation.user_id == current_user.id)
        .order_by(Conversation.updated_at.desc(), Conversation.id.desc())
        .all()
    )


@app.post("/conversations", response_model=ConversationOut)
def create_conversation(
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    """현재 사용자 소유의 빈 대화방을 새로 만든다."""
    convo = Conversation(title="새 대화", user_id=current_user.id)
    db.add(convo)
    db.commit()
    db.refresh(convo)  # DB가 채워준 id 등을 객체에 반영
    return convo


@app.get("/conversations/{conversation_id}/messages", response_model=list[MessageOut])
def get_messages(
    conversation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """특정 대화의 메시지를 시간순으로 반환 (대화 클릭 시 불러오기)."""
    convo = get_owned_conversation(db, conversation_id, current_user)
    return convo.messages  # models.py에서 id순 정렬되도록 설정해둠


@app.post("/conversations/{conversation_id}/title", response_model=ConversationOut)
async def make_title(
    conversation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """대화의 첫 사용자 메시지로 제목을 자동 생성해 저장한다."""
    convo = get_owned_conversation(db, conversation_id, current_user)

    # 첫 사용자 메시지를 찾는다.
    first_user = next((m.content for m in convo.messages if m.role == "user"), "")
    if first_user:
        model = await resolve_model(None)  # 제목용으로는 기본(가벼운) 모델 사용
        convo.title = await generate_title(first_user, model)
        db.commit()
    return convo


@app.patch("/conversations/{conversation_id}", response_model=ConversationOut)
def rename_conversation(
    conversation_id: int,
    body: TitleUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """대화 제목을 사용자가 직접 수정한다."""
    convo = get_owned_conversation(db, conversation_id, current_user)
    title = body.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="제목이 비어 있습니다.")
    convo.title = title[:255]  # 컬럼 길이(255) 초과 방지
    db.commit()
    return convo


@app.delete("/conversations/{conversation_id}")
def delete_conversation(
    conversation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """대화 삭제 (속한 메시지도 cascade로 함께 삭제)."""
    convo = get_owned_conversation(db, conversation_id, current_user)
    db.delete(convo)
    db.commit()
    return {"deleted": conversation_id}


@app.post("/chat", response_model=ChatResponse)
async def chat(
    req: ChatRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    메시지를 받아 (필요시 대화 생성) 저장하고,
    이전 맥락과 함께 모델을 호출한 뒤 응답을 저장/반환한다.
    """
    # 1) 대화방 확보: ID가 오면 '내 대화인지' 확인 후 사용, 없으면 새로 만든다.
    if req.conversation_id is not None:
        convo = get_owned_conversation(db, req.conversation_id, current_user)
    else:
        # 첫 메시지 앞부분을 제목으로, 소유자는 현재 사용자
        convo = Conversation(title=req.message[:30], user_id=current_user.id)
        db.add(convo)
        db.flush()  # commit 전에 id를 먼저 확보

    # 2) 사용자 메시지를 DB에 저장
    db.add(Message(conversation_id=convo.id, role="user", content=req.message))
    db.commit()

    # 3) 멀티턴 맥락 구성 + 4) 모델 호출
    history = build_history(convo)
    model = await resolve_model(req.model)
    reply, usage = await call_hf(
        history,
        model,
        max_tokens=CHAT_MAX_TOKENS,
        temperature=CHAT_TEMPERATURE,
    )

    # 5) 모델 응답을 DB에 저장 (어떤 모델이 답했는지도 함께 기록) + 최근 활동 시각 갱신
    db.add(Message(conversation_id=convo.id, role="bot", content=reply, model=model))
    convo.updated_at = now_utc()
    db.commit()

    # 6) 토큰 사용량 적재 (실패해도 응답에는 영향 없도록 보호)
    try:
        p, c, t = usage_from_api_or_estimate(usage, history, reply)
        record_token_usage(db, current_user.id, model, p, c, t)
    except Exception:
        pass

    return ChatResponse(reply=reply, conversation_id=convo.id)


@app.post("/chat/stream")
async def chat_stream(
    req: ChatRequest, current_user: User = Depends(get_current_user)
):
    """
    /chat 과 동작은 같지만, 응답을 '토큰 단위로 흘려보낸다'(스트리밍).
    프론트는 받는 즉시 화면에 이어붙여 타이핑 효과를 낸다.

    구현 메모:
      - 대화방 확보/사용자 메시지 저장은 스트리밍 시작 '전에' 끝낸다.
        → 그래야 대화 ID를 응답 헤더(X-Conversation-Id)로 먼저 내려줄 수 있다.
      - 실제 스트리밍/DB 저장은 공용 헬퍼 stream_chat_and_save가 담당한다.
      - StreamingResponse 도중에도 DB 세션이 필요하므로, 의존성(get_db) 대신
        세션을 직접 열고 헬퍼가 제너레이터 끝에서 닫는다.
    """
    require_token()
    db = SessionLocal()

    # 1) 대화방 확보 ('내 대화'인지 확인, 없으면 현재 사용자 소유로 생성)
    if req.conversation_id is not None:
        convo = db.get(Conversation, req.conversation_id)
        if not convo or convo.user_id != current_user.id:
            db.close()
            raise HTTPException(status_code=404, detail="대화를 찾을 수 없습니다.")
    else:
        convo = Conversation(title=req.message[:30], user_id=current_user.id)
        db.add(convo)
        db.flush()

    # 2) 사용자 메시지 저장 + 맥락 구성 (스트리밍 전에 완료)
    db.add(Message(conversation_id=convo.id, role="user", content=req.message))
    db.commit()
    convo_id = convo.id
    history = build_history(convo)
    model = await resolve_model(req.model)

    # 3) 대화 ID를 헤더로 먼저 알려주고(새 대화 ID 전달), 응답을 스트리밍한다.
    return StreamingResponse(
        stream_chat_and_save(db, convo_id, history, model, current_user.id),
        media_type="text/plain; charset=utf-8",
        headers={"X-Conversation-Id": str(convo_id)},
    )


@app.post("/chat/stream/regenerate")
async def regenerate_stream(
    req: RegenerateRequest, current_user: User = Depends(get_current_user)
):
    """
    '응답 재생성': 마지막 봇 답변을 버리고, 같은 질문(맥락)으로 새 답변을 다시 스트리밍한다.

    흐름:
      - 대화의 마지막 메시지가 봇 응답이면 DB에서 삭제한다(=마지막 질문만 남김).
      - 남은 맥락(마지막 user 메시지까지)으로 모델을 다시 호출한다.
      - 새 응답은 stream_chat_and_save가 흘려보내며 끝나면 DB에 저장한다.
    """
    require_token()
    db = SessionLocal()

    convo = db.get(Conversation, req.conversation_id)
    if not convo or convo.user_id != current_user.id:
        db.close()
        raise HTTPException(status_code=404, detail="대화를 찾을 수 없습니다.")

    # 마지막 메시지가 봇 응답이면 삭제(재생성을 위해 직전 질문 상태로 되돌린다).
    if convo.messages and convo.messages[-1].role == "bot":
        db.delete(convo.messages[-1])
        db.commit()
        db.refresh(convo)  # 삭제를 messages 관계에 반영

    # 재생성하려면 적어도 사용자 메시지 하나는 남아 있어야 한다.
    if not any(m.role == "user" for m in convo.messages):
        db.close()
        raise HTTPException(status_code=400, detail="재생성할 사용자 메시지가 없습니다.")

    convo_id = convo.id
    history = build_history(convo)
    model = await resolve_model(req.model)

    return StreamingResponse(
        stream_chat_and_save(db, convo_id, history, model, current_user.id),
        media_type="text/plain; charset=utf-8",
        headers={"X-Conversation-Id": str(convo_id)},
    )
