from __future__ import annotations

import os
import traceback

import requests

from app.services.ai_types import AITextResult


DEFAULT_LMSTUDIO_URL = "http://host.docker.internal:1234/v1"
DEFAULT_LMSTUDIO_MODEL = "openai/gpt-oss-20b"
DEFAULT_LMSTUDIO_TIMEOUT = 180
SYSTEM_PROMPT = "Сен қазақ тілінде қысқа, нақты, фактіні бұрмаламайтын жаңалық мақаласын жазатын редакторсың."

_available_cache: bool | None = None
_unavailable_logged = False


def is_available() -> bool:
    global _available_cache
    if _available_cache is not None:
        return _available_cache

    try:
        response = requests.get(
            f"{base_url()}/models",
            timeout=5,
        )
        response.raise_for_status()
        response.json()
    except (requests.RequestException, ValueError) as exc:
        log_unavailable(exc)
        _available_cache = False
        return False

    _available_cache = True
    return True


def generate_text(prompt: str) -> str | None:
    result = generate_text_result(prompt)
    return result.text if result.text and not result.error_reason else None


def generate_text_result(prompt: str) -> AITextResult:
    global _available_cache
    model = os.getenv("LMSTUDIO_MODEL", DEFAULT_LMSTUDIO_MODEL)
    if not is_available():
        return AITextResult(provider="lmstudio", model=model, error_reason="lmstudio_not_ready")

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.3,
        "max_tokens": 900,
        "stream": False,
    }

    try:
        response = requests.post(
            f"{base_url()}/chat/completions",
            json=payload,
            timeout=timeout(),
        )
        response.raise_for_status()
        data = response.json()
        choice = data["choices"][0]
        finish_reason = choice.get("finish_reason")
        text = str(choice["message"]["content"])
    except (KeyError, IndexError, TypeError, requests.RequestException, ValueError) as exc:
        log_unavailable(exc)
        _available_cache = False
        return AITextResult(
            provider="lmstudio",
            model=model,
            error_reason="lmstudio_not_ready",
            error=str(exc),
        )

    error_reason = None
    if finish_reason == "length":
        error_reason = "finish_reason_length"
    elif not text.strip():
        error_reason = "empty_response"
    return AITextResult(
        provider="lmstudio",
        model=model,
        text=text.strip() or None,
        raw_response=text,
        finish_reason=str(finish_reason) if finish_reason else None,
        error_reason=error_reason,
    )


def base_url() -> str:
    return os.getenv("LMSTUDIO_URL", DEFAULT_LMSTUDIO_URL).rstrip("/")


def timeout() -> int:
    try:
        return int(os.getenv("LMSTUDIO_TIMEOUT", str(DEFAULT_LMSTUDIO_TIMEOUT)))
    except ValueError as exc:
        if debug_ai():
            print(f"[ai-debug] LMSTUDIO_TIMEOUT қате: {exc}")
        return DEFAULT_LMSTUDIO_TIMEOUT


def log_unavailable(exc: Exception) -> None:
    global _unavailable_logged
    if not _unavailable_logged:
        print("[ai] LM Studio қолжетімсіз, резерв шаблон қолданылады")
        _unavailable_logged = True
    if debug_ai():
        print("[ai-debug] LM Studio exception:")
        traceback.print_exception(type(exc), exc, exc.__traceback__)


def debug_ai() -> bool:
    return os.getenv("DEBUG_AI", "false").strip().lower() in {"1", "true", "yes", "on"}
