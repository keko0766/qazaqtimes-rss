#!/bin/bash
set -e

cd "$(dirname "$0")"

LOG_FILE="data/ollama_setup.log"
STATUS_FILE="data/ollama_status.json"
URL="http://localhost:8000"
DEFAULT_OLLAMA_MODEL="qwen2.5:7b"
OLLAMA_PULL_TIMEOUT_SECONDS="${OLLAMA_PULL_TIMEOUT_SECONDS:-7200}"

write_ollama_status() {
  local state="$1"
  local message="$2"
  local error="${3:-}"
  python3 - "$STATUS_FILE" "$state" "$message" "$error" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

path = Path(sys.argv[1])
path.parent.mkdir(parents=True, exist_ok=True)
payload = {
    "state": sys.argv[2],
    "message": sys.argv[3],
    "error": sys.argv[4],
    "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
}
path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
PY
}

current_ollama_model() {
  if [ -n "${OLLAMA_MODEL:-}" ]; then
    echo "$OLLAMA_MODEL"
    return
  fi
  if [ -f .env ]; then
    local env_model
    env_model="$(awk -F= '/^OLLAMA_MODEL=/{print $2; exit}' .env | tr -d '"' | tr -d "'")"
    if [ -n "$env_model" ]; then
      echo "$env_model"
      return
    fi
  fi
  echo "$DEFAULT_OLLAMA_MODEL"
}

run_with_timeout() {
  local timeout_seconds="$1"
  shift
  "$@" &
  local pid=$!
  local elapsed=0
  while kill -0 "$pid" >/dev/null 2>&1; do
    if [ "$elapsed" -ge "$timeout_seconds" ]; then
      kill "$pid" >/dev/null 2>&1 || true
      wait "$pid" >/dev/null 2>&1 || true
      return 124
    fi
    sleep 5
    elapsed=$((elapsed + 5))
  done
  wait "$pid"
}

run_ollama_setup() {
  mkdir -p data
  local model_name
  model_name="$(current_ollama_model)"
  write_ollama_status "starting" "Ollama контейнері іске қосылып жатыр"
  {
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Ollama setup басталды"
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Ollama model: $model_name"
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] docker compose --profile ollama up -d ollama"
    docker compose --profile ollama up -d ollama &
    local compose_pid=$!

    local ready=""
    for _ in $(seq 1 120); do
      if docker ps --filter "name=^/geo-news-ollama$" --filter "status=running" --format "{{.Names}}" | grep -q "^geo-news-ollama$"; then
        ready="true"
        break
      fi
      if docker ps -a --filter "name=^/geo-news-ollama$" --filter "status=created" --format "{{.Names}}" | grep -q "^geo-news-ollama$"; then
        docker start geo-news-ollama >/dev/null 2>&1 || true
      fi
      if ! kill -0 "$compose_pid" >/dev/null 2>&1 && ! docker ps -a --filter "name=^/geo-news-ollama$" --format "{{.Names}}" | grep -q "^geo-news-ollama$"; then
        break
      fi
      sleep 2
    done

    kill "$compose_pid" >/dev/null 2>&1 || true
    wait "$compose_pid" >/dev/null 2>&1 || true

    if [ "$ready" != "true" ]; then
      write_ollama_status "error" "Ollama іске қосылмады" "docker compose up failed"
      echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] ERROR: Ollama service start failed"
      exit 0
    fi

    write_ollama_status "pulling" "Ollama моделі жүктеліп жатыр: $model_name"
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] docker compose --profile ollama --profile setup run --rm ollama-pull"
    if run_with_timeout "$OLLAMA_PULL_TIMEOUT_SECONDS" docker compose --profile ollama --profile setup run --rm ollama-pull; then
      write_ollama_status "ready" "Ollama дайын: $model_name"
      echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Ollama setup дайын"
    else
      write_ollama_status "error" "Ollama моделі жүктелмеді: $model_name" "ollama pull failed or timed out"
      echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] ERROR: Ollama model pull failed"
    fi
  } >> "$LOG_FILE" 2>&1
}

if [ "${1:-}" = "--ollama-setup" ]; then
  run_ollama_setup
  exit 0
fi

start_ollama_setup() {
  nohup "$PWD/start.sh" --ollama-setup >/dev/null 2>&1 &
}

echo "geo-news-bot іске қосылуда..."

if ! command -v docker >/dev/null 2>&1; then
  echo "Қате: Docker орнатылмаған. Алдымен Docker Desktop орнатыңыз."
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  echo "Қате: Docker Desktop қосылмаған. Docker-ді ашып, қайта іске қосыңыз."
  exit 1
fi

if [ ! -f .env ]; then
  if [ -f .env.example ]; then
    cp .env.example .env
    echo ".env файлы .env.example ішінен жасалды."
  else
    echo "Қате: .env.example табылмады."
    exit 1
  fi
fi

mkdir -p data output

echo "GUI контейнері дайындалып жатыр..."
docker compose --profile gui up -d --build gui

echo "Ollama background-та дайындалады..."
start_ollama_setup

echo "GUI дайын: $URL"

if command -v open >/dev/null 2>&1; then
  open "$URL"
elif command -v xdg-open >/dev/null 2>&1; then
  xdg-open "$URL" >/dev/null 2>&1 || true
else
  echo "Браузер автоматты ашылмады. Мына адресті қолмен ашыңыз: $URL"
fi

echo "Браузерде \"Бүгінгі 5 мақаланы жасау\" батырмасын басыңыз."
echo "Ollama setup журналы: $LOG_FILE"
