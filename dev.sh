#!/usr/bin/env bash
set -euo pipefail

# ============================================================================
# hf-chat-lab 로컬 개발 환경 스크립트
#
# 사용법:
#   ./dev.sh start                # backend + frontend 둘 다 백그라운드 실행
#   ./dev.sh start backend        # backend 만
#   ./dev.sh start frontend       # frontend 만
#   ./dev.sh stop                 # 둘 다 종료
#   ./dev.sh stop backend         # backend 만 종료
#   ./dev.sh restart
#   ./dev.sh status               # 실행 상태 + 포트 확인
#   ./dev.sh logs                 # backend + frontend 로그 tail -f
#   ./dev.sh logs backend         # backend 로그만
#
# 참고: backend(uvicorn --reload) 와 frontend(vite HMR) 둘 다 코드가 바뀌면
#       자동으로 리로드됩니다. 즉 코드 수정 때마다 재시작할 필요는 거의 없고,
#       의존성/환경변수 변경처럼 프로세스를 통째로 다시 띄워야 할 때만 restart.
#
# PID / 로그는 .run/ 에 저장됩니다 (gitignored).
# ============================================================================

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
RUN_DIR="${REPO_ROOT}/.run"
BACKEND_PORT=8000
FRONTEND_PORT=5173

# 백그라운드 프로세스가 자기 process group 의 리더가 되도록 job control 활성화.
# 이래야 stop 시 `kill -TERM -<pgid>` 로 자식(uvicorn reloader, vite 등)까지 정리됨.
set -m

mkdir -p "$RUN_DIR"

# ─── 유틸 ────────────────────────────────────────────────

port_holder() {
  # 포트를 LISTEN 중인 프로세스의 PID (없으면 empty)
  lsof -iTCP:"$1" -sTCP:LISTEN -P -n 2>/dev/null | awk 'NR>1 {print $2; exit}'
}

is_alive() {
  kill -0 "$1" 2>/dev/null
}

is_descendant_of() {
  # is_descendant_of <child_pid> <ancestor_pid>
  # 부모 체인을 거슬러 올라가면서 ancestor 를 만나는지 확인.
  local pid=$1 ancestor=$2 ppid
  local hops=0
  while [[ -n "$pid" && "$pid" != "0" && "$pid" != "1" && $hops -lt 16 ]]; do
    [[ "$pid" == "$ancestor" ]] && return 0
    ppid=$(ps -o ppid= -p "$pid" 2>/dev/null | tr -d ' ')
    [[ -z "$ppid" || "$ppid" == "$pid" ]] && return 1
    pid="$ppid"
    hops=$((hops + 1))
  done
  return 1
}

service_pid() {
  local name=$1
  local pid_file="${RUN_DIR}/${name}.pid"
  [[ -f "$pid_file" ]] || return 1
  local pid
  pid=$(cat "$pid_file")
  [[ -n "$pid" ]] && is_alive "$pid" || return 1
  echo "$pid"
}

# ─── 개별 서비스 start ──────────────────────────────────

start_backend() {
  local pid_file="${RUN_DIR}/backend.pid"
  local log_file="${RUN_DIR}/backend.log"

  if pid=$(service_pid backend); then
    echo "  backend: already running (pid=$pid)"
    return 0
  fi
  rm -f "$pid_file"

  if [[ ! -x "${REPO_ROOT}/backend/.venv/bin/python" ]]; then
    echo "  backend: ERROR — backend/.venv/bin/python 없음."
    echo "           먼저 venv 생성 + requirements 설치 해주세요:"
    echo "             cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
    return 1
  fi
  if [[ ! -f "${REPO_ROOT}/backend/.env" ]]; then
    echo "  backend: WARN — backend/.env 없음. HF_TOKEN / DB 접속정보가 .env 에서 로드되므로"
    echo "           없으면 OS 환경변수만 사용됩니다."
  fi

  # `python -m uvicorn` 으로 실행 (venv 의 console_scripts shebang 우회 →
  # 레포 경로 바뀌어도 안전). --reload 로 코드 변경 자동 반영.
  # stdin 은 /dev/null 로 끊기.
  (
    cd "${REPO_ROOT}/backend"
    exec ./.venv/bin/python -m uvicorn main:app --reload --host 0.0.0.0 --port "$BACKEND_PORT"
  ) </dev/null >"$log_file" 2>&1 &
  local pid=$!
  echo "$pid" > "$pid_file"
  echo "  backend: started (pid=$pid, port=$BACKEND_PORT, log=.run/backend.log)"
}

start_frontend() {
  local pid_file="${RUN_DIR}/frontend.pid"
  local log_file="${RUN_DIR}/frontend.log"

  if pid=$(service_pid frontend); then
    echo "  frontend: already running (pid=$pid)"
    return 0
  fi
  rm -f "$pid_file"

  if [[ ! -d "${REPO_ROOT}/frontend/node_modules" ]]; then
    echo "  frontend: ERROR — frontend/node_modules 없음. 먼저 의존성 설치:"
    echo "         cd frontend && npm install"
    return 1
  fi

  # stdin 을 /dev/null 로 끊어야 vite 의 대화형 키 리스너가 TTY EIO 로 안 죽음.
  (
    cd "${REPO_ROOT}/frontend"
    exec npm run dev -- --host
  ) </dev/null >"$log_file" 2>&1 &
  local pid=$!
  echo "$pid" > "$pid_file"
  echo "  frontend: started (pid=$pid, port=$FRONTEND_PORT, log=.run/frontend.log)"
}

# ─── 개별 서비스 stop ───────────────────────────────────

