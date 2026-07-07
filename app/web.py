from __future__ import annotations

import json
import logging
import os
import platform
import re
import subprocess
import sys
import threading
import time
import webbrowser
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import requests


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.utils.datetime import today_str
from app.utils.paths import (
    configure_environment_defaults,
    configure_logging,
    data_dir,
    ollama_status_path,
    output_dir,
)
from app.main import PipelineCancelled, run_article, run_collect, run_daily_workflow, run_report
from app.services import ollama_writer
from app.services.ollama_manager import DOWNLOAD_URL

configure_environment_defaults()

OUTPUT_DIR = output_dir()
DATA_DIR = data_dir()
OLLAMA_STATUS_PATH = ollama_status_path()
AI_STATUS_PATH = DATA_DIR / "ai_status.json"
COMMANDS = {"collect", "report", "article", "all"}
PRESETS = {"daily_articles"}
MODES = {"fast", "normal"}
AI_PROVIDERS = {"none", "ollama", "lmstudio"}
LMSTUDIO_DEFAULT_URL = "http://host.docker.internal:1234/v1"
LMSTUDIO_DEFAULT_MODEL = "openai/gpt-oss-20b"
OLLAMA_DEFAULT_URL = "http://127.0.0.1:11434"
OLLAMA_DEFAULT_MODEL = "gpt-oss:20b"
LOGGER = logging.getLogger(__name__)
_LMSTUDIO_STATUS = {"checked_at": 0.0, "available": False}
_OLLAMA_STATUS = {
    "checked_at": 0.0,
    "available": False,
    "reachable": False,
    "model_present": False,
    "error": "",
}


class JobState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.running = False
        self.command = ""
        self.preset = ""
        self.mode = "fast"
        self.limit = 5
        self.ai_provider = "ollama"
        self.started_at = ""
        self.finished_at = ""
        self.returncode: int | None = None
        self.output: list[str] = []
        self.cancel_event: threading.Event | None = None
        self.stop_requested = False
        self.user_message = ""

    def snapshot(self) -> dict:
        selected_provider = self.ai_provider
        ollama_state = ollama_status_snapshot(refresh=selected_provider == "ollama")
        lmstudio_ready = lmstudio_available(refresh=selected_provider == "lmstudio")
        with self.lock:
            ai_status = {} if self.running else latest_ai_status()
            return {
                "running": self.running,
                "command": self.command,
                "preset": self.preset,
                "mode": self.mode,
                "limit": self.limit,
                "ai_provider": self.ai_provider,
                "started_at": self.started_at,
                "finished_at": self.finished_at,
                "returncode": self.returncode,
                "stopped": self.stop_requested and self.returncode not in (None, 0),
                "job_status": self.status_label(),
                "status_label": self.status_label(),
                "message": self.status_message(),
                "output": self.output[-240:],
                "today_folder": today_article_folder_label(),
                "latest_digest": latest_digest(include_content=False),
                "latest_articles": today_articles(limit=5),
                "lmstudio_fallback": self.has_lmstudio_fallback(),
                "ollama_fallback": self.has_ollama_fallback(),
                "ollama_available": ollama_state["available"],
                "ollama_loading": ollama_state["loading"],
                "ollama_status": ollama_state["status"],
                "ollama_status_message": ollama_state["message"],
                "ollama_error": ollama_state["error"],
                "ollama_state": ollama_state["state"],
                "ollama_progress": ollama_state["percent"],
                "ollama_missing": ollama_state["state"] == "missing",
                "ollama_download_url": DOWNLOAD_URL,
                "lmstudio_available": lmstudio_ready,
                "current_model": current_model(selected_provider),
                "last_ai_provider": ai_status.get("provider", ""),
                "last_ai_model": ai_status.get("model", ""),
                "last_ai_used_fallback": ai_status.get("used_fallback"),
                "last_ai_reject_reason": ai_status.get("reject_reason"),
                "last_ai_json_parsed": ai_status.get("json_parsed"),
                "last_ai_bad_phrase": ai_status.get("bad_phrase_detected"),
                "last_ai_event_keyword_overlap": ai_status.get("event_keyword_overlap"),
                "last_ai_quality_error_sample": ai_status.get("quality_error_sample"),
                "last_ai_debug_folder": ai_status.get("debug_folder", ""),
                "last_ai_raw_preview": ai_status.get("raw_preview", ""),
                "last_ai_rendered_preview": ai_status.get("rendered_preview", ""),
            }

    def status_label(self) -> str:
        if self.running:
            return "Жұмыс істеп жатыр"
        if self.stop_requested and self.returncode not in (None, 0):
            return "Тоқтатылды"
        if self.returncode == 0:
            return "Аяқталды"
        if self.finished_at:
            return "Қате болды"
        return "Дайын"

    def status_message(self) -> str:
        if self.user_message:
            return self.user_message
        if self.running:
            return "Жаңалықтар өңделіп жатыр. Журналдан барысын көре аласыз."
        if self.returncode == 0:
            return build_run_summary(self.output) or "Дайын. Соңғы нәтижелер төменде көрсетіледі."
        if self.stop_requested and self.returncode not in (None, 0):
            return "Жұмыс тоқтатылды."
        if self.finished_at:
            return "Қате болды. Толық ақпарат журналда."
        return "Бір батырмамен бүгінгі мақалаларды жасаңыз."

    def has_lmstudio_fallback(self) -> bool:
        return any("LM Studio қолжетімсіз" in line for line in self.output)

    def has_ollama_fallback(self) -> bool:
        return any("Ollama дайын емес" in line or "[ollama] қолжетімсіз" in line for line in self.output)

    def select_ai_provider(self, ai_provider: str) -> None:
        with self.lock:
            self.ai_provider = ai_provider

    def start_command(self, command: str, mode: str, ai_provider: str, limit: int = 5) -> bool:
        if command not in COMMANDS:
            return False
        return self.start(command, "", mode, ai_provider, limit)

    def start_preset(self, preset: str, mode: str, ai_provider: str, limit: int = 5) -> bool:
        if preset not in PRESETS:
            return False
        if preset == "daily_articles":
            return self.start("daily_articles", preset, mode, ai_provider, limit)
        return False

    def start(
        self,
        command: str,
        preset: str,
        mode: str,
        ai_provider: str,
        limit: int,
    ) -> bool:
        with self.lock:
            if self.running:
                return False
            self.running = True
            self.command = command
            self.preset = preset
            self.mode = mode
            self.limit = limit
            self.ai_provider = ai_provider
            self.started_at = now_iso()
            self.finished_at = ""
            self.returncode = None
            self.output = []
            self.cancel_event = threading.Event()
            self.stop_requested = False
            self.user_message = ""

        thread = threading.Thread(
            target=self._run_job,
            args=(command, preset, mode, ai_provider, limit, self.cancel_event),
            daemon=True,
        )
        thread.start()
        return True

    def _run_job(
        self,
        command: str,
        preset: str,
        mode: str,
        ai_provider: str,
        limit: int,
        cancel_event: threading.Event,
    ) -> None:
        final_returncode = 0
        ollama_fallback_reported = False

        try:
            if ai_provider == "ollama" and not ollama_is_ready():
                self.append("[gui] Ollama дайын емес. Резерв шаблон қолданылды.")
                ollama_fallback_reported = True
            with patched_environment(ai_environment(ai_provider)):
                reset_ollama_cache()
                with redirect_stdout(JobOutputStream(self)), redirect_stderr(JobOutputStream(self)):
                    if preset == "daily_articles":
                        print("[gui] Бүгінгі мақалалар жасалып жатыр")
                        run_daily_workflow(
                            mode=mode,
                            limit=limit,
                            ai_provider=ai_provider,
                            cancel_event=cancel_event,
                        )
                    elif command == "collect":
                        print("[gui] жаңалық жинау басталды")
                        run_collect(mode=mode, cancel_event=cancel_event)
                    elif command == "report":
                        print("[gui] дайджест жасау басталды")
                        run_report(mode=mode, cancel_event=cancel_event)
                    elif command == "article":
                        print("[gui] мақала жасау басталды")
                        run_article(
                            mode=mode,
                            limit=limit,
                            replace_today=True,
                            cancel_event=cancel_event,
                        )
                    elif command == "all":
                        print("[gui] жинау және дайджест басталды")
                        run_collect(mode=mode, cancel_event=cancel_event)
                        run_report(mode=mode, cancel_event=cancel_event)
                    else:
                        final_returncode = 1
        except PipelineCancelled:
            final_returncode = 130
        except Exception:  # noqa: BLE001 - GUI must never crash the server.
            LOGGER.exception("GUI job failed")
            self.append("[gui] Қате болды. Толық ақпарат журналда.")
            final_returncode = 1

        with self.lock:
            self.running = False
            self.returncode = final_returncode
            self.finished_at = now_iso()
            self.cancel_event = None
            summary = build_run_summary(self.output)
            if self.has_lmstudio_fallback():
                summary = f"{summary}\nLM Studio табылмады, резерв шаблон қолданылды." if summary else "LM Studio табылмады, резерв шаблон қолданылды."
            if self.has_ollama_fallback():
                summary = f"{summary}\nOllama дайын емес. Резерв шаблон қолданылды." if summary else "Ollama дайын емес. Резерв шаблон қолданылды."
            if self.stop_requested and final_returncode == 130:
                summary = "Жұмыс тоқтатылды."
            self.user_message = summary

    def stop(self) -> bool:
        with self.lock:
            if not self.running:
                return False
            self.stop_requested = True
            cancel_event = self.cancel_event
            self.output.append("[gui] тоқтату сұралды")

        if cancel_event is not None:
            cancel_event.set()
        return True

    def append(self, line: str) -> None:
        with self.lock:
            self.output.append(line)


