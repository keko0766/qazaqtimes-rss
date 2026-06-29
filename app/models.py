from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class NewsItem:
    title: str
    url: str
    source: str = ""
    published_at: str = ""
    summary: str = ""
    tags: list[str] = field(default_factory=list)
    importance: int = 0
    source_score: int = 0
    relevance_score: int = 0
    final_score: int = 0

    def to_dict(self) -> dict:
        return asdict(self)
