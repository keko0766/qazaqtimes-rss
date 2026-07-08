# GeoNewsBot Developer Guide

GeoNewsBot is now a native macOS app first. The user opens `GeoNewsBot.app`; the app starts the local GUI, checks native Ollama, pulls `gpt-oss:20b` if needed, and runs the existing news pipeline in-process.

## Architecture

Primary entrypoint:

- `app/desktop.py` initializes app paths, logging, GUI server, browser opening, background Ollama setup, and clean shutdown.

Shared pipeline:

- `app/main.py::run_collect(mode)`
- `app/main.py::run_report(mode)`
- `app/main.py::run_article(mode, limit, replace_today)`
- `app/main.py::run_daily_workflow(mode, limit, ai_provider)`

The CLI and GUI both call these functions. Business logic remains in the existing collectors and services: SQLite, RSS/GDELT, classifier/relevance/scoring, clustering, editorial slots, journalist generation, verification/repair/fallback, and report/article writers.

## GUI

`app/web.py` still uses `ThreadingHTTPServer` and `BaseHTTPRequestHandler`; no new web framework was added.

The GUI binds to `127.0.0.1`. The desktop launcher tries ports `8000` through `8010` and opens the selected port. GUI jobs run in background threads and use `threading.Event` cancellation. Cancellation is checked between collection stages, RSS sources, GDELT queries, report generation, each article, and AI generation boundaries.

## Native Ollama

`app/services/ollama_manager.py` owns native Ollama lifecycle:

- `find_ollama_binary()`
- `is_ollama_running()`
- `start_ollama()`
- `is_model_installed(model)`
- `pull_model(model, progress_callback)`
- `ensure_ollama_ready(progress_callback)`
- `stop_managed_ollama()`

Detection checks `ollama` on `PATH`, `/Applications/Ollama.app`, `/Applications/Ollama.app/Contents/Resources/ollama`, `/opt/homebrew/bin/ollama`, and `/usr/local/bin/ollama`. It never uses `shell=True`, never installs Ollama, and never requests admin privileges.

Native defaults:

```env
AI_PROVIDER=ollama
OLLAMA_URL=http://127.0.0.1:11434
OLLAMA_MODEL=gpt-oss:20b
```

Ollama readiness is checked with:

```text
GET http://127.0.0.1:11434/api/tags
```

Model download progress is written to `runtime/ollama_status.json` and shown by the GUI.

## Paths

`app/utils/paths.py` centralizes packaged vs developer paths.

Packaged app data:

```text
~/Library/Application Support/GeoNewsBot/
├── data/news.sqlite3
├── output/
└── runtime/
    ├── app.log
    └── ollama_status.json
```

Developer runs continue to use repo-local `data/` and `output/`.

## Packaging

Build the macOS app:

```bash
./build_macos.sh
```

Output:

```text
dist/GeoNewsBot.app
```

The app bundles source code and `sources.json`. It does not bundle Ollama, `gpt-oss:20b`, SQLite databases, output files, or `.env`.

Useful checks:

```bash
python3 -m compileall app
.venv/bin/python -m app.desktop
./build_macos.sh
open dist/GeoNewsBot.app
```
