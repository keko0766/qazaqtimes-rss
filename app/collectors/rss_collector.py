from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import feedparser
import requests

from app.models import NewsItem
from app.utils.text import clean_html, normalize_spaces, normalize_url


def collect_rss_source(source: dict, timeout: int = 20, max_items: int = 30) -> list[dict]:
    name = source.get("name", "Unknown source")
    url = source.get("url", "")
    if source.get("enabled", True) is False:
        print(f"[rss] skip {name}: disabled in sources.json")
        return []
    if not url:
        print(f"[rss] skip {name}: missing URL")
        return []

    try:
        response = requests.get(
            url,
            timeout=timeout,
            headers={"User-Agent": "geo-news-bot/0.1 (+local research MVP)"},
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        print(f"[rss] {name}: cannot fetch feed: {exc}")
        return []

    parsed = feedparser.parse(response.content)
    if parsed.bozo:
        print(f"[rss] {name}: feed has parsing warnings, continuing")

    items: list[dict] = []
    for entry in parsed.entries[:max_items]:
        title = normalize_spaces(entry.get("title", ""))
        link = normalize_url(entry.get("link", ""))
        if not title or not link:
            continue

        summary = entry.get("summary") or entry.get("description") or ""
        items.append(
            NewsItem(
                title=title,
                url=link,
                source=name,
                published_at=parse_entry_date(entry),
                summary=clean_html(summary),
            ).to_dict()
        )

    print(f"[rss] {name}: {len(items)} items")
    return items


def collect_rss_sources(sources: list[dict], timeout: int = 20, max_items: int = 30) -> list[dict]:
    all_items: list[dict] = []
    for source in sources:
        all_items.extend(collect_rss_source(source, timeout=timeout, max_items=max_items))
    return all_items


def parse_entry_date(entry: dict) -> str:
    for key in ("published", "updated", "created"):
        value = entry.get(key)
        if not value:
            continue
        try:
            dt = parsedate_to_datetime(value)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc).isoformat()
        except (TypeError, ValueError, IndexError, OverflowError):
            continue

    parsed_struct = entry.get("published_parsed") or entry.get("updated_parsed")
    if parsed_struct:
        try:
            return datetime(*parsed_struct[:6], tzinfo=timezone.utc).isoformat()
        except (TypeError, ValueError):
            return ""
    return ""
