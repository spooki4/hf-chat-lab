# 백엔드(FastAPI) 컨테이너 이미지.
# 로컬 .venv와 무관하게, requirements.txt만으로 동일한 실행 환경을 재현한다.
FROM python:3.10-slim

# - PYTHONUNBUFFERED: 로그가 버퍼에 갇히지 않고 바로 출력되게(docker logs 즉시 확인)
# - PYTHONDONTWRITEBYTECODE: 컨테이너 안에 .pyc 파일을 남기지 않음
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# 의존성만 먼저 복사해서 설치 → 코드만 바뀔 때 이 레이어는 캐시 재사용(빌드 속도↑)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 애플리케이션 코드 복사 (.dockerignore로 .venv/.env/tests 등은 제외됨)
COPY . .

EXPOSE 8000

# 컨테이너에서는 --reload 없이 실행(코드 변경 자동반영은 로컬 dev.sh의 몫).
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
