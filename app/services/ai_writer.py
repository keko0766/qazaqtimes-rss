from __future__ import annotations

import os

from app.services.ai_types import AITextResult
from app.services import lmstudio_writer, ollama_writer


def generate_article_text(prompt: str) -> AITextResult:
    provider = selected_provider()
    if provider == "lmstudio":
        return lmstudio_writer.generate_text_result(prompt)
    if provider == "ollama":
        return ollama_writer.generate_text_result(prompt)
    return AITextResult(provider=provider, error_reason="provider_disabled")


def selected_provider() -> str:
    provider = os.getenv("AI_PROVIDER", "none").strip().lower()
    if provider == "none":
        return "none"
    if provider in {"ollama", "lmstudio"}:
        return provider
    if ollama_writer.use_ollama():
        return "ollama"
    return "none"
