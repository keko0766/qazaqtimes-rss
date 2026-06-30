from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path

from app.services.ai_types import (
    AI_ARTICLE_JSON_FIELDS,
    BAD_KAZAKH_PHRASES,
    AITextResult,
    MIN_EVENT_KEYWORD_OVERLAP,
)
from app.services.ai_writer import generate_article_text
from app.utils.datetime import today_str


REQUIRED_JSON_FIELDS = AI_ARTICLE_JSON_FIELDS
MIN_JSON_FIELD_CHARS = 15
MIN_EVENT_KEYWORD_OVERLAP_REQUIRED = MIN_EVENT_KEYWORD_OVERLAP

BULLET_FIELD_PREFIXES = ("- ", "• ")

GIBBERISH_PATTERNS = (
    r"\b\w*улу\b",
    r"\b\w*улейт\b",
    r"\b\w*лулу\b",
    r"\bнатыйжа\w*\b",
    r"\bкечерген\b",
    r" болумен\b",
    r"\bынгікаст\b",
    r"\bлевантия\b",
    r"\bруhani\b",
    r"\bоруңыз\b",
)

TOO_GENERIC_PHRASES = (
    "табиғий боюнда",
    "көргенді жеңілеттікт",
    "маңызды сәйкес",
    "айырмачыларда",
    "көргенді жеңілеттікті",
    "өз аяғы менен",
)

TAG_KAZAKH_KEYWORDS = {
    "usa": ["АҚШ", "Америка"],
    "iran": ["Иран"],
    "russia": ["Ресей"],
    "ukraine": ["Украина"],
    "china": ["Қытай"],
    "taiwan": ["Тайвань"],
    "nato": ["НАТО"],
    "eu": ["ЕО", "Еуропа"],
    "middle_east": ["Таяу Шығыс", "Ормуз"],
    "israel": ["Израиль"],
    "gaza": ["Газа"],
    "lebanon": ["Ливан"],
    "syria": ["Сирия"],
    "hormuz": ["Ормуз"],
    "war": ["соққы", "соғыс", "зымыран"],
    "military": ["соққы"],
    "diplomacy": ["келіссөз", "дипломатия"],
    "sanctions": ["санкция"],
    "nuclear": ["ядерлік"],
}

TOPIC_KAZAKH_KEYWORDS = {
    "russia_ukraine": ["Украина", "Ресей", "БҰҰ", "соққы", "энергетика", "гуманитарлық"],
    "usa_iran": ["Иран", "АҚШ", "Бахрейн", "Кувейт", "келіссөз", "соққы"],
    "middle_east": ["Иран", "Израиль", "Ливан", "Ормуз", "соққы", "келіссөз"],
    "nato_eu": ["НАТО", "ЕО", "санкция", "қауіпсіздік"],
    "china_taiwan": ["Қытай", "Тайвань", "соққы"],
    "other": ["БҰҰ", "соққы", "келіссөз"],
}

ENGLISH_TERM_KAZAKH = {
    "ukraine": ["Украина"],
    "ukrainian": ["Украина"],
    "russia": ["Ресей"],
    "russian": ["Ресей"],
    "un": ["БҰҰ"],
    "humanitarian": ["гуманитарлық"],
    "strike": ["соққы"],
    "strikes": ["соққы"],
    "power": ["энергетика"],
    "energy": ["энергетика"],
    "electricity": ["энергетика"],
    "iran": ["Иран"],
    "iranian": ["Иран"],
    "usa": ["АҚШ"],
    "u.s.": ["АҚШ"],
    "american": ["АҚШ"],
    "bahrain": ["Бахрейн"],
    "kuwait": ["Кувейт"],
    "talks": ["келіссөз"],
    "negotiation": ["келіссөз"],
    "negotiations": ["келіссөз"],
    "missile": ["зымыран", "соққы"],
    "drone": ["дрон", "соққы"],
    "war": ["соғыс", "соққы"],
    "china": ["Қытай"],
    "taiwan": ["Тайвань"],
    "nato": ["НАТО"],
    "lebanon": ["Ливан"],
    "israel": ["Израиль"],
    "gaza": ["Газа"],
    "hormuz": ["Ормуз"],
}

REJECTED_TITLE_PATTERNS = {
    "world news in brief",
    "news in brief",
    "as it happened",
    "live updates",
    "liveblog",
    "briefing",
    "roundup",
    "opinion",
    "analysis video",
    "video only",
    "europe live",
}

TOPIC_LIMITS = {
    "usa_iran": 2,
    "middle_east": 2,
    "russia_ukraine": 2,
    "nato_eu": 2,
    "china_taiwan": 1,
    "other": 1,
}


