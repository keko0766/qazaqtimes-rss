from __future__ import annotations

from datetime import datetime, timezone
from time import sleep

import requests

from app.models import NewsItem
from app.services.source_quality import get_domain, is_allowed_gdelt_domain
from app.utils.text import clean_html, normalize_spaces, normalize_url


GDELT_ENDPOINT = "https://api.gdeltproject.org/api/v2/doc/doc"
GDELT_USER_AGENT = "geo-news-bot/0.1 contact: local-mvp"
DEFAULT_MAX_RECORDS = 20
DEFAULT_DELAY_SECONDS = 15
DEFAULT_RETRY_DELAY_SECONDS = 60
DEFAULT_TIMEOUT_SECONDS = 20


def collect_gdelt(
    queries: list[str],
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    max_records: int = DEFAULT_MAX_RECORDS,
    delay_seconds: float = DEFAULT_DELAY_SECONDS,
    retry_delay_seconds: float = DEFAULT_RETRY_DELAY_SECONDS,
) -> list[dict]:
    all_items: list[dict] = []
    for query in queries:
        params = {
            "query": query,
            "format": "json",
            "mode": "ArtList",
            "maxrecords": max_records,
            "sort": "HybridRel",
        }
        try:
            response = fetch_gdelt(params=params, timeout=timeout)
            if response.status_code == 429:
                print(f"[gdelt] сұрау '{query}': rate limit, {retry_delay_seconds} секунд күту")
                sleep(retry_delay_seconds)
                response = fetch_gdelt(params=params, timeout=timeout)
                if response.status_code == 429:
                    print(f"[gdelt] сұрау '{query}': rate limit қайталанды, өткізіледі")
                    continue
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            print(f"[gdelt] сұрау '{query}': дерек жүктелмеді: {exc}")
            continue
        finally:
            if delay_seconds > 0:
                sleep(delay_seconds)

        articles = payload.get("articles", [])
        query_items = [parse_article(article, query) for article in articles]
        clean_items = [item for item in query_items if item["title"] and item["url"]]
        print(f"[gdelt] {query}: {len(clean_items)} items")
        all_items.extend(clean_items)
    return all_items


def fetch_gdelt(params: dict, timeout: int) -> requests.Response:
    return requests.get(
        GDELT_ENDPOINT,
        params=params,
        timeout=timeout,
        headers={"User-Agent": GDELT_USER_AGENT},
    )


def parse_article(article: dict, query: str) -> dict:
    url = normalize_url(article.get("url", ""))
    domain = (article.get("domain") or get_domain(url)).lower()
    if domain.startswith("www."):
        domain = domain[4:]
    if not is_allowed_gdelt_domain(domain):
        return NewsItem(title="", url="").to_dict()
    return NewsItem(
        title=normalize_spaces(article.get("title", "")),
        url=url,
        source=f"GDELT / {domain}",
        published_at=parse_gdelt_date(article.get("seendate", "")),
        summary=clean_html(f"Found by GDELT query: {query}", max_length=200),
    ).to_dict()


def parse_gdelt_date(value: str) -> str:
    if not value:
        return ""
    for fmt in ("%Y%m%dT%H%M%SZ", "%Y%m%d%H%M%S"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc).isoformat()
        except ValueError:
            continue
    return value
