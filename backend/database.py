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
from sqlalchemy import create_engine
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
engine = create_engine(DATABASE_URL, pool_pre_ping=True, echo=False)

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