def select_article_clusters(clusters: list[dict], limit: int = 5) -> list[dict]:
    selected: list[dict] = []
    fingerprints: list[set[str]] = []
    topic_counts: dict[str, int] = {}

    for cluster in sorted(clusters, key=lambda item: int(item.get("final_score", 0)), reverse=True):
        if not is_article_topic(cluster) or is_rejected_article_title(cluster):
            continue
        topic = article_topic(cluster)
        if topic_counts.get(topic, 0) >= TOPIC_LIMITS.get(topic, 1):
            continue
        fingerprint = title_fingerprint(cluster)
        if is_duplicate_fingerprint(fingerprint, fingerprints):
            continue
        selected.append(cluster)
        fingerprints.append(fingerprint)
        topic_counts[topic] = topic_counts.get(topic, 0) + 1
        if len(selected) >= limit:
            break

    return selected


def generate_kazakh_article(cluster: dict, index: int = 1) -> tuple[str | None, str]:
    prompt = build_prompt(cluster)
    ai_result = generate_article_text(prompt)
    raw_text = ai_result.raw_response or ai_result.text or ""
    reject_reason = ai_result.error_reason
    sections: dict | None = None
    rendered = ""
    json_parsed = False
    accepted = False
    quality_details: dict = {}

    print(f"[ai] provider={ai_result.provider} model={ai_result.model}")
    if ai_result.ollama_available is not None:
        print(f"[ai] ollama available={str(ai_result.ollama_available).lower()}")
    print(f"[ai] raw response length={len(ai_result.raw_response)}")

    if reject_reason not in {"ollama_not_ready", "lmstudio_not_ready", "provider_disabled"}:
        sections, parse_reason = parse_ai_article_json(raw_text)
        if sections:
            json_parsed = True
            print("[ai] json parsed=true")
            rendered = render_structured_article(kazakh_headline(cluster), sections, cluster)
            if not reject_reason:
                accepted, reject_reason, quality_details = is_quality_structured_article(
                    sections,
                    rendered,
                    ai_result,
                    cluster,
                )
        else:
            print(f"[ai] json parsed=false reason={parse_reason}")
            if not reject_reason:
                reject_reason = parse_reason

    if accepted:
        reject_reason = None

    print(f"[ai] quality accepted={str(accepted).lower()}" + (f" reason={reject_reason}" if reject_reason else ""))

    if accepted:
        print(f"[article] жазу режимі: {ai_result.provider}")
        save_ai_debug(
            index,
            cluster,
            prompt,
            ai_result,
            sections=sections,
            rendered=rendered,
            used_fallback=False,
            reject_reason=None,
            json_parsed=json_parsed,
            quality_details=quality_details,
        )
        return rendered, ai_result.provider

    if raw_text.strip():
        print(f"[article] AI мәтіні сапа тексерісінен өтпеді; reason={reject_reason}")
    print("[article] жазу режимі: fallback")
    print("[article] fallback қолданылды")
    save_ai_debug(
        index,
        cluster,
        prompt,
        ai_result,
        sections=sections,
        rendered=rendered,
        used_fallback=True,
        reject_reason=reject_reason,
        json_parsed=json_parsed,
        quality_details=quality_details,
    )
    return fallback_article(cluster), "fallback"


def save_article(
    title: str,
    content: str,
    *,
    index: int,
    mode: str,
    source_count: int,
    replace_today: bool = False,
    date: str | None = None,
) -> Path:
    article_date = date or today_str()
    body = content.rstrip()
    article_title = extract_markdown_title(body) or title
    document = render_document(article_title, body, article_date, source_count, mode)

    out_dir = article_output_dir(article_date, replace_today=replace_today)
    out_dir.mkdir(parents=True, exist_ok=True)
    filename = unique_filename(out_dir, index, slugify(title))
    path = out_dir / filename
    path.write_text(document, encoding="utf-8")
    return path


def prepare_article_output(replace_today: bool = False, date: str | None = None) -> Path:
    article_date = date or today_str()
    out_dir = article_output_dir(article_date, replace_today=replace_today)
    if replace_today and out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


def article_output_dir(article_date: str, replace_today: bool = False) -> Path:
    base = Path(os.getenv("OUTPUT_DIR", "output")) / "articles" / article_date
    return base / "latest" if replace_today else base


