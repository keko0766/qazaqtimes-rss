from __future__ import annotations

import re

from app.utils.text import normalize_spaces
from app.services.relevance import IMPORTANT_TAGS, is_relevant_item
from app.services.source_quality import source_score_for_item


TAG_KEYWORDS = {
    "usa": ["usa", "u.s.", "us ", "united states", "america", "american", "washington", "white house"],
    "iran": ["iran", "iranian", "tehran"],
    "russia": ["russia", "russian", "moscow", "kremlin"],
    "ukraine": ["ukraine", "ukrainian", "kyiv", "kiev", "zelensky"],
    "china": ["china", "chinese", "beijing", "xi jinping"],
    "china_influence": [
        "china influence",
        "chinese influence",
        "influence operations",
        "influence operation",
        "economic coercion",
        "coercion",
        "coercive",
        "pressure campaign",
        "belt and road",
        "bri ",
    ],
    "china_aggression": [
        "china aggression",
        "chinese aggression",
        "military pressure",
        "taiwan pressure",
        "coercion",
        "intimidation",
        "harassment",
    ],
    "grey_zone": ["grey zone", "gray zone", "hybrid tactics", "cognitive warfare"],
    "south_china_sea": ["south china sea", "spratly", "paracel", "scarborough shoal", "second thomas shoal"],
    "belt_and_road": ["belt and road", "bri ", "silk road", "china-kazakhstan", "china kazakhstan"],
    "central_asia": ["central asia", "central asian", "kazakhstan", "uzbekistan", "kyrgyzstan", "tajikistan", "turkmenistan"],
    "kazakhstan": ["kazakhstan", "kazakh", "astana", "akorda"],
    "kazakhstan_politics": [
        "kazakhstan domestic politics",
        "tokayev",
        "akorda",
        "kazakh government",
        "kazakhstan government",
        "kazakhstan parliament",
        "mazhilis",
        "majilis",
        "senate of kazakhstan",
        "cabinet",
        "prime minister of kazakhstan",
        "political reform",
    ],
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
    "coercion",
    "grey zone",
    "gray zone",
    "south china sea",
    "tokayev",
    "parliament",
]

IMPORTANCE_2 = [
    "diplomacy",
    "talks",
    "minister",
    "president",
    "warning",
    "agreement",
    "government",
    "parliament",
    "coercion",
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
    return item


def classify_items(items: list[dict]) -> list[dict]:
    return [classify_item(item) for item in items]


def find_tags(text: str) -> list[str]:
    tags: list[str] = []
    for tag, keywords in TAG_KEYWORDS.items():
        if any(keyword_in_text(text, keyword) for keyword in keywords):
            tags.append(tag)
    return refine_tags(tags, text)


def refine_tags(tags: list[str], text: str) -> list[str]:
    tag_set = set(tags)
    china_pressure_tags = {"china_influence", "china_aggression", "grey_zone", "south_china_sea"}
    has_china_context = bool(
        tag_set & {"china", "taiwan", "south_china_sea", "belt_and_road"}
        or keyword_in_text(text, "beijing")
        or keyword_in_text(text, "taipei")
        or keyword_in_text(text, "south china sea")
    )
    if not has_china_context:
        tag_set -= china_pressure_tags
    return [tag for tag in tags if tag in tag_set]


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
