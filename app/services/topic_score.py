from __future__ import annotations

from app.services.relevance import item_text, keyword_in_text


CHINA_TAIWAN_QUALIFIERS = {
    "taiwan",
    "military",
    "sanctions",
    "trade",
    "semiconductor",
    "south china sea",
    "defense",
    "navy",
    "chip",
    "export control",
}

CHINA_US_CONFLICT_WORDS = {
    "sanctions",
    "tariff",
    "export control",
    "semiconductor",
    "chip",
    "defense",
    "navy",
    "military",
    "security",
    "tensions",
}

GEOPOLITICAL_TAGS = {
    "usa",
    "iran",
    "russia",
    "ukraine",
    "china",
    "nato",
    "eu",
    "middle_east",
    "taiwan",
    "nuclear",
    "sanctions",
    "war",
    "diplomacy",
    "military",
    "israel",
    "gaza",
    "lebanon",
    "syria",
    "hormuz",
}


def score_item_core_topic(item: dict) -> dict:
    tags = set(item.get("tags") or [])
    text = item_text(item)
    core_topics = find_core_topics(tags, text)
    item["core_topics"] = core_topics
    item["core_topic_score"] = core_topic_score(core_topics, tags, text)
    return item


def score_items_core_topic(items: list[dict]) -> list[dict]:
    return [score_item_core_topic(item) for item in items]


def find_core_topics(tags: set[str], text: str) -> list[str]:
    topics = []
    if is_usa_iran(tags):
        topics.append("usa_iran")
    if {"russia", "ukraine"} <= tags:
        topics.append("russia_ukraine")
    if is_china_taiwan(tags, text):
        topics.append("china_taiwan")
    if {"nato", "ukraine"} <= tags:
        topics.append("nato_ukraine")
    if is_middle_east_security(tags):
        topics.append("middle_east_security")
    if {"iran", "nuclear"} <= tags:
        topics.append("iran_nuclear")
    if is_sanctions_core(tags):
        topics.append("sanctions")
    if is_war_escalation(tags):
        topics.append("war_escalation")
    return topics


def core_topic_score(core_topics: list[str], tags: set[str], text: str) -> int:
    if core_topics:
        return 3
    if is_important_international(tags, text):
        return 2
    if is_secondary_international(tags, text):
        return 1
    return 0


def is_usa_iran(tags: set[str]) -> bool:
    return (
        {"usa", "iran"} <= tags
        or {"usa", "sanctions"} <= tags
        or {"usa", "military"} <= tags and bool(tags & {"iran", "middle_east", "hormuz"})
        or {"usa", "nuclear"} <= tags and bool(tags & {"iran", "middle_east"})
        or {"usa", "middle_east"} <= tags
        or {"iran", "nuclear"} <= tags
        or {"iran", "sanctions"} <= tags
        or {"iran", "hormuz"} <= tags
    )


def is_china_taiwan(tags: set[str], text: str) -> bool:
    if not (tags & {"china", "taiwan"}):
        return False
    if "taiwan" in tags:
        return True
    if tags & {"military", "sanctions"}:
        return True
    if "usa" in tags and any(keyword_in_text(text, keyword) for keyword in CHINA_US_CONFLICT_WORDS):
        return True
    return any(keyword_in_text(text, keyword) for keyword in CHINA_TAIWAN_QUALIFIERS)


def is_middle_east_security(tags: set[str]) -> bool:
    region_tags = {"middle_east", "iran", "israel", "gaza", "lebanon", "syria", "hormuz"}
    security_tags = {"war", "military", "sanctions", "nuclear", "diplomacy"}
    return bool(tags & region_tags) and bool(tags & security_tags)


def is_sanctions_core(tags: set[str]) -> bool:
    return "sanctions" in tags and bool(tags & {"usa", "iran", "russia", "ukraine", "china", "nato", "eu"})


def is_war_escalation(tags: set[str]) -> bool:
    if not (tags & {"war", "military"}):
        return False
    if tags & {"ukraine", "iran", "middle_east", "israel", "gaza", "lebanon", "syria", "hormuz", "taiwan"}:
        return True
    return {"russia", "ukraine"} <= tags


def is_important_international(tags: set[str], text: str) -> bool:
    if tags & {"nato", "eu", "nuclear", "sanctions"}:
        return True
    important_tag_context = {
        "ukraine",
        "iran",
        "middle_east",
        "taiwan",
        "nato",
        "eu",
        "israel",
        "gaza",
        "lebanon",
        "syria",
        "hormuz",
    }
    if tags & {"diplomacy", "military"} and tags & important_tag_context:
        return True
    important_words = {"foreign minister", "security council", "ceasefire", "summit", "export control"}
    return any(keyword_in_text(text, keyword) for keyword in important_words)


def is_secondary_international(tags: set[str], text: str) -> bool:
    if tags & GEOPOLITICAL_TAGS:
        return True
    secondary_words = {"usaid", "trade agreement", "free trade", "protests", "government"}
    return any(keyword_in_text(text, keyword) for keyword in secondary_words)


def is_weak_gdelt_summary(summary: str | None) -> bool:
    if not summary:
        return True
    return summary.strip().lower().startswith("found by gdelt query")
