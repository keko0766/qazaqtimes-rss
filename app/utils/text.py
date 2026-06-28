from __future__ import annotations

import re
from html import unescape
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from bs4 import BeautifulSoup


TRACKING_PREFIXES = ("utm_",)
TRACKING_PARAMS = {"fbclid", "gclid", "mc_cid", "mc_eid"}


def clean_html(value: str | None, max_length: int = 600) -> str:
    if not value:
        return ""
    text = BeautifulSoup(value, "html.parser").get_text(" ", strip=True)
    text = unescape(text)
    text = normalize_spaces(text)
    if len(text) > max_length:
        return text[: max_length - 1].rstrip() + "..."
    return text


def normalize_spaces(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"\s+", " ", value).strip()


def normalize_title(value: str | None) -> str:
    text = normalize_spaces(value).lower()
    text = re.sub(r"[^a-zа-я0-9\s]", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def normalize_url(value: str | None) -> str:
    if not value:
        return ""
    parts = urlsplit(value.strip())
    query = [
        (key, val)
        for key, val in parse_qsl(parts.query, keep_blank_values=True)
        if key not in TRACKING_PARAMS and not key.startswith(TRACKING_PREFIXES)
    ]
    clean_query = urlencode(query, doseq=True)
    return urlunsplit((parts.scheme, parts.netloc.lower(), parts.path, clean_query, ""))
