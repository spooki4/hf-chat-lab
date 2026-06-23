"""
DB 연결 설정 (SQLAlchemy)

여기서는 "어떤 DB에 어떻게 연결할지"만 정의한다.
실제 테이블 구조(모델)는 models.py 에 있다.

핵심 개념:
  - engine   : DB와의 실제 연결 통로
  - Session  : DB에 질의/저장을 수행하는 작업 단위 (요청마다 하나 만들어 쓰고 닫는다)
  - Base     : 모든 테이블 모델이 상속하는 기반 클래스
"""

import os
from urllib.parse import quote_plus

from dotenv import load_dotenv
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker

load_dotenv()


def build_database_url() -> str:
    """
    .env의 접속 정보로 SQLAlchemy 연결 문자열을 만든다.

    우선순위:
      1) DATABASE_URL 이 있으면 그대로 사용 (예: SQLite로 바꿀 때 편리)
         예) sqlite:///./chat.db
      2) 없으면 DB_HOST/DB_PORT/DB_USER/DB_PASSWORD/DB_NAME 항목으로 조립

    핵심: 비밀번호/사용자명에 @, :, / 같은 특수문자가 있어도
          quote_plus()가 자동으로 URL 인코딩(@ -> %40)해주므로
          .env에는 날것 그대로 적으면 된다.
    """
    # 1) 완성된 URL을 직접 줬다면 그것을 우선한다.
    full_url = os.getenv("DATABASE_URL")
    if full_url:
        return full_url

    # 2) 항목별 정보로 조립
    host = os.getenv("DB_HOST", "localhost")
    port = os.getenv("DB_PORT", "3306")
    user = os.getenv("DB_USER", "root")
    password = os.getenv("DB_PASSWORD", "")
    name = os.getenv("DB_NAME", "hf_chat_lab")

    # 특수문자 안전 처리 (사용자명/비밀번호)
    user_enc = quote_plus(user)
    password_enc = quote_plus(password)

    return f"mysql+pymysql://{user_enc}:{password_enc}@{host}:{port}/{name}"


DATABASE_URL = build_database_url()

# engine 생성.
#   pool_pre_ping=True : 끊긴 커넥션을 자동 감지해 재연결(개발 중 끊김 방지)
#   echo=False         : True로 바꾸면 실행되는 SQL이 콘솔에 찍힘(학습 시 유용)
# SQLite(테스트/로컬용)는 기본적으로 '커넥션을 만든 스레드'에서만 쓸 수 있는데,
# FastAPI는 여러 워커 스레드에서 같은 커넥션을 쓸 수 있으므로 그 제약을 끈다.
# (MySQL 등 다른 DB에는 영향 없음)
_connect_args = (
    {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
)
engine = create_engine(
    DATABASE_URL, pool_pre_ping=True, echo=False, connect_args=_connect_args
)

# 요청 처리마다 하나씩 만들어 쓸 Session 공장(factory)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 모든 모델이 상속할 기반 클래스
Base = declarative_base()


def get_db():
    """
    FastAPI 의존성 주입용 함수.
    엔드포인트가 호출될 때 Session을 하나 열어주고,
    응답이 끝나면 (성공/실패와 무관하게) 반드시 닫아준다.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# 나중에 추가된 컬럼들 (테이블별).
#   각 항목: (컬럼명, 컬럼 정의 SQL, 기존 행 보정 SQL 또는 None)
# create_all()은 '없는 테이블'만 만들 뿐 '기존 테이블에 컬럼 추가'는 못 하므로,
# 이미 운영 중인 DB를 위해 빠진 컬럼만 직접 ALTER로 채운다(기존 데이터 보존).
_COLUMN_MIGRATIONS = {
    "users": [
        # 이름: 기존 행은 빈 문자열로 채움
        ("name", "VARCHAR(100) NOT NULL DEFAULT ''", None),
        # 연락처: 선택값이라 NULL 허용
        ("phone", "VARCHAR(30) NULL", None),
        # 권한: 기존 행은 일반 사용자로
        ("role", "VARCHAR(16) NOT NULL DEFAULT 'user'", None),
        # 승인 상태: 승인 기능이 생기기 '전'부터 있던 기존 사용자는
        # 이미 쓰던 계정이므로 자동으로 'approved'로 인정(grandfather)한다.
        ("status", "VARCHAR(16) NOT NULL DEFAULT 'approved'", None),
    ],
    "conversations": [
        # 최근 활동 시각: 기존 행은 생성 시각으로 backfill 후 정렬에 사용.
        (
            "updated_at",
            "DATETIME NULL",
            "UPDATE conversations SET updated_at = created_at WHERE updated_at IS NULL",
        ),
    ],
    "messages": [
        # 봇 응답을 만든 모델 id (기존/사용자 메시지는 NULL).
        ("model", "VARCHAR(255) NULL", None),
    ],
}


def run_migrations():
    """
    스키마를 코드 모델과 맞춘다.
      1) 없는 테이블 생성 (create_all)
      2) 기존 테이블에 빠진 컬럼이 있으면 ALTER로 추가 (+ 필요시 기존 행 보정)
    앱이 뜰 때 한 번 호출한다. 이미 맞춰져 있으면 아무 일도 하지 않는다(idempotent).
    """
    Base.metadata.create_all(bind=engine)

    inspector = inspect(engine)
    tables = set(inspector.get_table_names())

    with engine.begin() as conn:
        for table, columns in _COLUMN_MIGRATIONS.items():
            if table not in tables:
                continue  # 새로 만들어진 테이블은 이미 최신 스키마
            existing = {c["name"] for c in inspector.get_columns(table)}
            for col, ddl, backfill in columns:
                if col in existing:
                    continue
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}"))
                if backfill:
                    conn.execute(text(backfill))
