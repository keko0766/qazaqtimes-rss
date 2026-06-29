# geo-news-bot

Лёгкий Docker MVP для геополитического дайджеста:

RSS/GDELT -> SQLite -> deduplicate -> classify/filter -> event cluster -> Markdown digest -> optional Ollama writer fallback.

Проект сохраняет только метаданные: `title`, `url`, `source`, `published_at`, `summary`, `tags` и простые score-поля. Полные тексты статей не скачиваются, автопубликации нет.

## Quick Start

Default-режим запускает только `app` и не скачивает Ollama image:

```bash
docker compose run --rm app python app/main.py all --mode fast
```

После запуска:

- SQLite: `data/news.sqlite3`
- Digest: `output/digest_YYYY-MM-DD.md`

## Commands

```bash
docker compose run --rm app python app/main.py collect
docker compose run --rm app python app/main.py report
docker compose run --rm app python app/main.py all
```

- `collect`: собирает RSS/GDELT, дедуплицирует, классифицирует и сохраняет записи.
- `report`: строит Markdown digest из сохранённых записей.
- `all`: делает оба шага.

## Modes

```bash
docker compose run --rm app python app/main.py all --mode fast
docker compose run --rm app python app/main.py all --mode normal
```

- `fast`: RSS only, default.
- `normal`: RSS + GDELT.

## GUI

Small local GUI runs behind an optional profile:

```bash
docker compose --profile gui up gui
```

Open `http://localhost:8000`. The GUI can run `collect`, `report` or `all`, choose `fast`/`normal`, show command logs and display the latest digest. It does not start Ollama unless you also run the Ollama profile.

## Sources

Активные RSS источники лежат в `sources.json`: White House, Defense.gov, UN News, Kremlin, BBC World, Al Jazeera, The Guardian World, Deutsche Welle, France 24, плюс GDELT config.

Отключённые кандидаты вынесены в `sources.disabled.json`, чтобы основной список оставался коротким.

## Optional Ollama

Ollama выключен по умолчанию:

```env
USE_OLLAMA=false
OLLAMA_URL=http://ollama:11434
OLLAMA_MODEL=qwen2.5:3b
OLLAMA_TIMEOUT=180
```

Запуск Ollama container:

```bash
docker compose --profile ollama up -d ollama
```

Model pull:

```bash
docker compose --profile ollama --profile setup run --rm ollama-pull
```

Report через Ollama:

```bash
docker compose --profile ollama run --rm -e USE_OLLAMA=true app python app/main.py report --mode fast
```

Если Ollama недоступен, приложение пишет один warning и использует fallback-шаблоны. Модель хранится в Docker volume `ollama_data`; первый download может быть большим, особенно на Mac.

`docker-compose.gpu.yml` оставлен только для будущего ПК с NVIDIA. Нужны NVIDIA driver и NVIDIA Container Toolkit:

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml --profile ollama up -d ollama
```

## GDELT 429

Если GDELT вернул `429 Too Many Requests`, collector ждёт `retry_delay_seconds`, делает один повтор и при повторном 429 пропускает query. RSS-сбор и report продолжаются.

Что можно сделать:

- запустить позже;
- уменьшить `gdelt.queries`;
- уменьшить `gdelt.maxrecords`;
- увеличить `gdelt.delay_seconds`;
- использовать `--mode fast`.

## Manual Review

Черновики не являются готовыми публикациями. Перед публикацией откройте `output/digest_YYYY-MM-DD.md`, проверьте ссылки, даты, имена, цифры и формулировки. Добавляйте собственный анализ только после ручной проверки фактов.