JOB = JobState()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/":
            self.send_html(INDEX_HTML)
            return
        if path == "/api/status":
            self.send_json(JOB.snapshot())
            return
        if path == "/api/digest":
            self.send_json(latest_digest(include_content=True))
            return
        self.send_error(404)

    def do_POST(self) -> None:
        if not self.is_local_request():
            self.send_json({"ok": False, "error": "Тек local request рұқсат"}, status=403)
            return
        if not self.is_allowed_origin():
            self.send_json({"ok": False, "error": "Origin қате"}, status=403)
            return
        path = urlparse(self.path).path
        if path == "/api/stop":
            if not JOB.stop():
                self.send_json({"ok": False, "error": "Іске қосылған тапсырма жоқ"}, status=409)
                return
            self.send_json({"ok": True})
            return
        if path == "/api/open-folder":
            self.send_json(open_today_folder())
            return
        if path == "/api/open-ollama-download":
            webbrowser.open(DOWNLOAD_URL)
            self.send_json({"ok": True, "url": DOWNLOAD_URL})
            return
        if path == "/api/ai-provider":
            self.handle_ai_provider()
            return
        if path == "/api/run-preset":
            self.handle_run_preset()
            return
        if path == "/api/run":
            self.handle_run()
            return
        self.send_error(404)

    def handle_run_preset(self) -> None:
        payload = self.read_json()
        if payload is None:
            self.send_json({"ok": False, "error": "JSON payload қате"}, status=400)
            return
        preset = str(payload.get("preset", "")).strip()
        mode = parse_mode(payload.get("mode", "fast"))
        limit = parse_limit(payload.get("limit", 5))
        ai_provider = parse_ai_provider(payload.get("ai_provider", "ollama"), payload.get("use_ollama", False))
        if preset not in PRESETS:
            self.send_json({"ok": False, "error": "Preset қате"}, status=400)
            return
        if mode is None:
            self.send_json({"ok": False, "error": "Режим қате"}, status=400)
            return
        if limit is None:
            self.send_json({"ok": False, "error": "Мақала саны қате"}, status=400)
            return
        if ai_provider is None:
            self.send_json({"ok": False, "error": "ИИ режимі қате"}, status=400)
            return
        if not JOB.start_preset(preset, mode, ai_provider, limit=limit):
            self.send_json({"ok": False, "error": "Тапсырма қазір орындалып жатыр"}, status=409)
            return
        self.send_json({"ok": True})

    def handle_run(self) -> None:
        payload = self.read_json()
        if payload is None:
            self.send_json({"ok": False, "error": "JSON payload қате"}, status=400)
            return
        command = str(payload.get("command", "")).strip()
        mode = parse_mode(payload.get("mode", "fast"))
        limit = parse_limit(payload.get("limit", 5))
        ai_provider = parse_ai_provider(payload.get("ai_provider", "ollama"), payload.get("use_ollama", False))
        if command not in COMMANDS:
            self.send_json({"ok": False, "error": "Команда қате"}, status=400)
            return
        if mode is None:
            self.send_json({"ok": False, "error": "Режим қате"}, status=400)
            return
        if limit is None:
            self.send_json({"ok": False, "error": "Мақала саны қате"}, status=400)
            return
        if ai_provider is None:
            self.send_json({"ok": False, "error": "ИИ режимі қате"}, status=400)
            return
        if not JOB.start_command(command, mode, ai_provider, limit=limit):
            self.send_json({"ok": False, "error": "Тапсырма қазір орындалып жатыр"}, status=409)
            return
        self.send_json({"ok": True})

    def handle_ai_provider(self) -> None:
        payload = self.read_json()
        if payload is None:
            self.send_json({"ok": False, "error": "JSON payload қате"}, status=400)
            return
        ai_provider = parse_ai_provider(payload.get("ai_provider", "ollama"), payload.get("use_ollama", False))
        if ai_provider is None:
            self.send_json({"ok": False, "error": "ИИ режимі қате"}, status=400)
            return
        JOB.select_ai_provider(ai_provider)
        self.send_json({"ok": True, "ai_provider": ai_provider})

    def read_json(self) -> dict | None:
        try:
            length = int(self.headers.get("content-length", "0"))
        except ValueError:
            return None
        content_type = self.headers.get("content-type", "")
        if "application/json" not in content_type.lower():
            return None
        if length <= 0 or length > 65536:
            return None
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    def is_local_request(self) -> bool:
        host = self.client_address[0]
        return host in {"127.0.0.1", "::1"} or host.startswith("172.") or host.startswith("192.168.") or host.startswith("10.")

    def is_allowed_origin(self) -> bool:
        origin = self.headers.get("origin") or self.headers.get("referer")
        if not origin:
            return True
        host = urlparse(origin).hostname
        return host in {"localhost", "127.0.0.1", "::1"}

    def send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_html(self, html: str) -> None:
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        LOGGER.info("%s %s", self.address_string(), format % args)


