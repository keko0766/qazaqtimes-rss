from __future__ import annotations

from difflib import SequenceMatcher

from app.utils.text import normalize_title, normalize_url


def deduplicate_items(
    items: list[dict],
    existing_titles: list[str] | None = None,
    similarity_threshold: float = 0.92,
) -> list[dict]:
    seen_urls: set[str] = set()
    seen_titles = [normalize_title(title) for title in existing_titles or [] if title]
    result: list[dict] = []

    for item in items:
        item["url"] = normalize_url(item.get("url", ""))
        title_key = normalize_title(item.get("title", ""))

        if not item["url"] or not title_key:
            continue
        if item["url"] in seen_urls:
            continue
        if is_similar_to_existing(title_key, seen_titles, threshold=similarity_threshold):
            continue

        seen_urls.add(item["url"])
        seen_titles.append(title_key)
        result.append(item)

    return result


def is_similar_to_existing(title: str, existing_titles: list[str], threshold: float = 0.92) -> bool:
    for existing in existing_titles:
        if title == existing:
            return True
        if not title or not existing:
            continue
        max_len = max(len(title), len(existing))
        if max_len < 18:
            continue
        ratio = SequenceMatcher(None, title, existing).ratio()
        if ratio >= threshold:
            return True
    return False
