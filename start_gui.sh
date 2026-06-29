#!/usr/bin/env sh
set -eu

cd "$(dirname "$0")"

echo "[geo-news-bot] GUI іске қосылып жатыр..."
docker compose --profile gui up -d --build gui

echo
echo "[geo-news-bot] GUI мына жерде ашылады:"
echo "  http://localhost:8000"
echo
echo "Тоқтату үшін:"
echo "  docker compose --profile gui down"
