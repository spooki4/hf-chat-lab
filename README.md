# 🤗 hf-chat-lab

HuggingFace 무료 모델을 사용하는 학습용 AI 챗봇 웹앱.

- **백엔드**: Python + FastAPI (HuggingFace Inference Providers 연동)
- **프론트엔드**: React (Vite) + react-router-dom + recharts(그래프)
- **DB**: MySQL (SQLAlchemy ORM) — 대화 기록·사용자·토큰 사용량 영구 저장
- **동작**: 메시지 입력 → DB 저장 → 이전 맥락과 함께 HF 모델 호출(멀티턴) → 응답 표시/저장

### 기능

**채팅**
- 💬 메시지 보내고 응답 받기
- ⌨️ 스트리밍 응답: 답변이 토큰 단위로 실시간 출력 (타이핑 효과)
- 📝 마크다운 렌더링 + 코드블록 문법 하이라이트
- 🔀 모델 선택 드롭다운 (실시간 가용 목록에서 선택)
- 🏷️ 대화 제목 자동 생성 (첫 메시지를 모델이 요약) + 직접 수정(✏️)
- 💾 대화 내용 DB 저장 (브라우저를 닫아도 유지) · 🧠 멀티턴 맥락 기억
- 📂 대화 목록 사이드바 (새 대화 / 선택 / 삭제)
- 📋 메시지 복사 · 🔄 응답 재생성 · ✂️ 토큰 절약(최근 N개만 전송, `HISTORY_WINDOW`)

**사용자 · 권한**
- 🔐 회원가입·로그인(JWT): 이메일/비밀번호 + 이름·연락처, 비밀번호 확인 입력, 사용자별 대화 분리
- ✅ 가입 승인제: 가입 후 **관리자 승인**을 받아야 로그인 가능 (`ADMIN_EMAILS`로 최초 관리자 지정)
- 🛡️ 권한 분리(관리자/일반) + **관리자 페이지**: 사용자 목록/승인·거부/권한변경/삭제
- 🙋 **마이페이지**: 정보변경(이름·연락처·비밀번호)

**토큰 사용량 모니터링**
- 📊 채팅 시 (사용자 × 날짜 × 모델) 단위로 토큰 사용량 자동 적재
- 📈 마이페이지: 내 사용량(요약·일별 추이 그래프·모델별 분포), 기간/모델 필터
- 📉 관리페이지: 전체 사용자 사용량(사용자 TOP5·모델 TOP5·표), 기간/사용자/모델 필터

```
hf-chat-lab/
├── backend/      # FastAPI + HuggingFace + DB
│   ├── main.py          # API 엔드포인트 (인증/관리/채팅/사용량)
│   ├── auth.py          # 비밀번호 해싱 + JWT + 현재 사용자/관리자 판별
│   ├── database.py      # DB 연결 설정 + 경량 자동 마이그레이션
│   ├── models.py        # 테이블 정의 (users, conversations, messages, token_usage)
│   ├── requirements.txt
│   └── .env.example
├── frontend/     # React (Vite)
│   └── src/             # App(채팅) · Login · AdminPage · MyPage · 사용량(UsageShared 등)
└── README.md
```

---

## 0. 사전 준비: HuggingFace 토큰 발급

1. https://huggingface.co 가입/로그인
2. https://huggingface.co/settings/tokens 접속
3. **New token** → 이름 입력 → 권한은 **Read** 로 충분 → 생성
4. `hf_` 로 시작하는 토큰을 복사해 둡니다. (잠시 후 `.env`에 붙여넣습니다)

> 무료 토큰에는 월 사용량 한도가 있습니다. 학습/테스트 용도로는 충분합니다.

---

## 0-2. DB 준비 (MySQL)

대화 기록을 저장할 데이터베이스(스키마)를 한 번만 만들어 둡니다.
(테이블은 백엔드가 처음 실행될 때 자동으로 생성됩니다.)

