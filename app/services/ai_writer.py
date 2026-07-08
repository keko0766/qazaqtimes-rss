from __future__ import annotations

import os

from app.services.ai_types import AITextResult
from app.services import ollama_writer


def generate_article_text(prompt: str, stage: str = "article") -> AITextResult:
    provider = selected_provider()
    if provider == "ollama":
        return ollama_writer.generate_text_result(prompt, stage=stage)
    return AITextResult(provider=provider, error_reason="provider_disabled")


def selected_provider() -> str:
    provider = os.getenv("AI_PROVIDER", "none").strip().lower()
    if provider == "none":
        return "none"
    if provider == "ollama":
        return provider
    return "none"
