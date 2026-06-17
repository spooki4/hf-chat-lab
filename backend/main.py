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
  GET  /models                        선택 가능한 모델 목록 (드롭다운용)
  GET  /conversations                 대화 목록 (사이드바용)
  POST /conversations                 새 대화 생성
  GET  /conversations/{id}/messages   특정 대화의 메시지 전체
  DELETE /conversations/{id}          대화 삭제
  POST /chat                          메시지 전송 → 모델 응답 (한 번에)
  POST /chat/stream                   메시지 전송 → 응답을 토큰 단위로 스트리밍
"""

import json
import os
import time

import httpx
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import Base, SessionLocal, engine, get_db
from models import Conversation, Message

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

# 앱이 처음 뜰 때, 모델 정의(models.py)에 맞춰 테이블이 없으면 자동 생성한다.
# (DB 자체는 미리 만들어져 있어야 함 → README의 MySQL 준비 단계 참고)
Base.metadata.create_all(bind=engine)

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


class MessageOut(BaseModel):
    id: int
    role: str
    content: str

    # SQLAlchemy 모델 객체를 그대로 응답으로 변환할 수 있게 해주는 설정
    model_config = {"from_attributes": True}


class ConversationOut(BaseModel):
    id: int
    title: str

    model_config = {"from_attributes": True}


class TitleUpdate(BaseModel):
    title: str  # 사용자가 직접 입력한 새 제목


# --- 공용 헬퍼 ---------------------------------------------------------------
def build_history(convo: Conversation) -> list[dict]:
    """
    대화의 모든 메시지를 OpenAI 호환 형식으로 변환한다.
    우리 DB의 role "bot" → API의 "assistant" 로 매핑.
    (이 목록을 통째로 모델에 보내는 것이 '멀티턴/맥락 기억'의 핵심)
    """
    history = [{"role": "system", "content": SYSTEM_PROMPT}]
    for m in convo.messages:
        role = "assistant" if m.role == "bot" else "user"
        history.append({"role": role, "content": m.content})
    return history


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


# --- HuggingFace 호출 함수 ----------------------------------------------------
async def call_hf(
    messages: list[dict], model: str, max_tokens: int = 512, temperature: float | None = None
) -> str:
    """
    messages를 HF에 보내고 '완성된' 응답 텍스트를 한 번에 돌려준다. (비스트리밍)
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
        return data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError):
        raise HTTPException(status_code=500, detail=f"예상치 못한 응답 형식: {data}")


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
    raw = await call_hf(prompt, model, max_tokens=24, temperature=0.0)
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


@app.get("/conversations", response_model=list[ConversationOut])
def list_conversations(db: Session = Depends(get_db)):
    """대화 목록을 최신순으로 반환 (프론트 사이드바용)."""
    return db.query(Conversation).order_by(Conversation.id.desc()).all()


@app.post("/conversations", response_model=ConversationOut)
def create_conversation(db: Session = Depends(get_db)):
    """빈 대화방을 새로 만든다."""
    convo = Conversation(title="새 대화")
    db.add(convo)
    db.commit()
    db.refresh(convo)  # DB가 채워준 id 등을 객체에 반영
    return convo


@app.get("/conversations/{conversation_id}/messages", response_model=list[MessageOut])
def get_messages(conversation_id: int, db: Session = Depends(get_db)):
    """특정 대화의 메시지를 시간순으로 반환 (대화 클릭 시 불러오기)."""
    convo = db.get(Conversation, conversation_id)
    if not convo:
        raise HTTPException(status_code=404, detail="대화를 찾을 수 없습니다.")
    return convo.messages  # models.py에서 id순 정렬되도록 설정해둠


@app.post("/conversations/{conversation_id}/title", response_model=ConversationOut)
async def make_title(conversation_id: int, db: Session = Depends(get_db)):
    """대화의 첫 사용자 메시지로 제목을 자동 생성해 저장한다."""
    convo = db.get(Conversation, conversation_id)
    if not convo:
        raise HTTPException(status_code=404, detail="대화를 찾을 수 없습니다.")

    # 첫 사용자 메시지를 찾는다.
    first_user = next((m.content for m in convo.messages if m.role == "user"), "")
    if first_user:
        model = await resolve_model(None)  # 제목용으로는 기본(가벼운) 모델 사용
        convo.title = await generate_title(first_user, model)
        db.commit()
    return convo


@app.patch("/conversations/{conversation_id}", response_model=ConversationOut)
def rename_conversation(
    conversation_id: int, body: TitleUpdate, db: Session = Depends(get_db)
):
    """대화 제목을 사용자가 직접 수정한다."""
    convo = db.get(Conversation, conversation_id)
    if not convo:
        raise HTTPException(status_code=404, detail="대화를 찾을 수 없습니다.")
    title = body.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="제목이 비어 있습니다.")
    convo.title = title[:255]  # 컬럼 길이(255) 초과 방지
    db.commit()
    return convo