class JobOutputStream:
    def __init__(self, job: JobState) -> None:
        self.job = job
        self.buffer = ""

    def write(self, text: str) -> int:
        self.buffer += text
        while "\n" in self.buffer:
            line, self.buffer = self.buffer.split("\n", 1)
            if line:
                self.job.append(line.rstrip())
        return len(text)

    def flush(self) -> None:
        if self.buffer:
            self.job.append(self.buffer.rstrip())
            self.buffer = ""


@contextmanager
def patched_environment(values: dict[str, str]):
    previous = {key: os.environ.get(key) for key in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def reset_ollama_cache() -> None:
    ollama_writer._ollama_available_cache = None  # noqa: SLF001
    ollama_writer._ollama_unavailable_logged = False  # noqa: SLF001


def ai_environment(provider: str) -> dict[str, str]:
    if provider == "ollama":
        return {"AI_PROVIDER": "ollama", "USE_OLLAMA": "true"}
    if provider == "lmstudio":
        return {
            "AI_PROVIDER": "lmstudio",
            "USE_OLLAMA": "false",
            "LMSTUDIO_URL": "http://host.docker.internal:1234/v1",
        }
    return {"AI_PROVIDER": "none", "USE_OLLAMA": "false"}


def parse_mode(value: object) -> str | None:
    mode = str(value or "fast").strip().lower()
    return mode if mode in MODES else None


def parse_ai_provider(value: object, use_ollama: object = False) -> str | None:
    provider = str(value or "").strip().lower()
    if provider in AI_PROVIDERS:
        return provider
    if not provider:
        return "ollama" if bool(use_ollama) else "none"
    return None


def parse_limit(value: object) -> int | None:
    try:
        limit = int(value)
    except (TypeError, ValueError):
        return None
    if 1 <= limit <= 10:
        return limit
    return None


def lmstudio_available(refresh: bool = False) -> bool:
    now = time.time()
    if not refresh and now - float(_LMSTUDIO_STATUS["checked_at"]) < 5:
        return bool(_LMSTUDIO_STATUS["available"])
    try:
        response = requests.get(f"{lmstudio_url()}/models", timeout=1.5)
        ready = response.ok
    except requests.RequestException:
        ready = False
    _LMSTUDIO_STATUS["checked_at"] = now
    _LMSTUDIO_STATUS["available"] = ready
    return ready


def lmstudio_url() -> str:
    return os.getenv("LMSTUDIO_URL", LMSTUDIO_DEFAULT_URL).rstrip("/")


def current_model(provider: str) -> str:
    if provider == "ollama":
        return ollama_model()
    if provider == "lmstudio":
        return os.getenv("LMSTUDIO_MODEL", LMSTUDIO_DEFAULT_MODEL)
    return ""


def ollama_status_snapshot(refresh: bool = False) -> dict:
    status_file = read_ollama_status_file()
    model_state = ollama_model_state() if refresh else dict(_OLLAMA_STATUS)
    available = bool(model_state["available"])
    state = str(status_file.get("state") or "").lower()
    message = str(status_file.get("message") or status_file.get("text") or "")
    error = str(status_file.get("error") or "")
    percent = int(status_file.get("percent") or 0)

    if available:
        return {
            "available": True,
            "loading": False,
            "status": "Дайын",
            "message": "Ollama дайын",
            "error": "",
            "state": "ready",
            "percent": 100,
        }
    if state in {"starting", "pulling", "running"}:
        return {
            "available": False,
            "loading": True,
            "status": "Дайындалып жатыр",
            "message": message or "Ollama дайындалып жатыр",
            "error": "",
            "state": state,
            "percent": percent,
        }
    if state == "ready":
        return {
            "available": False,
            "loading": False,
            "status": "Қате",
            "message": "Ollama жауап бермеді",
            "error": "Model status file ready, but /api/tags unavailable",
            "state": "error",
            "percent": 0,
        }
    if model_state["reachable"] and not model_state["model_present"]:
        model = ollama_model()
        return {
            "available": False,
            "loading": False,
            "status": "Қате",
            "message": f"Ollama моделі табылмады: {model}",
            "error": model_state["error"] or f"Model not found: {model}",
            "state": "error",
            "percent": 0,
        }
    if state == "missing":
        return {
            "available": False,
            "loading": False,
            "status": "Ollama орнатылмаған",
            "message": message or "Ollama орнатылмаған. ИИ үшін Ollama қажет.",
            "error": error,
            "state": "missing",
            "percent": 0,
        }
    if state == "error":
        return {
            "available": False,
            "loading": False,
            "status": "Қате",
            "message": message or "Ollama қате",
            "error": error,
            "state": "error",
            "percent": 0,
        }
    return {
        "available": False,
        "loading": False,
        "status": "Қосылмаған",
        "message": "Ollama қосылмаған",
        "error": "",
        "state": "",
        "percent": 0,
    }


def read_ollama_status_file() -> dict:
    if not OLLAMA_STATUS_PATH.exists():
        return {}
    try:
        data = json.loads(OLLAMA_STATUS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"state": "error", "message": "Ollama status оқылмады"}
    return data if isinstance(data, dict) else {}


def latest_ai_status() -> dict:
    for path in [AI_STATUS_PATH, OUTPUT_DIR / "debug_ai" / today_str() / "latest_status.json"]:
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict):
            return data
    return {}