def build_prompt(cluster: dict) -> str:
    links = [
        f"- {link.get('source', 'source')}: {link.get('title', link.get('url', ''))} — {link.get('url', '')}"
        for link in cluster.get("links", [])[:3]
        if link.get("url")
    ]
    sources = ", ".join(cluster.get("sources", [])[:3])
    tags = ", ".join(tag for tag in cluster.get("tags", []) if tag != "untagged")

    return f"""Тек JSON қайтар. Markdown, code block, түсіндіру немесе JSON алдында/кейін мәтін жоқ.

Формат:
{{
"lead": "...",
"what_happened": "...",
"why_important": "...",
"what_next": "..."
}}

Мысал (стильді көшір, фактілерді емес):
{{
"lead": "Reuters деректеріне қарағанда, Украинада энергетика нысандарына дрон соққысы тіркелді. Оқиға Ресей мен Украина арасындағы соғыс динамикасына қатысты.",
"what_happened": "Дереккөздер энергетика инфрақұрылымына бағытталған шабуыл туралы хабарлады. Ресей мен Украина тараптардың ресми мәлімдемелері әлі толық расталмады.",
"why_important": "Энергетика нысандарына соққы инфрақұрылым қауіпсіздігіне және одақтастардың саяси шешімдеріне әсер етуі мүмкін.",
"what_next": "Әрі қарай Ресей мен Украина тараптардың ресми мәлімдемелері мен соққы салдары туралы деректер бақыланады."
}}

Ережелер:
- Қарапайым журналистикалық қазақ тілінде жаз; мысалдағы стильді елікте, фактілерді көшірме.
- Тақырыптағы негізгі актерлерді (ел, ұйым, тарап) міндетті түрде ата.
- Әр JSON өрісі нақты осы оқиға туралы болсын; жалпы сөздерден аулақ бол.
- Әр өріс — 1-2 қысқа сөйлем, bullet (-, •) қолданба.
- Қырғыз сөздерін қолданба, ерекше сөз ойлап табпа.
- Факт, сан, есім, цитата ойдан шығарма; дерек аз болса, сақ тұжырым қолдан.
- Дереккөз тізімін, тақырып немесе heading жазба.
- Тек JSON қайтар.

Cluster title: {cluster.get("title", "")}
Summary: {cluster.get("summary", "")}
Tags: {tags}
Sources: {sources}
Source links:
{chr(10).join(links)}
"""


def fallback_article(cluster: dict) -> str:
    original_title = str(cluster.get("title") or "Геосаяси оқиға").strip()
    headline = kazakh_headline(cluster)
    sources = natural_sources(cluster)
    summary = usable_summary(cluster)
    what_happened = what_happened_text(cluster, original_title, summary)

    return "\n".join(
        [
            f"# {headline}",
            "",
            "**Лид:**",
            f"{sources} деректеріне қарағанда, {lead_text(cluster, original_title, summary)}",
            "",
            "**Не болды:**",
            what_happened,
            "",
            "**Неге маңызды:**",
            importance_text(cluster),
            "",
            "**Әрі қарай не күту керек:**",
            next_watch_text(cluster),
            "",
            "**Дереккөздер:**",
            "",
            *format_sources(cluster),
        ]
    )


def render_document(title: str, body: str, date: str, source_count: int, mode: str) -> str:
    return "\n".join(
        [
            "---",
            f'title: "{yaml_escape(title)}"',
            f'date: "{date}"',
            f"source_count: {source_count}",
            f'mode: "{mode}"',
            "---",
            "",
            body,
            "",
        ]
    )


def parse_ai_article_json(raw_text: str) -> tuple[dict | None, str | None]:
    stripped = strip_json_fences(raw_text.strip())
    if not stripped:
        return None, "json_parse_failed"

    candidates = [stripped]
    extracted = extract_json_object(stripped)
    if extracted and extracted not in candidates:
        candidates.append(extracted)

    data: dict | None = None
    for candidate in candidates:
        for normalized in (candidate, fix_loose_json(candidate)):
            try:
                parsed = json.loads(normalized)
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(parsed, dict):
                data = parsed
                break
        if data is not None:
            break

    if data is None:
        return None, "json_parse_failed"

    missing = [field for field in REQUIRED_JSON_FIELDS if field not in data]
    if missing:
        return None, "missing_json_fields"

    sections: dict[str, str] = {}
    for field in REQUIRED_JSON_FIELDS:
        value = data.get(field)
        if not isinstance(value, str) or not value.strip():
            return None, "empty_json_field"
        sections[field] = value.strip()

    return sections, None


def render_structured_article(title: str, sections: dict, cluster: dict) -> str:
    return "\n".join(
        [
            f"# {title}",
            "",
            "**Лид:**",
            sections["lead"],
            "",
            "**Не болды:**",
            sections["what_happened"],
            "",
            "**Неге маңызды:**",
            sections["why_important"],
            "",
            "**Әрі қарай не күту керек:**",
            sections["what_next"],
            "",
            "**Дереккөздер:**",
            "",
            *format_sources(cluster),
        ]
    )


def is_quality_structured_article(
    sections: dict,
    rendered: str,
    ai_result: AITextResult,
    cluster: dict,
) -> tuple[bool, str | None, dict]:
    quality_details = empty_quality_details(cluster)

    if ai_result.finish_reason == "length" or ai_result.done_reason == "length":
        quality_details["quality_checks"]["finish_reason_length"] = False
        return False, "finish_reason_length", quality_details

    combined = "\n\n".join(sections[field] for field in REQUIRED_JSON_FIELDS)
    if not combined.strip():
        quality_details["quality_checks"]["empty_response"] = False
        return False, "empty_response", quality_details

    for field in REQUIRED_JSON_FIELDS:
        if len(sections[field]) < MIN_JSON_FIELD_CHARS:
            quality_details["quality_checks"]["empty_json_field"] = False
            quality_details["quality_error_sample"] = sections[field][:160]
            return False, "empty_json_field", quality_details

    if has_broken_markdown(rendered):
        quality_details["quality_checks"]["markdown_broken"] = False
        return False, "markdown_broken", quality_details

    text_for_language = re.sub(r"https?://\S+", "", combined)
    word_count = len(re.findall(r"\b[\wӘәҒғҚқҢңӨөҰұҮүҺһІі-]+\b", text_for_language))
    if word_count > 320:
        quality_details["quality_checks"]["too_long"] = False
        return False, "too_long", quality_details

    accepted, reject_reason, section_details = is_good_kazakh_article_sections(sections, cluster)
    quality_details.update(section_details)
    if not accepted:
        return False, reject_reason, quality_details

    quality_details["quality_checks"]["accepted"] = True
    return True, None, quality_details


