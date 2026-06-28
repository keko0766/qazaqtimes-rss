from __future__ import annotations

import re
from difflib import SequenceMatcher

from app.services.topic_score import is_weak_gdelt_summary
from app.utils.text import normalize_url

STOPWORDS = {
    "a",
    "an",
    "and",
    "as",
    "at",
    "by",
    "for",
    "from",
    "in",
    "into",
    "is",
    "it",
    "of",
    "on",
    "or",
    "over",
    "says",
    "the",
    "to",
    "with",
    "after",
    "before",
    "new",
    "live",
    "latest",
    "news",
    "update",
    "updates",
    "about",
    "amid",
    "that",
    "this",
    "will",
    "has",
    "have",
    "had",
    "are",
    "was",
    "were",
    "president",
    "donald",
    "trump",
    "america",
    "first",
    "government",
    "members",
    "meeting",
    "exchange",
    "exchanges",
    "targets",
    "threatens",
    "accuse",
    "accuses",
    "violating",
    "days",
    "deal",
    "agreement",
}

SIGNATURE_KEYWORDS = {
    "iran",
    "nuclear",
    "sanctions",
    "usa",
    "us",
    "strike",
    "strikes",
    "attack",
    "attacks",
    "ceasefire",
    "hormuz",
    "evacuation",
    "evacuates",
    "seafarers",
    "lebanon",
    "israel",
    "gaza",
    "ukraine",
    "russia",
    "nato",
    "china",
    "taiwan",
    "missile",
    "troops",
}

ALIASES = {
    "u": "usa",
    "us": "usa",
    "u.s": "usa",
    "america": "usa",
    "american": "usa",
    "attacks": "attack",
    "attacked": "attack",
    "strikes": "strike",
    "struck": "strike",
    "evacuates": "evacuation",
    "evacuate": "evacuation",
    "evacuating": "evacuation",
    "iranian": "iran",
    "russian": "russia",
    "ukrainian": "ukraine",
    "israeli": "israel",
    "lebanese": "lebanon",
}


def cluster_events(items: list[dict], similarity_threshold: float = 0.55) -> list[dict]:
    clusters: list[dict] = []
    for item in sorted(items, key=item_sort_key, reverse=True):
        item_tokens = title_tokens(item.get("title", ""))
        item_signature = event_signature(item_tokens, item.get("tags", []))
        matched = None
        best_ratio = 0.0

        for cluster in clusters:
            ratio = SequenceMatcher(None, " ".join(item_tokens), cluster["fingerprint"]).ratio()
            if should_join_cluster(
                item_tokens,
                cluster["tokens"],
                item_signature,
                cluster["signature"],
                ratio,
                similarity_threshold,
            ):
                if ratio > best_ratio:
                    matched = cluster
                    best_ratio = ratio if ratio > 0 else 0.01

        if matched:
            matched["items"].append(item)
            matched["tokens"] |= item_tokens
            matched["signature"] |= item_signature
            matched["fingerprint"] = " ".join(sorted(matched["tokens"]))
        else:
            clusters.append(
                {
                    "items": [item],
                    "tokens": set(item_tokens),
                    "signature": set(item_signature),
                    "fingerprint": " ".join(sorted(item_tokens)),
                }
            )

    event_clusters = [finalize_cluster(cluster) for cluster in clusters]
    return sorted(event_clusters, key=lambda cluster: cluster["final_score"], reverse=True)


def finalize_cluster(cluster: dict) -> dict:
    items = sorted(cluster["items"], key=item_sort_key, reverse=True)
    lead = items[0]
    tags = sorted({tag for item in items for tag in item.get("tags", [])})
    links = unique_links(items)
    sources = unique_values(link.get("source", "unknown source") for link in links)
    source_count = len(sources)
    max_score = max(int(item.get("final_score", 0)) for item in items)
    max_source_score = max(int(item.get("source_score", 0)) for item in items)
    core_topic_score = max(int(item.get("core_topic_score", 0)) for item in items)
    core_topics = sorted({topic for item in items for topic in item.get("core_topics", [])})

    return {
        "title": lead.get("title", "Untitled event"),
        "summary": best_summary(items),
        "tags": tags,
        "sources": sources,
        "links": links,
        "items": items,
        "source_count": source_count,
        "max_source_score": max_source_score,
        "core_topic_score": core_topic_score,
        "core_topics": core_topics,
        "final_score": max_score + source_count * 2 + min(len(items), 5),
    }