@app.delete("/conversations/{conversation_id}")
def delete_conversation(conversation_id: int, db: Session = Depends(get_db)):
    """대화 삭제 (속한 메시지도 cascade로 함께 삭제)."""
    convo = db.get(Conversation, conversation_id)
    if not convo:
        raise HTTPException(status_code=404, detail="대화를 찾을 수 없습니다.")
    db.delete(convo)
    db.commit()
    return {"deleted": conversation_id}


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest, db: Session = Depends(get_db)):
    """
    메시지를 받아 (필요시 대화 생성) 저장하고,
    이전 맥락과 함께 모델을 호출한 뒤 응답을 저장/반환한다.
    """
    # 1) 대화방 확보: ID가 오면 그걸 쓰고, 없으면 새로 만든다.
    if req.conversation_id is not None:
        convo = db.get(Conversation, req.conversation_id)
        if not convo:
            raise HTTPException(status_code=404, detail="대화를 찾을 수 없습니다.")
    else:
        convo = Conversation(title=req.message[:30])  # 첫 메시지 앞부분을 제목으로
        db.add(convo)
        db.flush()  # commit 전에 id를 먼저 확보

    # 2) 사용자 메시지를 DB에 저장
    db.add(Message(conversation_id=convo.id, role="user", content=req.message))
    db.commit()

    # 3) 멀티턴 맥락 구성 + 4) 모델 호출
    history = build_history(convo)
    reply = await call_hf(
        history,
        await resolve_model(req.model),
        max_tokens=CHAT_MAX_TOKENS,
        temperature=CHAT_TEMPERATURE,
    )

    # 5) 모델 응답을 DB에 저장
    db.add(Message(conversation_id=convo.id, role="bot", content=reply))
    db.commit()

    return ChatResponse(reply=reply, conversation_id=convo.id)


@app.post("/chat/stream")
async def chat_stream(req: ChatRequest):
    """
    /chat 과 동작은 같지만, 응답을 '토큰 단위로 흘려보낸다'(스트리밍).
    프론트는 받는 즉시 화면에 이어붙여 타이핑 효과를 낸다.

    구현 메모:
      - 대화방 확보/사용자 메시지 저장은 스트리밍 시작 '전에' 끝낸다.
        → 그래야 대화 ID를 응답 헤더(X-Conversation-Id)로 먼저 내려줄 수 있다.
      - 모델 응답은 조각들을 모아 두었다가, 스트림이 끝나면 통째로 DB에 저장한다.
      - StreamingResponse 도중에도 DB 세션이 필요하므로, 의존성(get_db) 대신
        세션을 직접 열고 제너레이터 끝에서 닫는다.
    """
    require_token()
    db = SessionLocal()

    # 1) 대화방 확보
    if req.conversation_id is not None:
        convo = db.get(Conversation, req.conversation_id)
        if not convo:
            db.close()
            raise HTTPException(status_code=404, detail="대화를 찾을 수 없습니다.")
    else:
        convo = Conversation(title=req.message[:30])
        db.add(convo)
        db.flush()

    # 2) 사용자 메시지 저장 + 맥락 구성 (스트리밍 전에 완료)
    db.add(Message(conversation_id=convo.id, role="user", content=req.message))
    db.commit()
    convo_id = convo.id
    history = build_history(convo)
    model = await resolve_model(req.model)

    async def token_generator():
        """HF 스트림에서 텍스트 조각(delta)을 받아 그대로 흘려보낸다."""
        collected = []  # 전체 응답을 모아 마지막에 DB 저장용
        payload = {
            "model": model,
            "messages": history,
            "max_tokens": CHAT_MAX_TOKENS,
            "temperature": CHAT_TEMPERATURE,  # 응답 안정성 향상
            "stream": True,  # ← HF에 스트리밍 요청
        }
        headers = {"Authorization": f"Bearer {HF_TOKEN}"}
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                async with client.stream(
                    "POST", HF_API_URL, headers=headers, json=payload
                ) as resp:
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
                            delta = obj["choices"][0]["delta"].get("content")
                        except (json.JSONDecodeError, KeyError, IndexError):
                            continue
                        if delta:
                            collected.append(delta)
                            yield delta  # ← 받는 즉시 프론트로 전달
        except httpx.RequestError as e:
            yield f"⚠️ 연결 실패: {e}"
        finally:
            # 3) 스트림 종료 후 전체 응답을 DB에 저장하고 세션 정리
            full = "".join(collected).strip()
            if full:
                db.add(Message(conversation_id=convo_id, role="bot", content=full))
                db.commit()
            db.close()

    # 대화 ID를 헤더로 먼저 알려준다(프론트가 새 대화 ID를 알 수 있게).
    return StreamingResponse(
        token_generator(),
        media_type="text/plain; charset=utf-8",
        headers={"X-Conversation-Id": str(convo_id)},
    )