def is_good_kazakh_article_sections(
    sections: dict,
    cluster: dict,
) -> tuple[bool, str | None, dict]:
    combined = "\n\n".join(sections[field] for field in REQUIRED_JSON_FIELDS)
    combined_lower = combined.lower()
    event_keywords = extract_event_keywords(cluster)
    quality_details = empty_quality_details(cluster, event_keywords=event_keywords)

    for field in REQUIRED_JSON_FIELDS:
        value = sections[field].strip()
        if value.startswith(BULLET_FIELD_PREFIXES):
            quality_details["quality_checks"]["bullet_text_in_json_field"] = False
            quality_details["quality_error_sample"] = value[:160]
            return False, "bullet_text_in_json_field", quality_details

    bad_phrase = find_bad_kazakh_phrase(combined_lower)
    if bad_phrase:
        quality_details["quality_checks"]["bad_phrase"] = False
        quality_details["bad_phrase_detected"] = bad_phrase
        quality_details["quality_error_sample"] = combined[:160]
        return False, "gibberish_text", quality_details

    gibberish_match = find_gibberish_pattern(combined_lower)
    if gibberish_match:
        quality_details["quality_checks"]["gibberish_text"] = False
        quality_details["quality_error_sample"] = gibberish_match[:160]
        return False, "gibberish_text", quality_details

    text_for_language = re.sub(r"https?://\S+", "", combined)
    cyrillic_count = len(re.findall(r"[А-Яа-яӘәҒғҚқҢңӨөҰұҮүҺһІі]", text_for_language))
    latin_count = len(re.findall(r"[A-Za-z]", text_for_language))
    word_count = len(re.findall(r"\b[\wӘәҒғҚқҢңӨөҰұҮүҺһІі-]+\b", text_for_language))
    quality_details["quality_checks"]["cyrillic_ratio"] = cyrillic_count >= 120 and cyrillic_count >= latin_count
    quality_details["quality_checks"]["word_count"] = word_count >= 60
    if cyrillic_count < 120 or cyrillic_count < latin_count or word_count < 60:
        quality_details["quality_error_sample"] = combined[:160]
        return False, "low_kazakh_quality", quality_details

    overlap, matched_keywords = count_event_keyword_overlap(combined_lower, event_keywords)
    quality_details["event_keyword_overlap"] = overlap
    quality_details["quality_checks"]["event_keywords"] = overlap >= MIN_EVENT_KEYWORD_OVERLAP_REQUIRED
    quality_details["matched_event_keywords"] = matched_keywords
    if overlap < MIN_EVENT_KEYWORD_OVERLAP_REQUIRED:
        quality_details["quality_error_sample"] = combined[:160]
        return False, "event_not_mentioned", quality_details

    if is_too_generic(combined_lower, overlap):
        quality_details["quality_checks"]["too_generic"] = False
        quality_details["quality_error_sample"] = combined[:160]
        return False, "too_generic", quality_details

    repeated, repeated_sample, repeated_count = find_repeated_phrase_detail(combined)
    quality_details["repeated_phrase_sample"] = repeated_sample
    quality_details["repeated_phrase_count"] = repeated_count
    quality_details["quality_checks"]["repeated_phrases"] = not repeated
    if repeated:
        quality_details["quality_error_sample"] = repeated_sample or combined[:160]
        return False, "repeated_phrases", quality_details

    quality_details["quality_checks"]["accepted"] = True
    return True, None, quality_details


def empty_quality_details(cluster: dict, *, event_keywords: list[str] | None = None) -> dict:
    keywords = event_keywords if event_keywords is not None else extract_event_keywords(cluster)
    return {
        "quality_checks": {},
        "bad_phrase_detected": None,
        "event_keyword_overlap": 0,
        "expected_event_keywords": keywords[:12],
        "matched_event_keywords": [],
        "quality_error_sample": None,
        "repeated_phrase_sample": None,
        "repeated_phrase_count": 0,
    }


def find_bad_kazakh_phrase(text_lower: str) -> str | None:
    for phrase in BAD_KAZAKH_PHRASES:
        if phrase in text_lower:
            return phrase
    return None


def find_gibberish_pattern(text_lower: str) -> str | None:
    for pattern in GIBBERISH_PATTERNS:
        match = re.search(pattern, text_lower, flags=re.IGNORECASE)
        if match:
            return match.group(0)
    return None


