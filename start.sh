#!/bin/bash
set -e

cd "$(dirname "$0")"

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

echo "GUI контейнері дайындалып жатыр..."
docker compose --profile gui up -d --build gui

URL="http://localhost:8000"
echo "GUI дайын: $URL"

if command -v open >/dev/null 2>&1; then
  open "$URL"
elif command -v xdg-open >/dev/null 2>&1; then
  xdg-open "$URL" >/dev/null 2>&1 || true
else
  echo "Браузер автоматты ашылмады. Мына адресті қолмен ашыңыз: $URL"
fi

echo "Браузерде \"Бүгінгі 5 мақаланы жасау\" батырмасын басыңыз."
