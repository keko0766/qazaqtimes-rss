from __future__ import annotations

from app.services.relevance import keyword_in_text


def is_usa_iran(tags: set[str]) -> bool:
    return bool(
        {"usa", "iran"} <= tags
        or {"iran", "nuclear"} <= tags
        or {"iran", "sanctions"} <= tags
        or {"iran", "hormuz"} <= tags
        or ({"usa", "middle_east"} <= tags and bool(tags & {"military", "sanctions", "nuclear"}))
    )


def is_china_taiwan(tags: set[str], text: str) -> bool:
    if not (tags & {"china", "taiwan"}):
        return False
    if "taiwan" in tags:
        return True
    qualifiers = {
        "military",
        "sanctions",
        "export control",
        "semiconductor",
        "chip",
        "security",
        "taiwan strait",
    }
    return bool(tags & {"military", "sanctions"}) or any(
        keyword_in_text(text, word) for word in qualifiers
    )


def is_weak_gdelt_summary(summary: str | None) -> bool:
    if not summary:
        return True
    return summary.strip().lower().startswith("found by gdelt query")
