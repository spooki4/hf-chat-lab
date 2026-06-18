"""
DB 테이블 구조 정의 (SQLAlchemy ORM 모델)

테이블 3개:
  - users         : 가입한 사용자 (이메일 + 비밀번호 해시)
  - conversations : 대화방 하나 (어떤 사용자 소유인지 user_id로 연결)
  - messages      : 그 대화방 안의 메시지들 (user / bot)

관계:
  user         1 : N conversation  (한 사용자가 여러 대화방 소유)
  conversation 1 : N message       (한 대화방에 여러 메시지)
"""

from datetime import datetime, timezone

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


def _now():
    """현재 UTC 시각. (DB에 저장 시각을 기록하기 위한 기본값)"""
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 로그인 아이디로 쓰는 이메일. 중복 가입을 막기 위해 unique.
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    # 비밀번호는 절대 평문으로 저장하지 않는다. bcrypt 해시 문자열만 저장.
    password_hash: Mapped[str] = mapped_column(String(255))
    # 사용자 이름(표시용). 가입 시 필수로 받는다.
    name: Mapped[str] = mapped_column(String(100), default="")
    # 연락처. 선택 입력이라 비어 있을 수 있다(nullable).
    phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    # 권한: "admin"(관리자) 또는 "user"(일반). 기본은 일반 사용자.
    role: Mapped[str] = mapped_column(String(16), default="user")
    # 가입 승인 상태: "pending"(대기) / "approved"(승인) / "rejected"(거부).
    # 가입하면 pending이고, 관리자가 승인해야 "approved"가 되어 로그인할 수 있다.
    status: Mapped[str] = mapped_column(String(16), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    # 이 사용자가 소유한 대화방들. 사용자를 지우면 대화도 함께 삭제(cascade).
    conversations: Mapped[list["Conversation"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )

    # 이 사용자의 토큰 사용량 집계 행들. 사용자를 지우면 함께 삭제.
    token_usages: Mapped[list["TokenUsage"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 이 대화방의 주인(어느 사용자 소유인지). 로그인한 사용자만 자기 대화를 보게 하는 핵심.
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    # 대화 제목. 첫 메시지로 자동 생성한다(예: "안녕하세요…").
    title: Mapped[str] = mapped_column(String(255), default="새 대화")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    # 대화방의 소유자(역방향 관계).
    user: Mapped["User"] = relationship(back_populates="conversations")

    # 이 대화방에 속한 메시지들. 대화방을 지우면 메시지도 같이 삭제된다(cascade).
    # order_by로 항상 시간순(=id순) 정렬해서 가져온다.
    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="Message.id",
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 어느 대화방 소속인지 (외래 키). 대화방 삭제 시 함께 삭제.
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE")
    )
    # 누가 한 말인지: "user"(사용자) 또는 "bot"(모델)
    role: Mapped[str] = mapped_column(String(16))
    # 메시지 본문. 길 수 있으므로 Text 타입.
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")


class TokenUsage(Base):
    """
    토큰 사용량 집계 테이블 (일별 × 모델별 × 사용자별로 누적).

    채팅 응답을 받을 때마다 (사용자, 날짜(KST), 모델) 한 행을 찾아
    prompt/completion/total 토큰과 요청 횟수를 더해 쌓는다.
    개별 메시지가 아니라 '하루 단위 합계'로 모아두므로 조회가 가볍다.
    """

    __tablename__ = "token_usage"
    # 같은 (사용자, 날짜, 모델) 조합은 한 행만 존재 → 그 행에 누적한다.
    __table_args__ = (
        UniqueConstraint("user_id", "day", "model", name="uq_usage_user_day_model"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    # 집계 기준 날짜 "YYYY-MM-DD" (한국 시간 KST 기준). 문자열이라 범위 조회가 간단.
    day: Mapped[str] = mapped_column(String(10), index=True)
    # 사용한 모델 id
    model: Mapped[str] = mapped_column(String(255), index=True)
    # 입력/출력/합계 토큰 누적값
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    # 이 그룹에서 발생한 채팅 요청 횟수
    request_count: Mapped[int] = mapped_column(Integer, default=0)

    user: Mapped["User"] = relationship(back_populates="token_usages")
