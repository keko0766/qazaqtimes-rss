from __future__ import annotations

from app.services.relevance import has_china_influence_signal, keyword_in_text


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


def is_china_influence(tags: set[str], text: str) -> bool:
    has_china = bool(tags & {"china", "taiwan", "belt_and_road"}) or any(
        keyword_in_text(text, word) for word in ("china", "chinese", "beijing", "taiwan", "taipei")
    )
    if not has_china:
        return False
    if tags & {"china_influence", "china_aggression", "grey_zone", "south_china_sea", "belt_and_road"}:
        return has_china_influence_signal(text)
    if not tags & {"china", "taiwan", "belt_and_road"}:
        return False
    return has_china_influence_signal(text)


def is_kazakhstan_domestic(tags: set[str], text: str) -> bool:
    if "kazakhstan_politics" in tags:
        return True
    if "kazakhstan" not in tags:
        return False
    markers = {
        "tokayev",
        "government",
        "parliament",
        "mazhilis",
        "majilis",
        "senate",
        "cabinet",
        "domestic politics",
        "political reform",
    }
    return any(keyword_in_text(text, word) for word in markers)


def is_weak_gdelt_summary(summary: str | None) -> bool:
    if not summary:
        return True
    return summary.strip().lower().startswith("found by gdelt query")