def item_sort_key(item: dict) -> tuple[int, int, str]:
    return (
        int(item.get("final_score", 0)),
        int(item.get("source_score", 0)),
        item.get("published_at") or item.get("created_at") or "",
    )


def title_tokens(title: str) -> set[str]:
    normalized = re.sub(r"[^a-zа-я0-9]+", " ", title.lower(), flags=re.IGNORECASE)
    tokens = set()
    for token in normalized.split():
        normalized_token = ALIASES.get(token, token)
        if len(normalized_token) > 2 and normalized_token not in STOPWORDS:
            tokens.add(normalized_token)
    return tokens


def should_join_cluster(
    item_tokens: set[str],
    cluster_tokens: set[str],
    item_signature: set[str],
    cluster_signature: set[str],
    ratio: float,
    similarity_threshold: float,
) -> bool:
    if strong_signature_match(item_signature, cluster_signature):
        return True
    if not has_common_keywords(item_tokens, cluster_tokens):
        return False
    if ratio > similarity_threshold:
        return True
    common = item_tokens & cluster_tokens
    union = item_tokens | cluster_tokens
    jaccard = len(common) / len(union) if union else 0
    return len(common) >= 3 and jaccard >= 0.25


def event_signature(tokens: set[str], tags: list[str]) -> set[str]:
    signature = {token for token in tokens if token in SIGNATURE_KEYWORDS}
    signature |= {tag for tag in tags if tag in SIGNATURE_KEYWORDS}
    if "usa" in signature and "iran" in signature and ({"attack", "strike", "ceasefire"} & signature):
        signature.add("usa_iran_escalation")
    if "iran" in signature and "nuclear" in signature:
        signature.add("iran_nuclear")
    if "hormuz" in signature and ({"evacuation", "seafarers"} & signature):
        signature.add("hormuz_evacuation")
    if "israel" in signature and "lebanon" in signature:
        signature.add("israel_lebanon")
    if "russia" in signature and "ukraine" in signature and ({"attack", "strike", "missile"} & signature):
        signature.add("russia_ukraine_strikes")
    return signature


def strong_signature_match(left: set[str], right: set[str]) -> bool:
    shared = left & right
    strong_markers = {
        "usa_iran_escalation",
        "iran_nuclear",
        "hormuz_evacuation",
        "israel_lebanon",
        "russia_ukraine_strikes",
    }
    if shared & strong_markers:
        return True
    if {"iran", "nuclear"} <= shared:
        return True
    if {"usa", "iran", "strike"} <= shared:
        return True
    return False


def has_common_keywords(left: set[str], right: set[str]) -> bool:
    common = left & right
    if len(common) >= 2:
        return True
    important = {
        "iran",
        "nuclear",
        "ukraine",
        "russia",
        "china",
        "taiwan",
        "gaza",
        "israel",
        "lebanon",
        "syria",
        "hormuz",
        "nato",
        "sanctions",
        "missile",
        "strike",
    }
    return bool(common & important)


def best_summary(items: list[dict]) -> str:
    for item in items:
        summary = item.get("summary", "").strip()
        if summary and not is_weak_gdelt_summary(summary):
            return summary
    return "Несколько источников сообщили об одном и том же геополитическом событии."


def unique_links(items: list[dict]) -> list[dict]:
    links = []
    seen_urls = set()
    seen_source_titles = set()

    for item in items:
        url = normalize_url(item.get("url", ""))
        source = item.get("source", "") or "unknown source"
        title = item.get("title", "") or "Untitled"
        source_title_key = (source.lower(), title.lower())

        if not url:
            continue
        if url in seen_urls or source_title_key in seen_source_titles:
            continue
        if is_weak_gdelt_summary(item.get("summary")) and not is_good_supporting_source(item):
            continue

        seen_urls.add(url)
        seen_source_titles.add(source_title_key)
        links.append(
            {
                "title": title,
                "url": url,
                "source": source,
                "source_score": int(item.get("source_score", 0)),
                "weak_summary": is_weak_gdelt_summary(item.get("summary")),
            }
        )
    return links


def is_good_supporting_source(item: dict) -> bool:
    title = item.get("title", "")
    return int(item.get("source_score", 0)) >= 8 and len(title) >= 20


def unique_values(values) -> list[str]:
    result = []
    seen = set()
    for value in values:
        clean_value = value or "unknown source"
        if clean_value in seen:
            continue
        seen.add(clean_value)
        result.append(clean_value)
    return result
