from __future__ import annotations

import re

from app.utils.text import normalize_spaces
from app.services.relevance import IMPORTANT_TAGS, is_relevant_item
from app.services.source_quality import source_score_for_item
from app.services.topic_score import score_item_core_topic


TAG_KEYWORDS = {
    "usa": ["usa", "u.s.", "us ", "united states", "america", "american", "washington", "white house"],
    "iran": ["iran", "iranian", "tehran"],
    "russia": ["russia", "russian", "moscow", "kremlin"],
    "ukraine": ["ukraine", "ukrainian", "kyiv", "kiev", "zelensky"],
    "china": ["china", "chinese", "beijing", "xi jinping"],
    "nato": ["nato", "alliance"],
    "eu": ["eu ", "european union", "european council", "brussels", "consilium"],
    "sanctions": ["sanction", "sanctions", "embargo", "blacklist"],
    "war": ["war", "missile", "invasion", "troops", "strike", "airstrike", "battle", "frontline"],
    "nuclear": ["nuclear", "uranium", "iaea", "reactor"],
    "middle_east": ["middle east", "gaza", "israel", "israeli", "palestinian", "lebanon", "syria", "yemen", "hormuz"],
    "taiwan": ["taiwan", "taipei", "taiwan strait"],
    "diplomacy": ["diplomacy", "talks", "minister", "foreign minister", "president", "agreement", "summit", "negotiation", "united nations", "security council"],
    "military": ["military", "defense", "troops", "missile", "strike", "army", "navy", "air force"],
    "israel": ["israel", "israeli"],
    "gaza": ["gaza"],
    "lebanon": ["lebanon", "lebanese"],
    "syria": ["syria", "syrian"],
    "hormuz": ["hormuz"],
    "trade": ["trade agreement", "free trade", "tariff", "export control", "semiconductor", "chip", "chips"],
}

IMPORTANCE_3 = [
    "attack",
    "missile",
    "killed",
    "invasion",
    "nuclear",
    "sanctions",
    "ceasefire",
    "troops",
    "strike",
]

IMPORTANCE_2 = [
    "diplomacy",
    "talks",
    "minister",
    "president",
    "warning",
    "agreement",
]


def classify_item(item: dict) -> dict:
    text = normalize_spaces(
        f"{item.get('title', '')} {item.get('summary', '')} {item.get('source', '')}"
    ).lower()
    item["tags"] = find_tags(text)
    item["importance"] = find_importance(text)
    item["source_score"] = source_score_for_item(item)
    item["relevance_score"] = find_relevance_score(item)
    item["final_score"] = find_final_score(item)
    item = score_item_core_topic(item)
    return item


def classify_items(items: list[dict]) -> list[dict]:
    return [classify_item(item) for item in items]


def find_tags(text: str) -> list[str]:
    tags: list[str] = []
    for tag, keywords in TAG_KEYWORDS.items():
        if any(keyword_in_text(text, keyword) for keyword in keywords):
            tags.append(tag)
    return tags


def find_importance(text: str) -> int:
    if any(keyword_in_text(text, word) for word in IMPORTANCE_3):
        return 3
    if any(keyword_in_text(text, word) for word in IMPORTANCE_2):
        return 2
    return 1


def keyword_in_text(text: str, keyword: str) -> bool:
    clean_keyword = keyword.strip().lower()
    if not clean_keyword:
        return False
    if clean_keyword in {"u.s.", "us ", "eu "}:
        clean_keyword = clean_keyword.strip()
    pattern = r"(?<![a-zа-я0-9])" + re.escape(clean_keyword) + r"(?![a-zа-я0-9])"
    return re.search(pattern, text, flags=re.IGNORECASE) is not None


def find_relevance_score(item: dict) -> int:
    if not is_relevant_item(item):
        return 0
    tags = set(item.get("tags") or [])
    important_tag_count = len(tags & IMPORTANT_TAGS)
    return 2 + min(important_tag_count, 4)


def find_final_score(item: dict) -> int:
    importance = int(item.get("importance", 0))
    source_score = int(item.get("source_score", 0))
    relevance_score = int(item.get("relevance_score", 0))
    return importance * 10 + source_score + relevance_score
