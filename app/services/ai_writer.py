from __future__ import annotations

import os

from app.services import lmstudio_writer, ollama_writer


def generate_article_text(prompt: str) -> tuple[str | None, str]:
    provider = selected_provider()
    if provider == "lmstudio":
        text = lmstudio_writer.generate_text(prompt)
        return (text, "lmstudio") if text else (None, "fallback")
    if provider == "ollama":
        text = ollama_writer.generate_text(prompt)
        return (text, "ollama") if text else (None, "fallback")
    return None, "fallback"


def selected_provider() -> str:
    provider = os.getenv("AI_PROVIDER", "none").strip().lower()
    if provider in {"ollama", "lmstudio"}:
        return provider
    if ollama_writer.use_ollama():
        return "ollama"
    return "none"
