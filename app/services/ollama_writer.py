from __future__ import annotations

import os

import requests

from app.services.ai_types import AITextResult


DEFAULT_OLLAMA_URL = "http://ollama:11434"
DEFAULT_OLLAMA_MODEL = "gpt-oss:20b"
DEFAULT_OLLAMA_TIMEOUT = 180

ARTICLE_JSON_OPTIONS = {
    "temperature": 0.2,
    "top_p": 0.8,
    "repeat_penalty": 1.2,
    "num_predict": 700,
}

_ollama_unavailable_logged = False
_ollama_available_cache: bool | None = None


def use_ollama() -> bool:
    return os.getenv("USE_OLLAMA", "false").strip().lower() in {"1", "true", "yes", "on"}


def generate_draft(cluster: dict) -> str | None:
    prompt = build_prompt(cluster)
    return generate_text(prompt, "мақала жобасын генерациялау")


def generate_text(prompt: str, task_name: str = "мәтін генерациялау") -> str | None:
    result = generate_text_result(prompt, task_name)
    return result.text if result.text and not result.error_reason else None


def generate_text_result(prompt: str, task_name: str = "мәтін генерациялау") -> AITextResult:
    global _ollama_available_cache
    model = os.getenv("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL)
    if not ollama_available():
        return AITextResult(
            provider="ollama",
            model=model,
            ollama_available=False,
            error_reason="ollama_not_ready",
        )

    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": ARTICLE_JSON_OPTIONS,
    }
    base_url = os.getenv("OLLAMA_URL", DEFAULT_OLLAMA_URL).rstrip("/")
    timeout = ollama_timeout()

    try:
        response = requests.post(
            f"{base_url}/api/generate",
            json=payload,
            timeout=timeout,
        )
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError) as exc:
        log_ollama_unavailable(f"{task_name} сәтсіз: {exc}")
        _ollama_available_cache = False
        return AITextResult(
            provider="ollama",
            model=model,
            ollama_available=False,
            error_reason="ollama_not_ready",
            error=str(exc),
        )

    raw_response = str(data.get("response", ""))
    finish_reason = data.get("finish_reason")
    done_reason = data.get("done_reason")
    error_reason = None
    if done_reason == "length" or finish_reason == "length":
        error_reason = "finish_reason_length"
    elif not raw_response.strip():
        error_reason = "empty_response"
    return AITextResult(
        provider="ollama",
        model=model,
        text=raw_response.strip() or None,
        raw_response=raw_response,
        finish_reason=str(finish_reason) if finish_reason else None,
        done_reason=str(done_reason) if done_reason else None,
        ollama_available=True,
        error_reason=error_reason,
    )


def ollama_available() -> bool:
    global _ollama_available_cache
    if _ollama_available_cache is not None:
        return _ollama_available_cache

    base_url = os.getenv("OLLAMA_URL", DEFAULT_OLLAMA_URL).rstrip("/")
    model = os.getenv("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL)
    try:
        response = requests.get(
            f"{base_url}/api/tags",
            timeout=min(ollama_timeout(), 10),
        )
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError) as exc:
        log_ollama_unavailable(f"алдын ала тексеру сәтсіз: {exc}")
        _ollama_available_cache = False
        return False
    if not has_ollama_model(data, model):
        log_ollama_unavailable(f"модель табылмады: {model}")
        _ollama_available_cache = False
        return False
    _ollama_available_cache = True
    return True


def has_ollama_model(data: dict, model: str) -> bool:
    wanted = model.lower()
    for item in data.get("models", []):
        name = str(item.get("name") or item.get("model") or "").lower()
        if name == wanted or name.startswith(f"{wanted}@"):
            return True
    return False


def log_ollama_unavailable(message: str) -> None:
    global _ollama_unavailable_logged
    if _ollama_unavailable_logged:
        return
    print(f"[ollama] қолжетімсіз; резерв шаблондар қолданылады ({message})")
    _ollama_unavailable_logged = True


def ollama_timeout() -> int:
    try:
        return int(os.getenv("OLLAMA_TIMEOUT", str(DEFAULT_OLLAMA_TIMEOUT)))
    except ValueError as exc:
        print(f"[ollama] OLLAMA_TIMEOUT қате; {DEFAULT_OLLAMA_TIMEOUT} қолданылады: {exc}")
        return DEFAULT_OLLAMA_TIMEOUT


def build_prompt(cluster: dict) -> str:
    links = [
        f"- {link.get('source', 'source')}: {link.get('title', 'Untitled')} — {link.get('url', '')}"
        for link in cluster.get("links", [])[:5]
        if link.get("url")
    ]
    sources = ", ".join(cluster.get("sources", [])[:5])
    tags = ", ".join(cluster.get("tags", []))

    return f"""Сен қазақ тілінде аналитикалық мақала жобасын жазасың.

Тек төмендегі event cluster деректерін қолдан:

Тақырып: {cluster.get("title", "")}
Түйін: {cluster.get("summary", "")}
Тегтер: {tags}
Дереккөздер: {sources}
Сілтемелер:
{chr(10).join(links)}

Ережелер:
- Факт, есім, сан, цитата немесе деталь ойдан шығарма.
- Дереккөз мәтінін сөзбе-сөз көшірме.
- Мақалалардың толық мәтінін жүктеме және қайталап берме.
- Ақпарат аз болса, сақ тұжырым қолдан.
- Өз сөзіңмен жаз.
- Соңында жоғарыдағы тізімнен дереккөздерді сілтемелерімен міндетті түрде қос.
- "Тақырып" сөзін сол күйі қалдырма: # белгісінен кейін қысқа нақты тақырып жаз.

Құрылым:

# [қысқа тақырып]

Лид

Контекст

Неге маңызды

Әрі қарай не күту керек

Дереккөздер
"""
