from __future__ import annotations

from urllib.parse import urlsplit


ALLOWED_GDELT_DOMAINS = {
    "reuters.com",
    "apnews.com",
    "bbc.com",
    "bbc.co.uk",
    "france24.com",
    "dw.com",
    "aljazeera.com",
    "theguardian.com",
    "un.org",
    "news.un.org",
    "state.gov",
    "whitehouse.gov",
    "defense.gov",
    "nato.int",
    "iaea.org",
    "consilium.europa.eu",
    "president.gov.ua",
    "mfa.gov.ua",
    "kremlin.ru",
    "mid.ru",
    "fmprc.gov.cn",
}

OFFICIAL_DOMAINS = {
    "un.org",
    "news.un.org",
    "state.gov",
    "whitehouse.gov",
    "defense.gov",
    "nato.int",
    "iaea.org",
    "consilium.europa.eu",
    "president.gov.ua",
    "mfa.gov.ua",
    "kremlin.ru",
    "mid.ru",
    "fmprc.gov.cn",
}


def get_domain(url: str | None) -> str:
    if not url:
        return ""
    domain = urlsplit(url).netloc.lower()
    if domain.startswith("www."):
        domain = domain[4:]
    return domain


def domain_matches(domain: str, allowed_domain: str) -> bool:
    return domain == allowed_domain or domain.endswith(f".{allowed_domain}")


def is_allowed_gdelt_domain(domain: str) -> bool:
    return any(domain_matches(domain, allowed) for allowed in ALLOWED_GDELT_DOMAINS)


def is_gdelt_item(item: dict) -> bool:
    return str(item.get("source", "")).lower().startswith("gdelt")


def source_score_for_item(item: dict) -> int:
    source = str(item.get("source", "")).lower()
    domain = get_domain(item.get("url", ""))

    if "reuters" in source or domain_matches(domain, "reuters.com"):
        return 10
    if "associated press" in source or source.startswith("ap ") or domain_matches(domain, "apnews.com"):
        return 10
    if any(domain_matches(domain, official) for official in OFFICIAL_DOMAINS):
        return 10
    if any(name in source for name in ("un news", "iaea", "nato")):
        return 10
    if any(domain_matches(domain, good) for good in ("bbc.com", "bbc.co.uk", "dw.com", "france24.com")):
        return 8
    if any(name in source for name in ("bbc", "deutsche welle", "france 24")):
        return 8
    if any(domain_matches(domain, good) for good in ("aljazeera.com", "theguardian.com")):
        return 7
    if any(name in source for name in ("al jazeera", "guardian")):
        return 7
    if is_gdelt_item(item) and is_allowed_gdelt_domain(domain):
        return 7
    return 3
