from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Callable

import requests


OLLAMA_URL = "http://127.0.0.1:11434"
DEFAULT_MODEL = "gpt-oss:20b"
DOWNLOAD_URL = "https://ollama.com/download"
_managed_process: subprocess.Popen[str] | None = None

ProgressCallback = Callable[[dict], None]


def find_ollama_binary() -> str | None:
    candidates = [
        shutil.which("ollama"),
        "/Applications/Ollama.app/Contents/Resources/ollama",
        "/opt/homebrew/bin/ollama",
        "/usr/local/bin/ollama",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    if Path("/Applications/Ollama.app").exists():
        return "/Applications/Ollama.app"
    return None


def is_ollama_running() -> bool:
    try:
        response = requests.get(f"{OLLAMA_URL}/api/tags", timeout=2)
        return response.ok
    except requests.RequestException:
        return False


def start_ollama() -> bool:
    global _managed_process
    if is_ollama_running():
        return True

    binary = find_ollama_binary()
    if not binary:
        return False

    try:
        if binary.endswith(".app"):
            subprocess.Popen(["open", "-a", "Ollama"])
        else:
            _managed_process = subprocess.Popen(
                [binary, "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
            )
    except OSError:
        try:
            subprocess.Popen(["open", "-a", "Ollama"])
        except OSError:
            return False

    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if is_ollama_running():
            return True
        time.sleep(1)
    return False


def is_model_installed(model: str) -> bool:
    try:
        response = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError):
        return False
    wanted = model.lower()
    for item in data.get("models", []):
        name = str(item.get("name") or item.get("model") or "").lower()
        if name == wanted or name.startswith(f"{wanted}@"):
            return True
    return False


def pull_model(model: str, progress_callback: ProgressCallback | None = None) -> bool:
    binary = find_ollama_binary()
    if not binary or binary.endswith(".app"):
        _emit(progress_callback, "error", 0, "Ollama command табылмады", model, error="ollama_binary_missing")
        return False

    _emit(progress_callback, "pulling", 0, "Модель жүктеліп жатыр", model)
    try:
        process = subprocess.Popen(
            [binary, "pull", model],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
    except OSError as exc:
        _emit(progress_callback, "error", 0, "Модель жүктеу басталмады", model, error=str(exc))
        return False

    deadline = time.monotonic() + float(os.getenv("OLLAMA_PULL_TIMEOUT_SECONDS", "7200"))
    last_text = "Модель жүктеліп жатыр"
    assert process.stdout is not None
    for line in process.stdout:
        if time.monotonic() > deadline:
            process.terminate()
            _emit(progress_callback, "error", 0, "Модель жүктеу уақыты бітті", model, error="timeout")
            return False
        percent, text = parse_pull_progress(line)
        last_text = text or last_text
        _emit(progress_callback, "pulling", percent, last_text, model)

    returncode = process.wait(timeout=5)
    if returncode == 0 and is_model_installed(model):
        _emit(progress_callback, "ready", 100, "Ollama дайын", model)
        return True
    _emit(progress_callback, "error", 0, "Модель жүктелмеді", model, error=f"ollama pull exited {returncode}")
    return False


def ensure_ollama_ready(progress_callback: ProgressCallback | None = None) -> bool:
    model = os.getenv("OLLAMA_MODEL", DEFAULT_MODEL)
    if not find_ollama_binary():
        _emit(
            progress_callback,
            "missing",
            0,
            "Ollama орнатылмаған. ИИ үшін Ollama қажет.",
            model,
            error="ollama_not_installed",
        )
        return False

    _emit(progress_callback, "starting", 5, "Ollama тексеріліп жатыр", model)
    if not is_ollama_running() and not start_ollama():
        _emit(progress_callback, "error", 0, "Ollama іске қосылмады", model, error="ollama_start_failed")
        return False

    if is_model_installed(model):
        _emit(progress_callback, "ready", 100, "Ollama дайын", model)
        return True

    return pull_model(model, progress_callback)


def stop_managed_ollama() -> None:
    global _managed_process
    process = _managed_process
    _managed_process = None
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()


def parse_pull_progress(line: str) -> tuple[int, str]:
    stripped = line.strip()
    if not stripped:
        return 0, "Модель жүктеліп жатыр"
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        return 0, stripped

    status = str(payload.get("status") or "Модель жүктеліп жатыр")
    total = payload.get("total")
    completed = payload.get("completed")
    if isinstance(total, (int, float)) and total > 0 and isinstance(completed, (int, float)):
        percent = max(0, min(99, int((completed / total) * 100)))
        return percent, status
    if status.lower() in {"success", "pulling manifest", "verifying sha256 digest", "writing manifest"}:
        return 99, status
    return 0, status


def _emit(
    callback: ProgressCallback | None,
    state: str,
    percent: int,
    text: str,
    model: str,
    *,
    error: str = "",
) -> None:
    if callback is None:
        return
    callback(
        {
            "state": state,
            "percent": percent,
            "text": text,
            "message": text,
            "model": model,
            "error": error,
            "updated_at": time.time(),
        }
    )