def extract_event_keywords(cluster: dict) -> list[str]:
    keywords: list[str] = []
    seen: set[str] = set()

    def add_keyword(keyword: str) -> None:
        normalized = keyword.strip()
        if len(normalized) < 2 or normalized in seen:
            return
        seen.add(normalized)
        keywords.append(normalized)

    topic = article_topic(cluster)
    for keyword in TOPIC_KAZAKH_KEYWORDS.get(topic, TOPIC_KAZAKH_KEYWORDS["other"]):
        add_keyword(keyword)

    for tag in cluster.get("tags") or []:
        for keyword in TAG_KAZAKH_KEYWORDS.get(tag, []):
            add_keyword(keyword)

    searchable_parts = [
        str(cluster.get("title", "")),
        str(cluster.get("summary", "")),
        " ".join(cluster.get("sources") or []),
    ]
    for link in cluster.get("links") or []:
        searchable_parts.append(str(link.get("title", "")))

    searchable = " ".join(searchable_parts).lower()
    for term, mapped_keywords in ENGLISH_TERM_KAZAKH.items():
        if keyword_in_cluster_text(searchable, term):
            for keyword in mapped_keywords:
                add_keyword(keyword)

    title_tokens = re.findall(r"[a-zа-яәғқңөұүһі0-9-]+", searchable)
    for token in title_tokens:
        if token in ENGLISH_TERM_KAZAKH:
            for keyword in ENGLISH_TERM_KAZAKH[token]:
                add_keyword(keyword)

    return keywords


def keyword_in_cluster_text(text: str, keyword: str) -> bool:
    if " " in keyword:
        return keyword in text
    return re.search(rf"(?<![a-zа-яәғқңөұүһі0-9-]){re.escape(keyword)}(?![a-zа-яәғқңөұүһі0-9-])", text) is not None


def count_event_keyword_overlap(text_lower: str, event_keywords: list[str]) -> tuple[int, list[str]]:
    matched: list[str] = []
    for keyword in event_keywords:
        keyword_lower = keyword.lower()
        if keyword_lower in text_lower:
            matched.append(keyword)
    return len(matched), matched


def is_too_generic(text_lower: str, event_overlap: int) -> bool:
    if any(phrase in text_lower for phrase in TOO_GENERIC_PHRASES):
        return True
    if event_overlap <= 1 and len(re.findall(r"\b[\wӘәҒғҚқҢңӨөҰұҮүҺһІі-]+\b", text_lower)) < 80:
        return True
    return False


def find_repeated_phrase_detail(text: str) -> tuple[bool, str | None, int]:
    normalized = re.sub(r"\s+", " ", text.lower())
    phrases = re.findall(
        r"\b[\wӘәҒғҚқҢңӨөҰұҮүҺһІі-]+(?:\s+[\wӘәҒғҚқҢңӨөҰұҮүҺһІі-]+){3,}\b",
        normalized,
    )
    seen: dict[str, int] = {}
    for phrase in phrases:
        key = phrase.strip(" .,:;!?")
        seen[key] = seen.get(key, 0) + 1
        if seen[key] >= 3:
            return True, key, seen[key]

    sentences = [part.strip() for part in re.split(r"[.!?。]+", normalized) if len(part.strip()) > 30]
    sentence_counts: dict[str, int] = {}
    for sentence in sentences:
        sentence_counts[sentence] = sentence_counts.get(sentence, 0) + 1
        if sentence_counts[sentence] >= 2:
            return True, sentence, sentence_counts[sentence]
    return False, None, 0


def fix_loose_json(text: str) -> str:
    return re.sub(r",(\s*[}\]])", r"\1", text)


