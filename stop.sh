#!/bin/bash
set -e

cd "$(dirname "$0")"

echo "geo-news-bot тоқтатылып жатыр..."
docker compose --profile gui --profile ollama down
if docker ps -a --filter "name=^/geo-news-ollama$" --format "{{.Names}}" | grep -q "^geo-news-ollama$"; then
  docker rm -f geo-news-ollama >/dev/null 2>&1 || true
fi
echo "geo-news-bot тоқтатылды."