stop_service() {
  local name=$1
  local pid_file="${RUN_DIR}/${name}.pid"

  if [[ ! -f "$pid_file" ]]; then
    echo "  $name: not running"
    return 0
  fi
  local pid
  pid=$(cat "$pid_file")

  if ! is_alive "$pid"; then
    echo "  $name: stale pid file (pid=$pid 없음), 정리"
    rm -f "$pid_file"
    return 0
  fi

  echo "  $name: SIGTERM → pid=$pid (process group)"
  # 음수 PID = process group 대상. group 리더가 아니면 실패하므로 개별 PID 로 fallback.
  kill -TERM -"$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true

  local i
  for i in 1 2 3; do
    sleep 1
    if ! is_alive "$pid"; then
      rm -f "$pid_file"
      echo "  $name: stopped"
      return 0
    fi
  done

  echo "  $name: SIGKILL (graceful 실패)"
  kill -KILL -"$pid" 2>/dev/null || kill -KILL "$pid" 2>/dev/null || true
  # 혹시 남은 자식 프로세스 정리
  pkill -KILL -P "$pid" 2>/dev/null || true
  rm -f "$pid_file"
  echo "  $name: killed"
}

# ─── 커맨드 ──────────────────────────────────────────────

cmd_start() {
  local target="${1:-all}"
  echo "▶ dev.sh start ($target)"
  case "$target" in
    backend)  start_backend ;;
    frontend) start_frontend ;;
    all)      start_backend; start_frontend ;;
    *) echo "Usage: ./dev.sh start [backend|frontend|all]"; exit 1 ;;
  esac
}

cmd_stop() {
  local target="${1:-all}"
  echo "■ dev.sh stop ($target)"
  case "$target" in
    backend)  stop_service backend ;;
    frontend) stop_service frontend ;;
    all)      stop_service frontend; stop_service backend ;;
    *) echo "Usage: ./dev.sh stop [backend|frontend|all]"; exit 1 ;;
  esac
}

cmd_restart() {
  cmd_stop "${1:-all}"
  echo ""
  cmd_start "${1:-all}"
}

cmd_status() {
  echo "● dev.sh status"
  _status_one backend  "$BACKEND_PORT"
  _status_one frontend "$FRONTEND_PORT"
}

_status_one() {
  local name=$1 port=$2
  local pid_file="${RUN_DIR}/${name}.pid"
  local holder
  holder=$(port_holder "$port" || true)

  if [[ -f "$pid_file" ]]; then
    local pid
    pid=$(cat "$pid_file")
    if is_alive "$pid"; then
      # 포트를 잡은 프로세스가 tracked pid 자신이거나 그 자손이면 정상.
      # (예: frontend 는 npm → node/vite 구조라 자식이 포트를 잡음)
      if [[ -z "$holder" || "$holder" == "$pid" ]] || is_descendant_of "$holder" "$pid"; then
        printf "  %-9s UP   pid=%s  port=%s\n" "$name" "$pid" "$port"
      else
        printf "  %-9s UP   pid=%s  port=%s (주의: %s 는 외부 pid=%s 가 점유)\n" \
          "$name" "$pid" "$port" "$port" "$holder"
      fi
      return
    fi
    printf "  %-9s DOWN (stale pid file, pid=%s 없음)\n" "$name" "$pid"
    return
  fi

  if [[ -n "$holder" ]]; then
    printf "  %-9s ?    port=%s 가 pid=%s 에 의해 점유됨 (dev.sh 로 시작하지 않음)\n" \
      "$name" "$port" "$holder"
  else
    printf "  %-9s DOWN\n" "$name"
  fi
}

cmd_logs() {
  local target="${1:-all}"
  case "$target" in
    backend)
      [[ -f "${RUN_DIR}/backend.log" ]] || { echo "backend.log 없음 (아직 실행된 적 없음)"; exit 1; }
      exec tail -f "${RUN_DIR}/backend.log"
      ;;
    frontend)
      [[ -f "${RUN_DIR}/frontend.log" ]] || { echo "frontend.log 없음"; exit 1; }
      exec tail -f "${RUN_DIR}/frontend.log"
      ;;
    all)
      shopt -s nullglob
      local logs=("${RUN_DIR}"/*.log)
      shopt -u nullglob
      if [[ ${#logs[@]} -eq 0 ]]; then
        echo "로그 파일이 아직 없습니다. 먼저 ./dev.sh start 하세요."
        exit 1
      fi
      exec tail -f "${logs[@]}"
      ;;
    *) echo "Usage: ./dev.sh logs [backend|frontend|all]"; exit 1 ;;
  esac
}

usage() {
  cat <<EOF
hf-chat-lab 로컬 개발 환경 스크립트

사용법:
  ./dev.sh start   [backend|frontend|all]   # 기본 all
  ./dev.sh stop    [backend|frontend|all]
  ./dev.sh restart [backend|frontend|all]
  ./dev.sh status
  ./dev.sh logs    [backend|frontend|all]

포트:
  backend   ${BACKEND_PORT}
  frontend  ${FRONTEND_PORT}

파일:
  .run/<name>.pid    프로세스 ID
  .run/<name>.log    stdout/stderr
EOF
}

# ─── 디스패치 ────────────────────────────────────────────

cmd="${1:-}"
shift || true

case "$cmd" in
  start)   cmd_start   "$@" ;;
  stop)    cmd_stop    "$@" ;;
  restart) cmd_restart "$@" ;;
  status)  cmd_status       ;;
  logs)    cmd_logs    "$@" ;;
  ""|-h|--help|help) usage ;;
  *) echo "Unknown command: $cmd"; echo ""; usage; exit 1 ;;
esac