def strip_json_fences(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def extract_json_object(text: str) -> str | None:
    start = text.find("{")
    if start == -1:
        return None

    depth = 0
    in_string = False
    escape = False
    for index, char in enumerate(text[start:], start=start):
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None


def clean_ai_article(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("---"):
        parts = stripped.split("---", 2)
        if len(parts) == 3:
            stripped = parts[2].strip()
    return stripped


def save_ai_debug(
    index: int,
    cluster: dict,
    prompt: str,
    ai_result: AITextResult,
    *,
    sections: dict | None,
    rendered: str,
    used_fallback: bool,
    reject_reason: str | None,
    json_parsed: bool,
    quality_details: dict | None = None,
) -> None:
    decision = ai_decision_payload(
        cluster,
        ai_result,
        sections=sections,
        rendered=rendered,
        used_fallback=used_fallback,
        reject_reason=reject_reason,
        json_parsed=json_parsed,
        quality_details=quality_details,
    )
    write_ai_status(decision, ai_result)
    if not debug_ai_articles():
        return

    folder = ai_debug_dir()
    folder.mkdir(parents=True, exist_ok=True)
    prefix = f"{index:02d}"
    (folder / f"{prefix}_prompt.md").write_text(prompt, encoding="utf-8")
    (folder / f"{prefix}_raw_response.md").write_text(ai_result.raw_response, encoding="utf-8")
    (folder / f"{prefix}_parsed_sections.json").write_text(
        json.dumps(sections or {}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (folder / f"{prefix}_rendered_article.md").write_text(rendered, encoding="utf-8")
    (folder / f"{prefix}_decision.json").write_text(
        json.dumps(decision, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (folder / "latest_status.json").write_text(
        json.dumps(ai_status_payload(decision, ai_result), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def ai_decision_payload(
    cluster: dict,
    ai_result: AITextResult,
    *,
    sections: dict | None,
    rendered: str,
    used_fallback: bool,
    reject_reason: str | None,
    json_parsed: bool,
    quality_details: dict | None = None,
) -> dict:
    details = quality_details or empty_quality_details(cluster)
    payload = {
        "provider": ai_result.provider,
        "model": ai_result.model,
        "ollama_available": ai_result.ollama_available,
        "used_fallback": used_fallback,
        "reject_reason": reject_reason,
        "finish_reason": ai_result.finish_reason,
        "done_reason": ai_result.done_reason,
        "raw_length": len(ai_result.raw_response),
        "rendered_length": len(rendered),
        "json_parsed": json_parsed,
        "fields": list(REQUIRED_JSON_FIELDS) if json_parsed and sections else [],
        "cluster_title": str(cluster.get("title", "")),
        "sources": list(cluster.get("sources", [])[:3]),
        "debug_folder": str(ai_debug_dir()),
        "rendered_preview": rendered[:1200] if debug_ai_articles() else "",
        "quality_checks": details.get("quality_checks", {}),
        "bad_phrase_detected": details.get("bad_phrase_detected"),
        "event_keyword_overlap": details.get("event_keyword_overlap", 0),
        "expected_event_keywords": details.get("expected_event_keywords", []),
        "matched_event_keywords": details.get("matched_event_keywords", []),
        "quality_error_sample": details.get("quality_error_sample"),
        "repeated_phrase_sample": details.get("repeated_phrase_sample"),
        "repeated_phrase_count": details.get("repeated_phrase_count", 0),
    }
    return payload


def write_ai_status(decision: dict, ai_result: AITextResult) -> None:
    path = ai_status_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(ai_status_payload(decision, ai_result), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def ai_status_payload(decision: dict, ai_result: AITextResult) -> dict:
    payload = dict(decision)
    if debug_ai_articles():
        payload["raw_preview"] = ai_result.raw_response[:1200]
    else:
        payload["raw_preview"] = ""
        payload["rendered_preview"] = ""
    return payload


def debug_ai_articles() -> bool:
    return os.getenv("DEBUG_AI_ARTICLES", "false").strip().lower() in {"1", "true", "yes", "on"}


def ai_debug_dir() -> Path:
    return Path(os.getenv("OUTPUT_DIR", "output")) / "debug_ai" / today_str()


def ai_status_path() -> Path:
    return Path("data") / "ai_status.json"


def has_broken_markdown(text: str) -> bool:
    if text.count("```") % 2:
        return True
    if "<<<<<<<" in text or "=======" in text or ">>>>>>>" in text:
        return True
    return False


def has_repeated_phrases(text: str) -> bool:
    repeated, _, _ = find_repeated_phrase_detail(text)
    return repeated


def unique_filename(out_dir: Path, index: int, slug: str) -> str:
    base = f"{index:02d}_{slug[:90]}"
    candidate = f"{base}.md"
    suffix = 2
    while (out_dir / candidate).exists():
        candidate = f"{base}_{suffix}.md"
        suffix += 1
    return candidate


def title_fingerprint(cluster: dict) -> set[str]:
    text = str(cluster.get("title", ""))
    tokens = re.findall(r"[a-zа-яәғқңөұүһі0-9]+", text.lower())
    stopwords = {
        "the",
        "and",
        "with",
        "after",
        "from",
        "about",
        "news",
        "live",
        "latest",
        "new",
        "says",
        "дейін",
        "және",
        "үшін",
    }
    return {token for token in tokens if len(token) > 2 and token not in stopwords}


def is_article_topic(cluster: dict) -> bool:
    tags = set(cluster.get("tags") or [])
    text = f"{cluster.get('title', '')} {cluster.get('summary', '')}".lower()
    if {"russia", "ukraine"} <= tags:
        return any(word in text for word in ["russia", "ukraine", "putin", "moscow", "kyiv", "kiev"])
    if {"usa", "iran"} <= tags:
        return True
    if {"china", "taiwan"} & tags:
        return True
    if tags & {"nato", "eu", "sanctions", "nuclear", "hormuz", "middle_east", "israel", "gaza", "lebanon", "syria"}:
        return True
    country_terms = {
        "afghanistan",
        "pakistan",
        "sudan",
        "belarus",
        "oman",
        "ecuador",
        "yemen",
        "qatar",
        "doha",
    }
    if tags & {"military", "war", "diplomacy"} and any(term in text for term in country_terms):
        return True
    return False


def is_rejected_article_title(cluster: dict) -> bool:
    title = str(cluster.get("title", "")).lower()
    return any(pattern in title for pattern in REJECTED_TITLE_PATTERNS)


def article_topic(cluster: dict) -> str:
    tags = set(cluster.get("tags") or [])
    if {"russia", "ukraine"} <= tags:
        return "russia_ukraine"
    if {"usa", "iran"} <= tags:
        return "usa_iran"
    if {"china", "taiwan"} & tags:
        return "china_taiwan"
    if tags & {"nato", "eu"}:
        return "nato_eu"
    if tags & {"middle_east", "israel", "gaza", "lebanon", "syria", "hormuz"}:
        return "middle_east"
    return "other"


def is_duplicate_fingerprint(fingerprint: set[str], selected: list[set[str]]) -> bool:
    if not fingerprint:
        return False
    for existing in selected:
        common = fingerprint & existing
        union = fingerprint | existing
        if union and len(common) / len(union) >= 0.55:
            return True
        if len(common) >= 5:
            return True
    return False


def extract_markdown_title(content: str) -> str | None:
    for line in content.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return None


def kazakh_headline(cluster: dict) -> str:
    tags = set(cluster.get("tags") or [])
    title = str(cluster.get("title", "")).lower()
    if {"russia", "ukraine"} <= tags:
        if "refinery" in title or "oil" in title:
            return "Украина соққысынан кейін Ресей инфрақұрылымы назарда"
        return "Ресей мен Украина бағытындағы жаңа әскери оқиға"
    if {"usa", "iran"} <= tags:
        if any(word in title for word in ["attack", "strike", "crossfire", "hostilities"]):
            return "АҚШ пен Иран арасындағы соққы мен келіссөз дауы"
        if "agreement" in title or "talk" in title or "doha" in title:
            return "АҚШ пен Иран келіссөзі қайта назарда"
        return "АҚШ пен Иран арасындағы соққы мен келіссөз дауы"
    if {"china", "taiwan"} & tags:
        return "Қытай мен Тайвань маңындағы жағдай бақылауда"
    if tags & {"nato", "eu"}:
        return "НАТО мен ЕО күн тәртібіндегі қауіпсіздік мәселесі"
    if tags & {"middle_east", "israel", "gaza", "lebanon", "syria", "hormuz"}:
        if "lebanon" in title or "hormuz" in title:
            return "Ливан мен Ормуз маңындағы уақытша бітім сынақта"
        return "Таяу Шығыстағы қауіпсіздік ахуалы"
    if "sanctions" in tags:
        return "Санкциялар төңірегіндегі жаңа қадам"
    return "Геосаяси оқиғаға қысқа шолу"


def importance_text(cluster: dict) -> str:
    tags = set(cluster.get("tags") or [])
    if {"usa", "iran"} <= tags or "hormuz" in tags:
        return "Бұл бағыттағы өзгерістер Парсы шығанағы қауіпсіздігіне, келіссөз процесіне және энергетикалық маршруттарға әсер етуі мүмкін. Егер зымыран, дрон немесе теңіз жолдары туралы жаңа дерек шықса, аймақтық тәуекел қайта бағаланады."
    if {"russia", "ukraine"} <= tags:
        return "Бұл бағыттағы хабарлар соғыс динамикасына, инфрақұрылым қауіпсіздігіне және одақтастардың саяси шешімдеріне әсер етуі мүмкін. Қолда бар дерек шектеулі болса, редакциялық қорытындыны қосымша қолмен тексерген дұрыс."
    if tags & {"nato", "eu"}:
        return "Мұндай оқиғалар қорғаныс жоспарлауына, одақтастардың үйлесіміне және саяси міндеттемелердің орындалуына қатысты. НАТО немесе ЕО деңгейіндегі шешімдер кейінгі әскери және дипломатиялық қадамдарға әсер етуі мүмкін."
    return "Оқиға халықаралық саясат, қауіпсіздік немесе дипломатиялық шешімдер контекстінде маңызды болуы мүмкін. Қолда бар дерек шектеулі болса, редакциялық қорытындыны қосымша қолмен тексерген дұрыс."


def lead_text(cluster: dict, title: str, summary: str) -> str:
    tags = set(cluster.get("tags") or [])
    if summary:
        return f"{summary} Бұл оқиға «{title}» тақырыбымен беріліп, ресми мәлімдемелер мен кейінгі реакцияларды бақылауды қажет етеді."
    if {"usa", "iran"} <= tags:
        return "АҚШ пен Иранға қатысты хабарлар шабуыл, соққы, келіссөз және Ормуз бұғазы қауіпсіздігі төңірегінде шоғырланып отыр. Қосымша мәлімет шектеулі болғандықтан, тараптардың ресми реакциясы маңызды."
    if {"russia", "ukraine"} <= tags:
        return "Ресей мен Украина бағытындағы хабарлар дрон, зымыран соққысы және инфрақұрылым қауіпсіздігі тақырыптарын қайта алға шығарды."
    if tags & {"middle_east", "lebanon", "hormuz", "israel", "gaza"}:
        return "Таяу Шығыстағы соңғы хабарлар уақытша бітімнің беріктігі мен аймақтық қауіпсіздік тәуекелдерін көрсетеді. Дерек аз болса да, оқиға дипломатиялық күн тәртіппен тығыз байланысты."
    return "Қосымша мәлімет шектеулі, бірақ дереккөздер бұл оқиғаны маңызды халықаралық жаңалық ретінде беріп отыр."


def what_happened_text(cluster: dict, title: str, summary: str) -> str:
    tags = set(cluster.get("tags") or [])
    if summary:
        return f"{summary} Қосымша мәлімет шектеулі болса да, оқиғаның негізгі бағыты осы хабарлар арқылы көрінеді."
    if {"usa", "iran"} <= tags:
        return "Дереккөздер АҚШ пен Иран арасындағы жаңа шиеленіс туралы хабарлады. Хабарларда соққы, келіссөздің тоқтауы немесе Ормуз бұғазы қауіпсіздігі сияқты тақырыптар қатар аталады. Қосымша мәлімет шектеулі, сондықтан нақты салдарын бөлек тексеру қажет."
    if {"russia", "ukraine"} <= tags:
        return "Дереккөздер Ресей-Украина бағытындағы әскери оқиға туралы хабарлады. Хабардың өзегінде дрон немесе зымыран соққысы, инфрақұрылым және соғыс динамикасы тұр. Толық көрініс үшін ресми тараптардың мәлімдемесін бақылау керек."
    if tags & {"middle_east", "lebanon", "hormuz", "israel", "gaza"}:
        return "Дереккөздер Таяу Шығыстағы қауіпсіздік ахуалы туралы хабарлады. Негізгі назар уақытша бітім, ықтимал соққы және теңіз жолдары қауіпсіздігіне ауып отыр. Қосымша мәлімет шектеулі болса, ақпаратты сақ бағалау қажет."
    return "Дереккөздер бұл оқиғаны халықаралық саясаттағы маңызды хабар ретінде берді. Қосымша мәлімет шектеулі, сондықтан ақпаратты сақ бағалау қажет."


def next_watch_text(cluster: dict) -> str:
    tags = set(cluster.get("tags") or [])
    if {"usa", "iran"} <= tags or "hormuz" in tags:
        return "Әрі қарай АҚШ, Иран және өңір елдерінің ресми мәлімдемелері, келіссөз туралы сигналдар және Ормуз бұғазы маңындағы қауіпсіздік хабарлары маңызды болады."
    if {"russia", "ukraine"} <= tags:
        return "Әрі қарай соққы салдары, дрон немесе зымыран шабуылдары туралы ресми мәліметтер және одақтастардың реакциясы назарда болады."
    if tags & {"middle_east", "lebanon", "gaza", "israel"}:
        return "Әрі қарай уақытша бітімнің сақталуы, жаңа соққы туралы хабарлар және БҰҰ мен өңір үкіметтерінің мәлімдемелері бақыланады."
    return "Әрі қарай ресми мәлімдемелерді және негізгі тараптардың реакциясын салыстыру қажет. Нақты болжам жасау үшін қосымша расталған дерек керек."


def usable_summary(cluster: dict) -> str:
    summary = str(cluster.get("summary") or "").strip()
    if not summary or summary.startswith("Бірнеше дереккөз") or summary.startswith("Оқиға дереккөздер"):
        return ""
    without_urls = re.sub(r"https?://\S+", "", summary)
    cyrillic_count = len(re.findall(r"[А-Яа-яӘәҒғҚқҢңӨөҰұҮүҺһІі]", without_urls))
    latin_count = len(re.findall(r"[A-Za-z]", without_urls))
    if latin_count > cyrillic_count:
        return ""
    if len(summary) > 260:
        return summary[:259].rstrip() + "..."
    return summary


def natural_sources(cluster: dict) -> str:
    sources = [source for source in cluster.get("sources", [])[:3] if source]
    if not sources:
        return "Дереккөздер"
    if len(sources) == 1:
        return sources[0]
    if len(sources) == 2:
        return f"{sources[0]} және {sources[1]}"
    return f"{sources[0]}, {sources[1]} және {sources[2]}"


def format_sources(cluster: dict) -> list[str]:
    links = [link for link in cluster.get("links", []) if link.get("url")][:6]
    if not links:
        return ["* Сілтеме жоқ"]
    return [f"* {link.get('source', 'source')} — {link['url']}" for link in links]


def slugify(title: str) -> str:
    normalized = re.sub(r"[^\wа-яА-ЯәғқңөұүһіӘҒҚҢӨҰҮҺІ]+", "-", title, flags=re.UNICODE)
    normalized = normalized.strip("-_").lower()
    return normalized[:90] or "maqala"


def yaml_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')
