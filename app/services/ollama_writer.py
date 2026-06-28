from __future__ import annotations

import os

import requests


DEFAULT_OLLAMA_URL = "http://host.docker.internal:11434"
DEFAULT_OLLAMA_MODEL = "qwen2.5:7b"
DEFAULT_OLLAMA_TIMEOUT = 120


def use_ollama() -> bool:
    return os.getenv("USE_OLLAMA", "false").strip().lower() in {"1", "true", "yes", "on"}


def generate_draft(cluster: dict) -> str | None:
    prompt = build_prompt(cluster)
    payload = {
        "model": os.getenv("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL),
        "prompt": prompt,
        "stream": False,
    }
    base_url = os.getenv("OLLAMA_URL", DEFAULT_OLLAMA_URL).rstrip("/")
    timeout = int(os.getenv("OLLAMA_TIMEOUT", str(DEFAULT_OLLAMA_TIMEOUT)))

    try:
        response = requests.post(
            f"{base_url}/api/generate",
            json=payload,
            timeout=timeout,
        )
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError) as exc:
        print(f"[ollama] draft generation failed: {exc}")
        return None

    text = str(data.get("response", "")).strip()
    return text or None


def build_prompt(cluster: dict) -> str:
    links = [
        f"- {link.get('source', 'source')}: {link.get('title', 'Untitled')} — {link.get('url', '')}"
        for link in cluster.get("links", [])[:5]
        if link.get("url")
    ]
    sources = ", ".join(cluster.get("sources", [])[:5])
    tags = ", ".join(cluster.get("tags", []))

    return f"""Ты пишешь черновик аналитической статьи на русском языке.

Используй только данные event cluster ниже:

Title: {cluster.get("title", "")}
Summary: {cluster.get("summary", "")}
Tags: {tags}
Sources: {sources}
Links:
{chr(10).join(links)}

Правила:
- Не выдумывай факты, имена, цифры, цитаты или детали.
- Не копируй текст источников дословно.
- Не загружай и не пересказывай полный текст статей.
- Если информации мало, используй осторожные формулировки.
- Пиши своими словами.
- В конце обязательно добавь источники со ссылками из списка выше.

Структура:

# Тақырып

Лид

Контекст

Неге маңызды

Әрі қарай не күту керек

Дереккөздер
"""