```bash
# MySQL에 접속한 뒤
mysql -h 127.0.0.1 -u root -p

# 접속되면 아래 실행 (한글/이모지 안전하게 utf8mb4)
CREATE DATABASE IF NOT EXISTS hf_chat_lab
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

> **SQLite로 쓰고 싶다면?** MySQL 준비 없이도 됩니다. `backend/.env`의
> `DATABASE_URL`을 `sqlite:///./chat.db` 로 바꾸기만 하면 파일 DB로 동작합니다.
> (ORM 덕분에 코드 수정 없이 연결 문자열만 바꾸면 됩니다.)

---

## 1. 백엔드 실행 (FastAPI)

터미널에서 백엔드 폴더로 이동합니다.

```bash
cd backend
```

### 1-1. 가상환경 생성 & 활성화

```bash
# 가상환경 생성 (.venv 폴더가 만들어집니다)
python3 -m venv .venv

# 활성화 (macOS / Linux)
source .venv/bin/activate

# 활성화 (Windows PowerShell)
# .venv\Scripts\Activate.ps1
```

활성화되면 터미널 프롬프트 앞에 `(.venv)` 가 붙습니다.

### 1-2. 의존성 설치

```bash
pip install -r requirements.txt
```

### 1-3. 환경변수 설정 (.env)

`.env.example` 을 복사해 `.env` 를 만들고, 발급받은 토큰을 넣습니다.

```bash
cp .env.example .env
```

`.env` 파일을 열어 수정:

```
HF_TOKEN=hf_본인의_실제_토큰

# 로그인 토큰(JWT) 서명용 비밀키 — 길고 무작위인 값으로 설정
# 생성 예) python -c "import secrets; print(secrets.token_hex(32))"
JWT_SECRET=무작위_긴_문자열

# 관리자 이메일(쉼표로 여러 개) — 여기 적힌 이메일은 가입/로그인 시
# 자동으로 관리자 + 승인 처리됩니다. (최초 관리자 지정용)
ADMIN_EMAILS=admin@example.com

DB_HOST=127.0.0.1
DB_PORT=3306
DB_USER=root
DB_PASSWORD=DB_비밀번호
DB_NAME=hf_chat_lab
```

> 💡 **첫 관리자 만들기**: `ADMIN_EMAILS`에 본인 이메일을 넣고 서버를 (재)시작하면,
> 그 이메일 계정은 자동으로 `관리자 + 승인됨` 상태가 됩니다. 이후 일반 가입자는
> 관리자 페이지에서 승인해 주면 로그인할 수 있습니다.
>
> 💡 비밀번호에 `@ : / ` 같은 특수문자가 있어도 **코드가 자동으로 URL 인코딩**하므로
> 날것 그대로 적으면 됩니다. (예전처럼 `@`→`%40` 직접 변환 불필요)
>
> SQLite로 바꾸고 싶으면 위 `DB_*` 대신 `DATABASE_URL=sqlite:///./chat.db` 한 줄만 쓰면 됩니다.
> (`DATABASE_URL`이 있으면 `DB_*`보다 우선합니다.)
>
> `.env` 는 `.gitignore` 에 등록되어 있어 git에 올라가지 않습니다.

### 1-4. 서버 실행

```bash
uvicorn main:app --reload --port 8000
```

- 헬스 체크: 브라우저에서 http://localhost:8000 → `{"status":"ok", ...}`
- 자동 생성 API 문서: http://localhost:8000/docs (여기서 `/chat`을 직접 테스트할 수 있습니다)

---

## 2. 프론트엔드 실행 (React + Vite)

**새 터미널**을 열어 (백엔드는 켜둔 채로) 프론트 폴더로 이동합니다.

```bash
cd frontend
```

### 2-1. 의존성 설치

```bash
npm install
```

> Node.js가 필요합니다. 없으면 https://nodejs.org 에서 LTS 버전을 설치하세요.

### 2-2. (선택) 백엔드 주소 변경

기본값은 `http://localhost:8000` 입니다. 바꾸려면:

```bash
cp .env.example .env   # 그리고 VITE_API_URL 수정
```