def ollama_is_ready() -> bool:
    return ollama_model_available()


def ollama_model_available() -> bool:
    return bool(ollama_model_state()["available"])


def ollama_model_state() -> dict:
    now = time.time()
    if now - float(_OLLAMA_STATUS["checked_at"]) < 5:
        return dict(_OLLAMA_STATUS)

    model = ollama_model()
    state = {
        "checked_at": now,
        "available": False,
        "reachable": False,
        "model_present": False,
        "error": "",
    }
    try:
        response = requests.get(f"{ollama_url()}/api/tags", timeout=2)
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError) as exc:
        state["error"] = str(exc)
        _OLLAMA_STATUS.update(state)
        return dict(_OLLAMA_STATUS)

    state["reachable"] = True
    wanted = model.lower()
    for item in data.get("models", []):
        name = str(item.get("name") or item.get("model") or "").lower()
        if name == wanted or name.startswith(f"{wanted}@"):
            state["available"] = True
            state["model_present"] = True
            break
    if not state["model_present"]:
        state["error"] = f"Model not found: {model}"
    _OLLAMA_STATUS.update(state)
    return dict(_OLLAMA_STATUS)


def ollama_url() -> str:
    return os.getenv("OLLAMA_URL", OLLAMA_DEFAULT_URL).rstrip("/")


def ollama_model() -> str:
    return os.getenv("OLLAMA_MODEL", OLLAMA_DEFAULT_MODEL)


def today_article_folder() -> Path:
    return OUTPUT_DIR / "articles" / today_str() / "latest"


def today_article_folder_label() -> str:
    return display_path(today_article_folder())


def latest_digest_path() -> Path | None:
    if not OUTPUT_DIR.exists():
        return None
    digests = sorted(OUTPUT_DIR.glob("digest_*.md"), key=lambda path: path.stat().st_mtime, reverse=True)
    return digests[0] if digests else None


def latest_digest(include_content: bool = False) -> dict:
    digest = latest_digest_path()
    if not digest:
        return {"path": "", "preview": ""}
    text = digest.read_text(encoding="utf-8", errors="replace") if include_content else read_text_preview(digest, 800)
    payload = {
        "path": display_path(digest),
        "preview": text[:800],
    }
    if include_content:
        payload["content"] = text
    return payload


def today_articles(limit: int = 5) -> list[dict]:
    folder = today_article_folder()
    if not folder.exists():
        return []
    articles = sorted(folder.glob("*.md"), key=lambda path: path.stat().st_mtime, reverse=True)[:limit]
    return [article_payload(path) for path in articles]


def article_payload(path: Path) -> dict:
    text = read_text_preview(path, 5000)
    body = strip_front_matter(text)
    metadata = article_front_matter(text)
    return {
        "path": display_path(path),
        "title": metadata.get("title") or article_title(text, body),
        "slot": metadata.get("slot", ""),
        "slot_label": metadata.get("slot_label", ""),
        "preview": markdown_preview(body, 700),
    }


