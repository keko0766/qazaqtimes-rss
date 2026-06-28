from __future__ import annotations

import re

from app.services.source_quality import get_domain, is_allowed_gdelt_domain, is_gdelt_item
from app.utils.text import normalize_spaces


IMPORTANT_TAGS = {
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
}

RELEVANCE_KEYWORDS = {
    "sanctions",
    "missile",
    "strike",
    "troops",
    "ceasefire",
    "nuclear",
    "foreign minister",
    "nato",
    "united nations",
    "security council",
    "ukraine",
    "russia",
    "iran",
    "china",
    "taiwan",
    "gaza",
    "israel",
    "lebanon",
    "syria",
    "hormuz",
}

BLACKLIST_KEYWORDS = {
    "sport",
    "sports",
    "celebrity",
    "entertainment",
    "weather",
    "heatwave",
    "swelters",
    "climate change",
    "crash",
    "plane crash",
    "wildfire",
    "crime",
    "accident",
    "music",
    "film",
    "football",
    "tennis",
    "earthquake",
    "shark attack",
    "deface",
    "vandal",
    "cryptographic",
    "cybersecurity",
}

BLACKLIST_EXCEPTIONS = {
    "war",
    "sanctions",
    "government",
    "military",
    "diplomacy",
}


def is_relevant_item(item: dict) -> bool:
    if is_gdelt_item(item) and not is_allowed_gdelt_domain(get_domain(item.get("url", ""))):
        return False

    text = item_text(item)
    tags = set(item.get("tags") or [])
    has_geo_tag = bool(tags & IMPORTANT_TAGS)
    has_geo_keyword = any(keyword_in_text(text, keyword) for keyword in RELEVANCE_KEYWORDS)

    if not has_geo_tag and not has_geo_keyword:
        return False
    if has_blacklisted_topic(text, tags):
        return False
    if is_domestic_noise(text, tags):
        return False
    if is_single_country_admin_noise(text, tags):
        return False
    if is_weak_single_tag_noise(text, tags):
        return False
    return True


def filter_relevant_items(items: list[dict]) -> list[dict]:
    return [item for item in items if is_relevant_item(item)]


def has_blacklisted_topic(text: str, tags: set[str]) -> bool:
    if not any(keyword_in_text(text, keyword) for keyword in BLACKLIST_KEYWORDS):
        return False
    if tags & {"war", "sanctions", "military"}:
        return False
    real_diplomacy = {"talks", "agreement", "ceasefire", "foreign minister", "summit", "negotiation"}
    if "diplomacy" in tags and any(keyword_in_text(text, keyword) for keyword in real_diplomacy):
        return False
    if any(keyword_in_text(text, keyword) for keyword in BLACKLIST_EXCEPTIONS - {"diplomacy"}):
        return False
    return True


def is_domestic_noise(text: str, tags: set[str]) -> bool:
    strong_foreign_tags = {
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
        "israel",
        "gaza",
        "lebanon",
        "syria",
        "hormuz",
    }
    if tags & strong_foreign_tags:
        return False
    domestic_markers = {
        "signed into law",
        "reflecting pool",
        "lincoln memorial",
        "shark attack",
        "cryptographic attacks",
        "cybersecurity",
        "wireless emergency alerts",
    }
    return any(keyword_in_text(text, marker) for marker in domestic_markers)


def is_single_country_admin_noise(text: str, tags: set[str]) -> bool:
    country_admin_tags = {"usa", "russia", "china", "diplomacy", "military"}
    if not tags or not tags <= country_admin_tags:
        return False
    foreign_policy_markers = {
        "foreign",
        "minister",
        "sanctions",
        "war",
        "military",
        "missile",
        "strike",
        "troops",
        "ceasefire",
        "nuclear",
        "agreement",
        "talks",
        "summit",
        "ukraine",
        "iran",
        "taiwan",
        "nato",
        "eu",
        "middle east",
        "gaza",
        "israel",
        "lebanon",
        "syria",
        "hormuz",
        "belarus",
        "venezuela",
    }
    administrative_markers = {
        "signed into law",
        "meeting with government",
        "domestic aviation",
        "adviser to the president",
        "presidential regiment",
        "executive order",
        "medal of honor",
        "anniversary of the battle",
    }
    if any(keyword_in_text(text, marker) for marker in foreign_policy_markers):
        return False
    return any(keyword_in_text(text, marker) for marker in administrative_markers) or tags <= {"usa", "russia", "diplomacy"}


def is_weak_single_tag_noise(text: str, tags: set[str]) -> bool:
    if len(tags) != 1:
        return False
    weak_tags = {"usa", "russia", "china", "diplomacy"}
    if not tags <= weak_tags:
        return False
    strong_words = {
        "sanctions",
        "missile",
        "strike",
        "troops",
        "ceasefire",
        "nuclear",
        "foreign minister",
        "nato",
        "united nations",
        "security council",
        "ukraine",
        "iran",
        "taiwan",
        "gaza",
        "israel",
        "lebanon",
        "syria",
        "hormuz",
    }
    return not any(keyword_in_text(text, word) for word in strong_words)


def item_text(item: dict) -> str:
    return normalize_spaces(
        f"{item.get('title', '')} {item.get('summary', '')}"
    ).lower()


def keyword_in_text(text: str, keyword: str) -> bool:
    clean_keyword = keyword.strip().lower()
    if not clean_keyword:
        return False
    pattern = r"(?<![a-zа-я0-9])" + re.escape(clean_keyword) + r"(?![a-zа-я0-9])"
    return re.search(pattern, text, flags=re.IGNORECASE) is not None
