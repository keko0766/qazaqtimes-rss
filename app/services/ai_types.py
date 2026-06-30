from __future__ import annotations

from dataclasses import dataclass


AI_ARTICLE_JSON_FIELDS = ("lead", "what_happened", "why_important", "what_next")

BAD_KAZAKH_PHRASES = frozenset(
    {
        "ұшқындар",
        "ғарыштық атқару",
        "шексіз күндері",
        "түштік оқуалар",
        "сейфендик",
        "дүйнөнде шайык",
        "тархыт",
        "көркөмлер",
        "текшеруунда",
        "айта алыш",
        "пайдалуулар тарабып",
        "күн күн жақсы",
        "мада рүсі",
        "қоргондасыз",
        "жашкылыктар",
    }
)

MIN_EVENT_KEYWORD_OVERLAP = 2


@dataclass
class AITextResult:
    provider: str
    model: str = ""
    text: str | None = None
    raw_response: str = ""
    finish_reason: str | None = None
    done_reason: str | None = None
    ollama_available: bool | None = None
    error_reason: str | None = None
    error: str | None = None

    @property
    def mode(self) -> str:
        return self.provider if self.text and not self.error_reason else "fallback"