def markdown_preview(text: str, limit: int) -> str:
    preview = text.strip()
    if len(preview) <= limit:
        return preview
    return preview[:limit].rstrip() + "..."


def strip_front_matter(text: str) -> str:
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            return parts[2].strip()
    return text.strip()


def article_title(raw: str, body: str) -> str:
    for line in raw.splitlines():
        if line.startswith("title:"):
            return line.split(":", 1)[1].strip().strip('"')
    for line in body.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return "Мақала"


def article_front_matter(raw: str) -> dict[str, str]:
    if not raw.startswith("---"):
        return {}
    parts = raw.split("---", 2)
    if len(parts) != 3:
        return {}
    metadata: dict[str, str] = {}
    for line in parts[1].splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        metadata[key.strip()] = value.strip().strip('"')
    return metadata


def open_today_folder() -> dict:
    folder = today_article_folder()
    folder.mkdir(parents=True, exist_ok=True)
    opener = "open" if platform.system() == "Darwin" else "xdg-open"
    try:
        subprocess.Popen([opener, str(folder)], cwd=PROJECT_ROOT)
    except OSError:
        return {
            "ok": False,
            "path": display_path(folder),
            "error": "Папканы автоматты ашу мүмкін болмады. Жолды қолмен ашыңыз.",
        }
    return {"ok": True, "path": display_path(folder)}


def display_path(path: Path) -> str:
    for root in [PROJECT_ROOT, OUTPUT_DIR.parent, DATA_DIR.parent]:
        try:
            return str(path.relative_to(root))
        except ValueError:
            continue
    return str(path)


def read_text_preview(path: Path, limit: int) -> str:
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        return handle.read(limit)


def build_run_summary(output: list[str]) -> str:
    metrics = {
        "rss": find_last_number(output, r"жиналған RSS жазбалар: (\d+)"),
        "unique": find_last_number(output, r"бірегей кандидаттар: (\d+)"),
        "new": find_last_number(output, r"жаңа жазбалар: (\d+)"),
        "selected": find_last_number(output, r"мақалаға таңдалған оқиғалар: (\d+)"),
        "saved": find_last_number(output, r"сақталған мақалалар: (\d+)"),
    }
    if not any(value is not None for value in metrics.values()):
        return ""

    lines = []
    if metrics["rss"] is not None:
        lines.append(f"Жиналған RSS жазбалар: {metrics['rss']}")
    if metrics["unique"] is not None:
        lines.append(f"Бірегей жаңалықтар: {metrics['unique']}")
    if metrics["new"] is not None:
        lines.append(f"Жаңа жазбалар: {metrics['new']}")
    if metrics["selected"] is not None:
        lines.append(f"Мақалаға таңдалған оқиғалар: {metrics['selected']}")
    if metrics["saved"] is not None:
        lines.append(f"Сақталған мақалалар: {metrics['saved']}")
    if metrics["new"] == 0:
        lines.append("Жаңа жазба табылмады, мақалалар бұрын сақталған соңғы релевант оқиғалардан жасалды.")
    return "\n".join(lines)


def find_last_number(lines: list[str], pattern: str) -> int | None:
    compiled = re.compile(pattern)
    for line in reversed(lines):
        match = compiled.search(line)
        if match:
            return int(match.group(1))
    return None


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


