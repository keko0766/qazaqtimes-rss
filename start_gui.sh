#!/usr/bin/env sh
set -eu

cd "$(dirname "$0")"

echo "[geo-news-bot] starting GUI..."
docker compose --profile gui up -d --build gui

echo
echo "[geo-news-bot] GUI is starting at:"
echo "  http://localhost:8000"
echo
echo "To stop it:"
echo "  docker compose --profile gui down"