### 2-3. 개발 서버 실행

```bash
npm run dev
```

터미널에 표시되는 주소(보통 http://localhost:5173)를 브라우저에서 엽니다.

---

## 3. 사용하기

1. 백엔드(8000)와 프론트엔드(5173)를 **둘 다** 실행
2. http://localhost:5173 접속
3. **회원가입**(이메일·비밀번호·이름·연락처) → 관리자 승인 후 **로그인**
   - `ADMIN_EMAILS`로 지정한 본인 계정은 가입 즉시 관리자로 승인되어 바로 로그인됩니다.
   - 다른 사용자는 관리자가 **🛠 관리 → 사용자 관리**에서 승인해야 로그인할 수 있습니다.
4. 입력창에 메시지를 쓰고 **전송** → HuggingFace 모델의 응답이 표시됩니다 🎉
5. **👤 마이** 에서 정보변경·내 토큰 사용량 확인, 관리자는 **🛠 관리** 에서 사용자/전체 사용량 관리

> 첫 요청은 모델이 깨어나는 데(cold start) 수 초 걸릴 수 있습니다.

---

## 자주 묻는 문제 (Troubleshooting)

| 증상 | 원인 / 해결 |
| --- | --- |
| `HF_TOKEN이 설정되지 않았습니다` | `backend/.env` 에 `HF_TOKEN` 을 넣고 서버를 재시작 |
| 401 / 403 오류 | 토큰이 잘못됨. 토큰을 다시 발급받아 `.env` 수정 |
| CORS 오류 (브라우저 콘솔) | 백엔드가 5173을 허용하도록 설정됨. 프론트 포트가 다르면 `backend/main.py`의 `allow_origins` 수정 |
| `not supported by any provider` / `model_not_supported` | 해당 모델 provider가 **일시적으로** 빠진 경우가 많음. 잠시 후 재시도하거나 드롭다운에서 다른 모델 선택 |
| 응답이 느림 | 무료 모델 cold start. 잠시 후 재시도 |
| `Access denied` / `Can't connect` (DB) | `DATABASE_URL`의 비밀번호/포트 확인, 특수문자 인코딩(`@`→`%40`), MySQL 실행 여부 확인 |
| `Unknown database 'hf_chat_lab'` | `0-2. DB 준비` 단계의 `CREATE DATABASE` 를 실행했는지 확인 |
| 401 / `로그인이 필요합니다` | 토큰 만료/무효. 다시 로그인하세요. (로그아웃 시 토큰 삭제됨) |
| `로그인이 만료되었습니다` | JWT 유효기간(기본 7일) 경과. 재로그인하면 됩니다. |
| `아직 승인 대기 중입니다` | 가입 후 관리자 승인 전. 관리자가 **🛠 관리 → 사용자 관리**에서 승인하면 로그인됩니다. |
| 관리 버튼(🛠)이 안 보임 | 관리자 계정이 아님. `.env`의 `ADMIN_EMAILS`에 이메일을 넣고 서버를 재시작하면 해당 계정이 관리자가 됩니다. |
| `Unknown column` 등 스키마 오류 | 기능 추가로 컬럼이 늘어남. 백엔드가 시작 시 **빠진 컬럼을 자동으로 추가**(경량 마이그레이션)하므로 보통 서버만 재시작하면 됩니다. |

---

## API 엔드포인트 요약

> `/auth/register`·`/auth/login`·`/`·`/models`를 제외한 엔드포인트는 모두 **로그인 필요**,
> `/admin/*`는 **관리자 권한**이 필요합니다.
> 프론트는 로그인 시 받은 토큰을 `Authorization: Bearer <토큰>` 헤더로 보냅니다.

**인증 · 사용자**

| 메서드 | 경로 | 설명 |
| --- | --- | --- |
| GET | `/` | 헬스 체크 |
| GET | `/models` | 선택 가능한 모델 목록 (드롭다운용) |
| POST | `/auth/register` | 회원가입 (`{email, password, name, phone?}`) → **승인 대기**(토큰 없음, 관리자 이메일은 자동 승인) |
| POST | `/auth/login` | 로그인 (`{email, password}`) → 승인된 사용자만 토큰 발급(`{access_token, email, role}`) |
| GET | `/auth/me` | 현재 로그인한 사용자 정보 |
| PATCH | `/auth/me` | 내 정보 변경 (`{name?, phone?, current_password?, new_password?}`) |

**대화 · 채팅** (로그인 필요)

| 메서드 | 경로 | 설명 |
| --- | --- | --- |
| GET | `/conversations` | 내 대화 목록 |
| POST | `/conversations` | 새 대화 생성 |
| GET | `/conversations/{id}/messages` | 특정 대화의 메시지 전체 |
| POST | `/conversations/{id}/title` | 첫 메시지로 대화 제목 자동 생성 |
| PATCH | `/conversations/{id}` | 대화 제목 직접 수정 (`{title}`) |
| DELETE | `/conversations/{id}` | 대화 삭제 |
| POST | `/chat` | 메시지 전송 → 모델 응답 한 번에 (`{message, conversation_id?, model?}`) |
| POST | `/chat/stream` | 메시지 전송 → 토큰 단위 스트리밍. 새 대화 ID는 `X-Conversation-Id` 헤더로 반환 |
| POST | `/chat/stream/regenerate` | 마지막 봇 답변을 삭제하고 같은 질문으로 다시 스트리밍 (`{conversation_id, model?}`) |

**토큰 사용량 · 관리** (관리자 전용은 🛡️)

| 메서드 | 경로 | 설명 |
| --- | --- | --- |
| GET | `/usage/me` | 내 토큰 사용량 (`?start&end&model`) — 요약·일별·모델별 |
| GET | `/admin/users` | 🛡️ 전체 사용자 목록(승인 대기 우선) |
| PATCH | `/admin/users/{id}` | 🛡️ 사용자 승인/거부·권한변경 (`{status?, role?}`) |
| DELETE | `/admin/users/{id}` | 🛡️ 사용자 삭제(대화·사용량 함께 삭제) |
| GET | `/admin/usage` | 🛡️ 전체 사용량 (`?start&end&model&user_id`) — 요약·일별·사용자/모델 TOP |

> 모델 목록은 하드코딩하지 않고 HF 라우터의 **실시간 목록**(`GET /v1/models`)에서 가져옵니다.
> ([backend/main.py](backend/main.py)의 `fetch_available_models`) — provider 교체로 목록이 바뀌어도 자동 반영됩니다.

---

## 다음 단계 아이디어 (학습 확장)

- ✅ ~~멀티턴~~ · ~~기록 저장~~ · ~~스트리밍~~ · ~~모델 선택~~ · ~~마크다운+하이라이트~~ · ~~제목 자동생성/수정~~ — 완료!
- ✅ ~~긴 대화 토큰 절약 (최근 N개만 전송)~~ · ~~메시지 복사 버튼~~ · ~~응답 재생성~~ — 완료!
- ✅ ~~사용자 인증(JWT 로그인)으로 사용자별 대화 분리~~ — 완료!
- ✅ ~~관리자/일반 권한 분리 + 가입 승인제 + 관리자 페이지(사용자 관리)~~ — 완료!
- ✅ ~~마이페이지(정보변경)~~ · ~~토큰 사용량 모니터링(마이/관리 대시보드, 그래프)~~ — 완료!

> **(선택) 토큰 절약 고도화 — 오래된 대화 '요약' 압축**
> 윈도우(최근 N개) 밖으로 밀려난 옛 메시지를 모델로 요약해 system에 합쳐 전달하는 방식.
> 맥락 유지력은 올라가지만 **요약용 LLM 호출 추가(비용·지연↑), 요약 저장/갱신 상태 관리,
> 응답 재생성과의 엣지케이스**까지 복잡도가 커진다. 현재 윈도우 방식으로도 토큰 문제는
> 충분히 해결되므로, 지금은 **보류**하고 심화 학습 과제로 남겨둔다.