INDEX_HTML = r"""<!doctype html>
<html lang="kk">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>GeoNewsBot</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f6f7f9;
      --panel: #ffffff;
      --ink: #17202a;
      --muted: #667085;
      --line: #d9dee7;
      --accent: #126b5f;
      --accent-2: #284b8f;
      --danger: #a43f3f;
      --soft: #eef6f4;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font: 14px/1.45 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      padding: 14px 18px;
      border-bottom: 1px solid var(--line);
      background: var(--panel);
      position: sticky;
      top: 0;
      z-index: 2;
    }
    h1 { margin: 0; font-size: 18px; letter-spacing: 0; }
    main {
      display: grid;
      grid-template-columns: minmax(300px, 380px) minmax(0, 1fr);
      min-height: calc(100vh - 58px);
    }
    aside {
      border-right: 1px solid var(--line);
      background: var(--panel);
      padding: 16px;
    }
    section { padding: 16px; min-width: 0; }
    h2 { margin: 0 0 12px; font-size: 18px; letter-spacing: 0; }
    .hero {
      padding: 14px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: var(--soft);
      margin-bottom: 14px;
    }
    .hero p { margin: 0 0 12px; color: var(--muted); }
    .field { margin-bottom: 12px; }
    label { display: block; color: var(--muted); font-size: 12px; margin-bottom: 6px; }
    select, input, button {
      width: 100%;
      min-height: 38px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fff;
      color: var(--ink);
      font: inherit;
    }
    button {
      cursor: pointer;
      font-weight: 650;
      background: var(--accent);
      border-color: var(--accent);
      color: #fff;
    }
    button.primary {
      min-height: 52px;
      font-size: 16px;
      background: var(--accent);
      border-color: var(--accent);
    }
    button.secondary { background: var(--accent-2); border-color: var(--accent-2); }
    button.danger { background: var(--danger); border-color: var(--danger); }
    button.ghost { background: #fff; color: var(--ink); border-color: var(--line); }
    button:disabled { opacity: .55; cursor: wait; }
    .actions { display: grid; gap: 8px; margin-top: 12px; }
    .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
    details {
      margin-top: 14px;
      padding: 10px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fbfcfe;
    }
    summary { cursor: pointer; font-weight: 700; }
    .status {
      margin-top: 14px;
      padding: 12px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fbfcfe;
    }
    .status strong { display: block; margin-bottom: 4px; }
    #meta { white-space: pre-line; }
    .hint {
      display: none;
      margin-top: 8px;
      padding: 8px;
      border-radius: 6px;
      background: #fff7e6;
      color: #6b4a00;
      font-size: 12px;
    }
    .notice {
      display: none;
      margin-top: 10px;
      padding: 8px;
      border-radius: 6px;
      background: #fff7e6;
      color: #6b4a00;
    }
    .ai-state {
      margin-top: 8px;
      padding: 8px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fff;
      color: var(--muted);
      font-size: 12px;
    }
    .progress {
      display: block;
      width: 100%;
      height: 10px;
      margin-top: 8px;
      border: 0;
      border-radius: 999px;
      background: #e6ebf2;
      overflow: hidden;
    }
    .progress::-webkit-progress-bar { background: #e6ebf2; border-radius: 999px; }
    .progress::-webkit-progress-value { background: var(--accent); border-radius: 999px; }
    .progress::-moz-progress-bar { background: var(--accent); border-radius: 999px; }
    .download-link {
      display: none;
      margin-top: 8px;
      background: #fff;
      color: var(--ink);
      border-color: var(--line);
    }
    .diag-grid {
      display: grid;
      grid-template-columns: 1fr;
      gap: 6px;
      margin-top: 10px;
      color: var(--muted);
      font-size: 12px;
    }
    .diag-grid div { overflow-wrap: anywhere; }
    .raw-preview {
      margin: 8px 0 0;
      white-space: pre-wrap;
      word-break: break-word;
      max-height: 160px;
      overflow: auto;
      padding: 8px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fff;
      font: 12px/1.45 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    }
    .muted { color: var(--muted); }
    .results-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      margin-bottom: 12px;
    }
    .cards {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
      gap: 10px;
    }
    .card {
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fff;
      padding: 12px;
      min-width: 0;
    }
    .card h3 {
      margin: 0 0 8px;
      font-size: 15px;
      letter-spacing: 0;
    }
    .path {
      overflow-wrap: anywhere;
      color: var(--muted);
      font-size: 12px;
      margin-bottom: 8px;
    }
    .slot-label {
      display: inline-flex;
      align-items: center;
      max-width: 100%;
      margin-bottom: 8px;
      padding: 3px 7px;
      border: 1px solid #b7d5cf;
      border-radius: 999px;
      background: #eef6f4;
      color: var(--accent);
      font-size: 12px;
      font-weight: 700;
      overflow-wrap: anywhere;
    }
    .preview {
      margin: 0 0 10px;
      color: #354052;
      font-size: 13px;
      white-space: pre-wrap;
    }
    .card-actions {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 8px;
    }
    .digest {
      margin-top: 14px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fff;
      padding: 12px;
    }
    .digest pre {
      margin: 8px 0 0;
      white-space: pre-wrap;
      word-break: break-word;
      max-height: 180px;
      overflow: auto;
      font: 13px/1.5 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    }
    .tabs {
      display: flex;
      gap: 8px;
      margin-top: 16px;
      margin-bottom: 12px;
    }
    .tabs button {
      width: auto;
      min-width: 92px;
      background: #fff;
      color: var(--ink);
      border-color: var(--line);
    }
    .tabs button.active { border-color: var(--accent); color: var(--accent); }
    #viewer {
      margin: 0;
      white-space: pre-wrap;
      word-break: break-word;
      overflow: auto;
      min-height: 360px;
      max-height: 520px;
      padding: 14px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fff;
      font: 13px/1.5 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    }
    .error { color: var(--danger); }
    @media (max-width: 860px) {
      main { grid-template-columns: 1fr; }
      aside { border-right: 0; border-bottom: 1px solid var(--line); }
      .results-head { align-items: stretch; flex-direction: column; }
    }
  </style>
</head>
<body>
  <header>
    <h1>GeoNewsBot</h1>
    <span id="latest" class="muted">дайджест: -</span>
  </header>
  <main>
    <aside>
      <div class="hero">
        <h2>Бүгінгі мақалалар</h2>
        <p>Жаңалықтарды жинап, дайджест жасап, 5 қазақша Markdown мақала дайындайды.</p>
        <button id="daily" class="primary">Бүгінгі мақалаларды жасау</button>
      </div>
      <div class="actions">
        <div class="grid-2">
          <button id="collect" class="secondary">Тек жаңалық жинау</button>
          <button id="report" class="secondary">Дайджест жасау</button>
        </div>
        <button id="article" class="secondary">Мақала жасау</button>
        <button id="stop" class="danger" disabled>Тоқтату</button>
      </div>
      <details>
        <summary>Кеңейтілген баптаулар</summary>
        <div class="field">
          <label for="mode">Режим</label>
          <select id="mode">
            <option value="fast">fast</option>
            <option value="normal">normal</option>
          </select>
        </div>
        <div class="field">
          <label for="limit">Мақала саны</label>
          <input id="limit" type="number" min="1" max="10" value="5">
        </div>
        <div class="field">
          <label for="aiProvider">ИИ режимі</label>
          <select id="aiProvider">
            <option value="none">Өшірулі</option>
            <option value="ollama" selected>Ollama</option>
          </select>
          <div id="aiState" class="ai-state">ИИ: Қосылмаған</div>
          <progress id="modelProgress" class="progress" max="100" value="0"></progress>
          <button id="ollamaDownload" class="download-link">Ollama жүктеу бетін ашу</button>
        </div>
      </details>
      <div class="status">
        <strong id="state">Дайын</strong>
        <div id="meta" class="muted">Бір батырмамен бүгінгі мақалаларды жасаңыз.</div>
        <div id="ollamaNotice" class="notice">Ollama дайын емес. Резерв шаблон қолданылды.</div>
      </div>
      <details>
        <summary>ИИ диагностика</summary>
        <div class="diag-grid">
          <div><strong>ИИ режимі:</strong> <span id="diagProvider">-</span></div>
          <div><strong>Ollama статусы:</strong> <span id="diagOllama">-</span></div>
          <div><strong>Соңғы генерация:</strong> <span id="diagMode">-</span></div>
          <div><strong>Қабылданбау себебі:</strong> <span id="diagReject">-</span></div>
          <div><strong>Сапа белгісі:</strong> <span id="diagBadPhrase">-</span></div>
          <div><strong>Оқиға сәйкестігі:</strong> <span id="diagEventOverlap">-</span></div>
          <div><strong>JSON оқылды:</strong> <span id="diagJsonParsed">-</span></div>
          <div><strong>Модель:</strong> <span id="diagModel">-</span></div>
          <div><strong>Диагностика папкасы:</strong> <span id="diagFolder">-</span></div>
        </div>
        <pre id="diagRaw" class="raw-preview">Raw response preview тек DEBUG_AI_ARTICLES=true болса көрінеді.</pre>
        <pre id="diagRendered" class="raw-preview">Rendered preview тек DEBUG_AI_ARTICLES=true болса көрінеді.</pre>
      </details>
    </aside>
    <section>
      <div class="results-head">
        <div>
          <h2>Бүгінгі мақалалар</h2>
          <div id="folder" class="muted">output/articles/YYYY-MM-DD/</div>
        </div>
        <button id="openFolder" class="ghost">Папканы ашу</button>
      </div>
      <div id="articles" class="cards"></div>
      <div class="digest">
        <strong>Соңғы дайджест</strong>
        <div id="digestPath" class="path">-</div>
        <pre id="digestPreview">Дайджест әзірге жоқ.</pre>
      </div>
      <div class="tabs">
        <button id="tabLog" class="active">Журнал</button>
      </div>
      <pre id="viewer">Журнал әзірге жоқ.</pre>
    </section>
  </main>
  <script>
    const state = document.querySelector("#state");
    const meta = document.querySelector("#meta");
    const latest = document.querySelector("#latest");
    const folder = document.querySelector("#folder");
    const articles = document.querySelector("#articles");
    const viewer = document.querySelector("#viewer");
    const digestPath = document.querySelector("#digestPath");
    const digestPreview = document.querySelector("#digestPreview");
    const ollamaNotice = document.querySelector("#ollamaNotice");
    const aiState = document.querySelector("#aiState");
    const modelProgress = document.querySelector("#modelProgress");
    const ollamaDownload = document.querySelector("#ollamaDownload");
    const daily = document.querySelector("#daily");
    const collect = document.querySelector("#collect");
    const report = document.querySelector("#report");
    const article = document.querySelector("#article");
    const stop = document.querySelector("#stop");
    const openFolder = document.querySelector("#openFolder");
    const mode = document.querySelector("#mode");
    const limit = document.querySelector("#limit");
    const aiProvider = document.querySelector("#aiProvider");
    const diagProvider = document.querySelector("#diagProvider");
    const diagOllama = document.querySelector("#diagOllama");
    const diagMode = document.querySelector("#diagMode");
    const diagReject = document.querySelector("#diagReject");
    const diagBadPhrase = document.querySelector("#diagBadPhrase");
    const diagEventOverlap = document.querySelector("#diagEventOverlap");
    const diagJsonParsed = document.querySelector("#diagJsonParsed");
    const diagModel = document.querySelector("#diagModel");
    const diagFolder = document.querySelector("#diagFolder");
    const diagRaw = document.querySelector("#diagRaw");
    const diagRendered = document.querySelector("#diagRendered");

    async function getJSON(url, options) {
      const response = await fetch(url, options);
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Сұрау сәтсіз аяқталды");
      return data;
    }

    function payload(extra) {
      return JSON.stringify({
        mode: mode.value,
        limit: limit.value || 5,
        ai_provider: aiProvider.value,
        ...extra
      });
    }

    async function runPreset() {
      await getJSON("/api/run-preset", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: payload({preset: "daily_articles"})
      });
      await refreshAll();
    }

    async function runCommand(command) {
      await getJSON("/api/run", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: payload({command})
      });
      await refreshAll();
    }

    async function refreshStatus() {
      const status = await getJSON("/api/status");
      state.textContent = status.status_label || "Дайын";
      meta.textContent = status.message || "";
      latest.textContent = `дайджест: ${(status.latest_digest && status.latest_digest.path) || "-"}`;
      folder.textContent = status.today_folder || "output/articles/YYYY-MM-DD/";
      stop.disabled = !status.running;
      [daily, collect, report, article].forEach((button) => button.disabled = status.running);
      viewer.textContent = (status.output || []).join("\n") || "Журнал әзірге жоқ.";
      ollamaNotice.style.display = status.ollama_fallback ? "block" : "none";
      renderAiStatus(status);
      renderAiDiagnostics(status);
      renderArticles(status.latest_articles || []);
      renderDigest(status.latest_digest || {});
      return status;
    }

    async function refreshAll() {
      try {
        await refreshStatus();
      } catch (error) {
        meta.textContent = error.message;
        state.textContent = "Қате болды";
      }
    }

    function renderArticles(items) {
      if (!items.length) {
        articles.innerHTML = `<div class="card"><p class="muted">Әзірге мақала жоқ.</p></div>`;
        return;
      }
      articles.innerHTML = items.map((item, index) => `
        <article class="card">
          <h3>${escapeHTML(item.title || "Мақала")}</h3>
          ${item.slot_label ? `<div class="slot-label">${escapeHTML(item.slot_label)}</div>` : ""}
          <div class="path">${escapeHTML(item.path)}</div>
          <p class="preview">${escapeHTML(item.preview || "")}</p>
          <div class="card-actions">
            <button class="ghost" data-copy="${index}">Көшіру</button>
            <button class="ghost" data-view="${index}">Толық көру</button>
          </div>
        </article>
      `).join("");
      articles.querySelectorAll("[data-copy]").forEach((button) => {
        button.addEventListener("click", async () => {
          const item = items[Number(button.dataset.copy)];
          const slot = item.slot_label ? `${item.slot_label}\n` : "";
          await navigator.clipboard.writeText(`${item.title}\n${slot}${item.path}\n\n${item.preview}`);
          button.textContent = "Көшірілді";
        });
      });
      articles.querySelectorAll("[data-view]").forEach((button) => {
        button.addEventListener("click", () => {
          const item = items[Number(button.dataset.view)];
          const slot = item.slot_label ? `${item.slot_label}\n` : "";
          viewer.textContent = `${item.path}\n${slot}\n${item.preview}`;
          window.scrollTo({top: document.body.scrollHeight, behavior: "smooth"});
        });
      });
    }

    function renderDigest(digest) {
      digestPath.textContent = digest.path || "-";
      digestPreview.textContent = digest.preview || "Дайджест әзірге жоқ.";
    }

    function renderAiStatus(status) {
      if (aiProvider.value === "ollama") {
        const model = status.current_model ? ` · Модель: ${status.current_model}` : "";
        let label = status.ollama_status || "Қосылмаған";
        if (status.ollama_loading) label = "Дайындалып жатыр";
        if (status.ollama_available) label = "Дайын";
        const message = status.ollama_status_message ? ` · ${status.ollama_status_message}` : "";
        aiState.textContent = `Ollama: ${label}${model}${message}`;
        modelProgress.value = status.ollama_available ? 100 : (status.ollama_progress || 0);
        modelProgress.style.display = (status.ollama_loading || status.ollama_available) ? "block" : "none";
        ollamaDownload.style.display = status.ollama_missing ? "block" : "none";
        return;
      }
      aiState.textContent = "ИИ: Қосылмаған";
      modelProgress.style.display = "none";
      ollamaDownload.style.display = "none";
    }

    function renderAiDiagnostics(status) {
      diagProvider.textContent = status.ai_provider || "-";
      const ollamaLabel = status.ollama_available ? "Дайын" : (status.ollama_loading ? "Дайындалып жатыр" : (status.ollama_status || "Қосылмаған"));
      diagOllama.textContent = `${ollamaLabel}${status.ollama_status_message ? ` · ${status.ollama_status_message}` : ""}`;
      if (status.last_ai_used_fallback === true) {
        diagMode.textContent = "fallback";
      } else if (status.last_ai_used_fallback === false) {
        diagMode.textContent = "AI";
      } else {
        diagMode.textContent = "-";
      }
      diagReject.textContent = status.last_ai_reject_reason || "-";
      diagBadPhrase.textContent = status.last_ai_bad_phrase || "-";
      diagEventOverlap.textContent = status.last_ai_event_keyword_overlap ?? "-";
      if (status.last_ai_json_parsed === true) {
        diagJsonParsed.textContent = "true";
      } else if (status.last_ai_json_parsed === false) {
        diagJsonParsed.textContent = "false";
      } else {
        diagJsonParsed.textContent = "-";
      }
      diagModel.textContent = status.last_ai_model || status.current_model || "-";
      diagFolder.textContent = status.last_ai_debug_folder || "output/debug_ai/YYYY-MM-DD/";
      diagRaw.textContent = status.last_ai_raw_preview || "Raw response preview тек DEBUG_AI_ARTICLES=true болса көрінеді.";
      diagRendered.textContent = status.last_ai_rendered_preview || "Rendered preview тек DEBUG_AI_ARTICLES=true болса көрінеді.";
    }

    function escapeHTML(value) {
      return String(value)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
    }

    daily.addEventListener("click", () => runPreset().catch((error) => meta.textContent = error.message));
    collect.addEventListener("click", () => runCommand("collect").catch((error) => meta.textContent = error.message));
    report.addEventListener("click", () => runCommand("report").catch((error) => meta.textContent = error.message));
    article.addEventListener("click", () => runCommand("article").catch((error) => meta.textContent = error.message));
    stop.addEventListener("click", async () => {
      try {
        await getJSON("/api/stop", {method: "POST"});
        await refreshAll();
      } catch (error) {
        meta.textContent = error.message;
      }
    });
    openFolder.addEventListener("click", async () => {
      const result = await getJSON("/api/open-folder", {method: "POST"});
      if (!result.ok) meta.textContent = `${result.error} ${result.path}`;
    });
    ollamaDownload.addEventListener("click", async () => {
      const result = await getJSON("/api/open-ollama-download", {method: "POST"});
      if (result.url) meta.textContent = "Ollama жүктеу беті ашылды.";
    });
    aiProvider.addEventListener("change", async () => {
      try {
        await getJSON("/api/ai-provider", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: payload({})
        });
        await refreshAll();
      } catch (error) {
        meta.textContent = error.message;
      }
    });
    setInterval(refreshAll, 2500);
    refreshAll();
  </script>
</body>
</html>
"""


def create_server(host: str = "127.0.0.1", preferred_port: int = 8000) -> tuple[ThreadingHTTPServer, int]:
    last_error: OSError | None = None
    for port in range(preferred_port, 8011):
        try:
            return ThreadingHTTPServer((host, port), Handler), port
        except OSError as exc:
            last_error = exc
    raise OSError(f"Ports {preferred_port}-8010 are unavailable") from last_error


def main() -> int:
    configure_logging()
    host = os.getenv("GUI_HOST", "127.0.0.1")
    preferred_port = int(os.getenv("GUI_PORT", "8000"))
    server, port = create_server(host, preferred_port)
    LOGGER.info("GUI listening on http://%s:%s", host, port)
    print(f"[gui] listening on http://{host}:{port}")
    try:
        server.serve_forever()
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
