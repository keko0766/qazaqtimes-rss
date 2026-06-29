from __future__ import annotations

import os

import requests


DEFAULT_OLLAMA_URL = "http://ollama:11434"
DEFAULT_OLLAMA_MODEL = "qwen2.5:3b"
DEFAULT_OLLAMA_TIMEOUT = 180

_ollama_unavailable_logged = False
_ollama_available_cache: bool | None = None


def use_ollama() -> bool:
    return os.getenv("USE_OLLAMA", "false").strip().lower() in {"1", "true", "yes", "on"}


def generate_draft(cluster: dict) -> str | None:
    global _ollama_available_cache
    if not ollama_available():
        return None

    prompt = build_prompt(cluster)
    payload = {
        "model": os.getenv("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL),
        "prompt": prompt,
        "stream": False,
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
        log_ollama_unavailable(f"мақала жобасын генерациялау сәтсіз: {exc}")
        _ollama_available_cache = False
        return None

    text = str(data.get("response", "")).strip()
    return text or None


def ollama_available() -> bool:
    global _ollama_available_cache
    if _ollama_available_cache is not None:
        return _ollama_available_cache

    base_url = os.getenv("OLLAMA_URL", DEFAULT_OLLAMA_URL).rstrip("/")
    try:
        response = requests.get(
            f"{base_url}/api/tags",
            timeout=min(ollama_timeout(), 10),
        )
        response.raise_for_status()
        response.json()
    except (requests.RequestException, ValueError) as exc:
        log_ollama_unavailable(f"алдын ала тексеру сәтсіз: {exc}")
        _ollama_available_cache = False
        return False
    _ollama_available_cache = True
    return True


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
