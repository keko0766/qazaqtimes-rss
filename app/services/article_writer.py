from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path
from typing import Any

from app.services.ai_types import (
    AI_ARTICLE_JSON_FIELDS,
    BAD_KAZAKH_PHRASES,
    AITextResult,
    MIN_EVENT_KEYWORD_OVERLAP,
)
from app.services.ai_writer import generate_article_text
from app.services.relevance import has_china_influence_signal, is_weather_disaster_noise
from app.utils.datetime import today_str
from app.utils.paths import ai_status_path as app_ai_status_path
from app.utils.paths import data_dir as app_data_dir


REQUIRED_JSON_FIELDS = AI_ARTICLE_JSON_FIELDS
MIN_JSON_FIELD_CHARS = 15
MIN_EVENT_KEYWORD_OVERLAP_REQUIRED = MIN_EVENT_KEYWORD_OVERLAP

BULLET_FIELD_PREFIXES = ("- ", "• ")
REQUIRED_MARKDOWN_HEADINGS = (
    "**Лид:**",
    "**Не болды:**",
    "**Неге маңызды:**",
    "**Әрі қарай не күту керек:**",
    "**Дереккөздер:**",
)
TECHNICAL_AI_TERMS = ("cluster", "metadata", "метадерек", "кластер")
EXTRA_BAD_AI_PHRASES = (
    "ұлттық одақ",
    "адамжарлық",
    "азаматты қаза табады",
    "шексіз күндері",
    "ғарыштық атқару",
    "ұшқындар",
    "контекстінде қаралады",
)
GENERIC_FALLBACK_TITLES = {
    "геосаяси оқиғаға қысқа шолу",
    "ресей мен украина бағытындағы жаңа әскери оқиға",
    "қазақстан ішкі саясатындағы жаңа шешім назарда",
    "халықаралық саясаттағы жаңа хабар",
    "жаңа шешім назарда",
}
BROKEN_FALLBACK_PHRASES = (
    "деректеріне қарағанда, Қосымша",
    "Ұлттық Одақ",
    "адамжарлық",
    "кластер",
    "метадерек",
)
HEADING_ALIASES = {
    "lead": {"лид", "кіріспе", "қысқаша", "бастысы", "негізгі ой"},
    "what_happened": {"не болды", "оқиға", "оқиға барысы", "негізгі оқиға", "жағдай"},
    "why_important": {"неге маңызды", "маңызы", "бұл неге маңызды", "неліктен маңызды"},
    "what_next": {
        "әрі қарай не күту керек",
        "келесі қадам",
        "бұдан кейін не болуы мүмкін",
        "не күтіледі",
        "алдағы жағдай",
    },
    "sources": {"дереккөздер", "дерек көздері", "ақпарат көздері", "sources"},
}
CANONICAL_HEADING_BY_FIELD = {
    "lead": "**Лид:**",
    "what_happened": "**Не болды:**",
    "why_important": "**Неге маңызды:**",
    "what_next": "**Әрі қарай не күту керек:**",
    "sources": "**Дереккөздер:**",
}

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
    "china_influence": ["Қытай", "Тайвань"],
    "china_aggression": ["Қытай", "Тайвань"],
    "grey_zone": ["Қытай", "Тайвань"],
    "south_china_sea": ["Қытай", "Оңтүстік Қытай теңізі"],
    "belt_and_road": ["Қытай", "Қазақстан"],
    "tech_geopolitics": ["АҚШ", "Anthropic", "AI", "экспорт"],
    "central_asia": ["Орталық Азия"],
    "kazakhstan": ["Қазақстан"],
    "kazakhstan_politics": ["Қазақстан", "Тоқаев", "парламент"],
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
    "china_influence": ["Қытай", "Тайвань", "қысым", "Орталық Азия", "Қазақстан"],
    "tech_geopolitics": ["АҚШ", "Anthropic", "AI", "экспорт", "бақылау"],
    "kazakhstan_domestic": ["Қазақстан", "Тоқаев", "үкімет", "парламент"],
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
    "chinese": ["Қытай"],
    "beijing": ["Қытай"],
    "taipei": ["Тайвань"],
    "anthropic": ["Anthropic"],
    "ai": ["AI"],
    "export": ["экспорт"],
    "controls": ["бақылау"],
    "chips": ["чип"],
    "semiconductors": ["жартылай өткізгіш"],
    "coercion": ["қысым"],
    "coercive": ["қысым"],
    "influence": ["ықпал"],
    "grey": ["қысым"],
    "gray": ["қысым"],
    "belt": ["Қазақстан"],
    "road": ["Қазақстан"],
    "kazakhstan": ["Қазақстан"],
    "kazakh": ["Қазақстан"],
    "tokayev": ["Тоқаев"],
    "parliament": ["парламент"],
    "government": ["үкімет"],
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
    "morning briefing",
    "evening briefing",
    "daily briefing",
    "what to know",
    "opinion",
    "analysis video",
    "video only",
    "europe live",
    "america first",
    "germany news:",
    "heat wave",
    "temperatures plunge",
    "earthquake relief",
    "what aftermath",
}

EDITORIAL_SLOTS = [
    ("ukraine_russia", "Украина-Ресей"),
    ("middle_east", "Таяу Шығыс"),
    ("tech_geopolitics", "Технологиялық геосаясат"),
    ("china_influence", "Қытайдың агрессиялық ықпалы"),
    ("kazakhstan_domestic", "Қазақстанның ішкі саясаты"),
    ("world_geopolitics", "Жалпы әлемдік геосаяси ахуал"),
]


def select_editorial_article_clusters(clusters: list[dict], limit: int = 5) -> list[dict]:
    selected: list[dict] = []
    fingerprints: list[set[str]] = []

    for slot, slot_label in EDITORIAL_SLOTS:
        cluster = best_cluster_for_slot(clusters, slot, fingerprints)
        if cluster is None:
            print(f"[article] slot missing: {slot}")
            continue
        cluster_with_slot = dict(cluster)
        cluster_with_slot["slot"] = slot
        cluster_with_slot["slot_label"] = slot_label
        if is_kremlin_tokayev_event(cluster_with_slot):
            cluster_with_slot["slot_label"] = "Қазақстан–Ресей"
        selected.append(cluster_with_slot)
        fingerprints.append(title_fingerprint(cluster))
        if len(selected) >= limit:
            break

    return selected


def best_cluster_for_slot(
    clusters: list[dict],
    slot: str,
    selected_fingerprints: list[set[str]],
) -> dict | None:
    candidates = [
        cluster
        for cluster in clusters
        if is_article_topic(cluster)
        and slot_matches_cluster(slot, cluster)
        and not is_rejected_article_title(cluster)
        and not is_weak_article_title(cluster)
        and not is_duplicate_fingerprint(title_fingerprint(cluster), selected_fingerprints)
    ]
    if not candidates:
        return None
    return sorted(candidates, key=editorial_score_key, reverse=True)[0]


def editorial_score_key(cluster: dict) -> tuple[int, int, int]:
    return (
        int(cluster.get("final_score", 0)),
        int(cluster.get("source_count", 0)),
        int(cluster.get("max_source_score", cluster.get("source_score", 0))),
    )


def slot_matches_cluster(slot: str, cluster: dict) -> bool:
    tags = set(cluster.get("tags") or [])
    text = cluster_search_text(cluster)
    if is_weather_disaster_noise(text):
        return False
    if slot == "ukraine_russia":
        return {"russia", "ukraine"} <= tags
    if slot == "middle_east":
        return bool(tags & {"middle_east", "iran", "israel", "gaza", "lebanon", "syria", "hormuz"})
    if slot == "china_influence":
        if is_tech_geopolitics_cluster(cluster) and not china_is_main_actor(cluster):
            return False
        has_china = bool(tags & {"china", "taiwan", "belt_and_road"}) or any(
            keyword in text for keyword in ("china", "chinese", "beijing", "taiwan", "taipei")
        )
        return has_china and has_china_influence_signal(text)
    if slot == "tech_geopolitics":
        return is_tech_geopolitics_cluster(cluster)
    if slot == "kazakhstan_domestic":
        if "kazakhstan_politics" in tags:
            return True
        return "kazakhstan" in tags and any(
            keyword in text
            for keyword in (
                "tokayev",
                "government",
                "parliament",
                "mazhilis",
                "senate",
                "minister",
                "cabinet",
                "domestic politics",
                "political reform",
            )
        )
    if slot == "world_geopolitics":
        return not (
            slot_matches_cluster("ukraine_russia", cluster)
            or slot_matches_cluster("middle_east", cluster)
            or slot_matches_cluster("china_influence", cluster)
            or slot_matches_cluster("tech_geopolitics", cluster)
            or slot_matches_cluster("kazakhstan_domestic", cluster)
        )
    return False


def is_tech_geopolitics_cluster(cluster: dict) -> bool:
    text = cluster_search_text(cluster)
    return any(
        keyword in text
        for keyword in (
            "us export controls",
            "export controls",
            "anthropic",
            "ai models",
            "powerful ai models",
            "ai export",
            "chips",
            "semiconductors",
            "semiconductor",
        )
    )


def china_is_main_actor(cluster: dict) -> bool:
    text = f"{cluster.get('title', '')} {cluster.get('summary', '')}".lower()
    return any(keyword in text for keyword in ("china", "chinese", "beijing", "taiwan", "taipei", "қытай", "тайвань"))


def cluster_search_text(cluster: dict) -> str:
    parts = [str(cluster.get("title", "")), str(cluster.get("summary", ""))]
    for link in cluster.get("links") or []:
        parts.append(str(link.get("title", "")))
        parts.append(str(link.get("source", "")))
    for item in cluster.get("items") or []:
        parts.append(str(item.get("title", "")))
        parts.append(str(item.get("summary", "")))
    return " ".join(parts).lower()


def unique_values(values: list[str]) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        unique.append(value)
    return unique


def generate_kazakh_article(cluster: dict, index: int = 1) -> tuple[str | None, str]:
    facts_prompt = build_facts_prompt(cluster)
    facts_result = generate_article_text(facts_prompt, stage="facts")
    print(f"[ai] provider={facts_result.provider} model={facts_result.model}")
    if facts_result.ollama_available is not None:
        print(f"[ai] ollama available={str(facts_result.ollama_available).lower()}")
    facts = stage_text(facts_result)
    if non_final_stage_failed(facts_result, facts):
        print("[ai] facts=fail")
        return fallback_from_ai_failure(index, cluster, facts_prompt, facts_result, "facts_failed")
    print("[ai] facts=ok")

    outline_prompt = build_outline_prompt(cluster, facts)
    outline_result = generate_article_text(outline_prompt, stage="outline")
    outline = stage_text(outline_result)
    if non_final_stage_failed(outline_result, outline):
        print("[ai] outline=fail")
        return fallback_from_ai_failure(index, cluster, outline_prompt, outline_result, "outline_failed")
    print("[ai] outline=ok")

    article_prompt = build_article_stage_prompt(cluster, facts, outline)
    article_result = generate_article_text(article_prompt, stage="article")
    article_text = stage_text(article_result)
    if not article_text:
        print("[ai] article=fail")
        return fallback_from_ai_failure(index, cluster, article_prompt, article_result, article_result.error_reason or "empty_response")
    print("[ai] article=ok")

    accepted, rendered, sections, reject_reason, quality_details = evaluate_ai_article(article_result, cluster)
    issue_codes = quality_issue_codes(reject_reason, quality_details)
    unsupported_claims = detect_unsupported_claims(rendered or article_text, cluster)
    verified = False
    verify_result: AITextResult | None = None
    verify_codes: list[str] = []
    if accepted:
        verify_prompt = build_verify_prompt(cluster, rendered)
        verify_result = generate_article_text(verify_prompt, stage="verify")
        verified, verify_codes = verification_result(verify_result)
    print(f"[ai] verify={'ok' if accepted and verified else 'fail'}")

    if accepted and verified:
        print("[ai] repair=not_used")
        print("[article] final mode=ai_journalist")
        save_ai_debug(
            index,
            cluster,
            combined_debug_prompt(facts_prompt, outline_prompt, article_prompt),
            article_result,
            sections=sections,
            rendered=rendered,
            used_fallback=False,
            reject_reason=None,
            json_parsed=False,
            quality_details=quality_details,
        )
        return rendered, "ai_journalist"

    if not verified:
        issue_codes = unique_values([*issue_codes, *verify_codes])
    log_rejection_diagnostics(issue_codes, unsupported_claims, reject_reason)

    repair_prompt = build_repair_prompt(
        cluster,
        issue_codes,
        unsupported_claims,
        compact_evidence(cluster, facts),
        rendered or article_text,
    )
    repair_result = generate_article_text(repair_prompt, stage="repair")
    repair_text = stage_text(repair_result)
    print(f"[ai] repair={'used' if repair_text else 'not_used'}")
    if repair_text:
        repair_accepted, repair_rendered, repair_sections, repair_reason, repair_details = evaluate_ai_article(repair_result, cluster)
        repair_issue_codes = quality_issue_codes(repair_reason, repair_details)
        repair_unsupported_claims = detect_unsupported_claims(repair_rendered or repair_text, cluster)
        repair_verify_result: AITextResult | None = None
        repair_verified = False
        repair_verify_codes: list[str] = []
        if repair_accepted:
            repair_verify_result = generate_article_text(build_verify_prompt(cluster, repair_rendered), stage="verify")
            repair_verified, repair_verify_codes = verification_result(repair_verify_result)
            print(f"[ai] verify={'ok' if repair_verified else 'fail'}")
        if repair_accepted and repair_verified:
            print("[article] final mode=ai_repaired")
            save_ai_debug(
                index,
                cluster,
                combined_debug_prompt(facts_prompt, outline_prompt, article_prompt, repair_prompt),
                repair_result,
                sections=repair_sections,
                rendered=repair_rendered,
                used_fallback=False,
                reject_reason=None,
                json_parsed=False,
                quality_details=repair_details,
            )
            return repair_rendered, "ai_repaired"
        if not repair_verified:
            repair_issue_codes = unique_values([*repair_issue_codes, *repair_verify_codes])
        log_rejection_diagnostics(repair_issue_codes, repair_unsupported_claims, repair_reason or verify_failure_reason(repair_verify_result))
        reject_reason = repair_reason or verify_failure_reason(repair_verify_result) or reject_reason

    if article_text.strip():
        print(f"[article] AI мәтіні қолданылмады, fallback; reason={reject_reason}")
    print("[article] final mode=fallback")
    save_ai_debug(
        index,
        cluster,
        combined_debug_prompt(facts_prompt, outline_prompt, article_prompt),
        article_result,
        sections=sections,
        rendered=rendered,
        used_fallback=True,
        reject_reason=reject_reason,
        json_parsed=False,
        quality_details=quality_details,
    )
    return fallback_article(cluster), "fallback"


def stage_text(ai_result: AITextResult) -> str:
    return strip_model_channel_tokens(ai_result.raw_response or ai_result.text or "").strip()


def non_final_stage_failed(ai_result: AITextResult, text: str) -> bool:
    if not text:
        return True
    return bool(ai_result.error_reason and ai_result.error_reason != "finish_reason_length")


def evaluate_ai_article(ai_result: AITextResult, cluster: dict) -> tuple[bool, str, dict | None, str | None, dict]:
    raw_text = ai_result.raw_response or ai_result.text or ""
    sections, parse_reason = parse_ai_article_markdown(raw_text, cluster)
    if not sections:
        print(f"[ai] markdown parsed=false reason={parse_reason}")
        return False, "", None, ai_result.error_reason or parse_reason, empty_quality_details(cluster)

    print("[ai] markdown parsed=true")
    parse_warnings = list(sections.get("_warnings", []))
    rendered = render_structured_article(kazakh_headline(cluster), sections, cluster)
    accepted, reject_reason, quality_details = is_quality_structured_article(
        sections,
        rendered,
        ai_result,
        cluster,
    )
    quality_details.setdefault("warnings", [])
    quality_details["warnings"] = unique_values([*parse_warnings, *quality_details["warnings"]])
    warnings = quality_details.get("warnings", [])
    warning_text = f" warnings={','.join(warnings)}" if accepted and warnings else ""
    print(
        f"[ai] quality accepted={str(accepted).lower()}"
        + (f" reason={reject_reason}" if reject_reason else "")
        + warning_text
    )
    return accepted, rendered, sections, reject_reason, quality_details


def fallback_from_ai_failure(
    index: int,
    cluster: dict,
    prompt: str,
    ai_result: AITextResult,
    reject_reason: str,
) -> tuple[str, str]:
    print(f"[article] AI мәтіні қолданылмады, fallback; reason={reject_reason}")
    print("[ai] verify=fail")
    print("[ai] repair=not_used")
    print("[article] final mode=fallback")
    save_ai_debug(
        index,
        cluster,
        prompt,
        ai_result,
        sections=None,
        rendered="",
        used_fallback=True,
        reject_reason=reject_reason,
        json_parsed=False,
        quality_details=empty_quality_details(cluster),
    )
    return fallback_article(cluster), "fallback"


def verification_result(ai_result: AITextResult | None) -> tuple[bool, list[str]]:
    if ai_result is None:
        return False, ["verify_not_run"]
    if ai_result.error_reason:
        return False, [ai_result.error_reason]
    text = stage_text(ai_result).lower()
    json_result = parse_verify_json(text)
    if json_result is not None:
        result, codes = json_result
        return result == "pass", codes
    first_line = text.splitlines()[0].strip() if text else ""
    codes = parse_verify_issue_codes(text)
    if first_line.startswith("pass") or first_line.startswith("ok"):
        return True, []
    return False, codes or ["verify_failed"]


def parse_verify_json(text: str) -> tuple[str, list[str]] | None:
    extracted = extract_json_object(text)
    if not extracted:
        return None
    try:
        data = json.loads(extracted)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    result = str(data.get("result", "")).strip().lower()
    issues = data.get("issues", [])
    codes: list[str] = []
    if isinstance(issues, list):
        for issue in issues:
            if isinstance(issue, dict):
                code = str(issue.get("code", "")).strip()
            else:
                code = str(issue).strip()
            if code:
                codes.append(code)
    if result not in {"pass", "fail"}:
        return None
    return result, codes


def parse_verify_issue_codes(text: str) -> list[str]:
    known_codes = {
        "missing_heading",
        "unsupported_number",
        "unsupported_name",
        "unsupported_location",
        "unsupported_claim",
        "claim_upgrade",
        "unsupported_specificity",
        "generic_speculation",
        "repeated_sentence",
        "gibberish_text",
        "word_count",
        "source_section",
        "mixed_headline",
        "event_not_mentioned",
    }
    codes: list[str] = []
    for code in known_codes:
        if code in text:
            codes.append(code)
    if not codes and "fail" in text:
        codes.append("verify_failed")
    return sorted(codes)


def verify_failure_reason(ai_result: AITextResult | None) -> str:
    if ai_result is None:
        return "verify_not_run"
    return ai_result.error_reason or "verify_failed"


def combined_debug_prompt(*prompts: str) -> str:
    return "\n\n--- stage ---\n\n".join(prompt for prompt in prompts if prompt)


def build_facts_prompt(cluster: dict) -> str:
    links = source_lines(cluster, limit=5)
    return f"""Event cluster деректерінен тек нақты фактілерді JSON ретінде шығар.

Ереже:
- Ойдан факт қоспа.
- Тек JSON array қайтар.
- Әр entry: {{"text":"...", "certainty":"confirmed|reported|uncertain", "sources":["..."]}}
- talks/negotiations/discussion/proposal/statement/intention/threat/plan сөздерін agreement/deal/treaty/decision/action/attack/completed event деп күшейтпе.
- Егер дереккөз тек талқылау немесе ұсыныс десе, text ішінде де сол деңгей сақталсын.
- Дерек жоқ болса, [] қайтар.

Тақырып: {cluster.get("title", "")}
Түйін: {cluster.get("summary", "")}
Тегтер: {", ".join(cluster.get("tags", [])[:8])}
Дереккөздер:
{chr(10).join(links)}
"""


def build_outline_prompt(cluster: dict, facts: str) -> str:
    return f"""Мына фактілерге сүйеніп қазақша мақала жоспарын жаса.

Құрылым:
- Лид
- Не болды
- Неге маңызды
- Әрі қарай не күту керек

Claim strength ережесі:
- talks != agreement
- negotiations != deal
- proposal != decision
- statement != action
- threat != attack
- plan != completed event

Тақырып: {cluster.get("title", "")}
Фактілер:
{facts}
"""


def build_article_stage_prompt(cluster: dict, facts: str, outline: str) -> str:
    links = source_lines(cluster, limit=5)
    return f"""Сен қазақ тілінде қысқа аналитикалық жаңалық мақаласын жазасың.

Тек берілген фактілерді, жоспарды және дереккөз тізімін қолдан.
Ойдан факт, сан, цитата, дата, адам шығыны немесе тарап реакциясын қоспа.
English title-ды көшірме. Тақырып толық қазақша/кирилл жазылсын.
Claim strength сақталсын:
- confirmed -> тікелей айт.
- reported -> "дереккөздер хабарлағандай" деп сақ жаз.
- uncertain -> сақ тұжырымда немесе қоспа.
- talks/negotiations/discussion/proposal/statement/intention/threat/plan сөздерін agreement/deal/treaty/signed agreement/decision/action/attack/completed event деп күшейтпе.
Глоссарий: UN/United Nations = БҰҰ; Security Council = Қауіпсіздік Кеңесі; Washington = Вашингтон; Strait = бұғаз.
Markdown ғана қайтар. Code block, JSON, түсіндірме жазба.

Құрылым дәл осылай болсын:

# Тақырып

**Лид:**

**Не болды:**

**Неге маңызды:**

**Әрі қарай не күту керек:**

**Дереккөздер:**

Тақырып: {cluster.get("title", "")}
Фактілер:
{facts}

Жоспар:
{outline}

Дереккөздер:
{chr(10).join(links)}
"""


def build_verify_prompt(cluster: dict, article: str) -> str:
    return f"""Мақаланы тексер. Бірінші жолға тек JSON жаз:
{{"result":"PASS","issues":[]}}
немесе
{{"result":"FAIL","issues":[{{"code":"code","sentence":"offending sentence","claim":"unsupported claim"}}]}}

PASS шарттары:
- Мақала қазақша.
- Тақырып mixed English/Russian/Kazakh емес.
- Негізгі оқиға берілген cluster дерегіне сай.
- Ойдан нақты сан, адам шығыны, дата, келісім немесе айыптау қосылмаған.
- Markdown бөлімдері сақталған.
- Claim strength сақталған: talks != agreement; negotiations != deal; proposal != decision; statement != action; threat != attack; plan != completed event.

Тек мына issue code қолдан:
missing_heading, unsupported_number, unsupported_name, unsupported_location,
unsupported_claim, claim_upgrade, unsupported_specificity, generic_speculation,
repeated_sentence, gibberish_text, word_count, source_section, mixed_headline,
event_not_mentioned.

Cluster:
{compact_evidence(cluster, "")}

Мақала:
{article}
"""


def build_repair_prompt(
    cluster: dict,
    issue_codes: list[str],
    unsupported_claims: list[dict[str, str]],
    evidence: str,
    article: str,
) -> str:
    return f"""Мына қазақша мақала draft-ын тек көрсетілген issues бойынша түзет.

Issue codes: {", ".join(issue_codes) if issue_codes else "verify_failed"}
Unsupported claims: {json.dumps(unsupported_claims, ensure_ascii=False)}

Тек compact evidence қолдан. Ойдан факт қоспа.
Fix only listed issues. Keep supported facts.
Do not rewrite the whole article unless necessary.
Do not add new facts.
Егер unsupported strong claim болса, evidence деңгейіндегі сөзге ауыстыр:
- agreement/deal/treaty/signed agreement -> talks/discussion/proposal wording
- decision/action/completed event -> proposal/statement/plan wording
- attack -> threat wording, егер дерек тек threat десе
Егер unsupported_date_claim болса, датаны ғана алып таста; қалған қолдаулы сөйлемді сақта.
Егер unsupported_number/unsupported_name/unsupported_location болса, evidence ішінде жоқ санды, елді, қаланы немесе ұйымды алып таста.
Егер supported qualified number болса, qualifier сақталсын: at least 14 -> кемінде 14; more than 10 -> 10-нан астам; around 20 -> шамамен 20.
Егер unsupported_specificity болса, offending claim ішіндегі күшейтілген сөзді evidence деңгейіне түсір.
Егер unsupported_future_claim болса, нақты уақыт/келесі апта/ай/жоспарланған нәтиже туралы сөйлемді алып таста; орнына "қосымша ресми хабарлар бақыланады" деп сақ жаз.
Егер gibberish_text болса, орысша/ағылшынша кірме сөзді қазақша қалыпты баламаға ауыстыр және мағынасы күмәнді сөйлемді қысқарт.
Глоссарий: ООН емес, БҰҰ; Вашингтон; Ормуз бұғазы; шұғыл сессия.
Тақырып толық қазақша/кирилл болсын, mixed-language headline қолданба.
Құрылым дәл сақталсын:
# Тақырып
**Лид:**
**Не болды:**
**Неге маңызды:**
**Әрі қарай не күту керек:**
**Дереккөздер:**

Compact evidence:
{evidence}

Current article:
{article}
"""


def source_lines(cluster: dict, limit: int = 5) -> list[str]:
    lines = []
    for link in cluster.get("links", [])[:limit]:
        label = link.get("title") or link.get("url") or "Untitled"
        lines.append(f"- {link.get('source', 'source')}: {label} — {link.get('url', '')}")
    return lines or ["- Дереккөз сілтемесі жоқ"]


def compact_evidence(cluster: dict, facts: str) -> str:
    lines = [
        f"Title: {cluster.get('title', '')}",
        f"Summary: {cluster.get('summary', '')}",
        "Facts:",
        facts[:1600],
        "Sources:",
        *source_lines(cluster, limit=5),
    ]
    for item in cluster.get("items", [])[:5]:
        item_summary = str(item.get("summary", "")).strip()
        if item_summary:
            lines.append(f"Source summary: {item_summary}")
    return "\n".join(lines)


def quality_issue_codes(reason: str | None, quality_details: dict | None) -> list[str]:
    codes: list[str] = []
    if reason:
        mapping = {
            "unsupported_agreement_claim": "unsupported_claim",
            "unsupported_claim_upgrade": "claim_upgrade",
            "unsupported_specificity": "unsupported_specificity",
            "unsupported_casualty_claim": "unsupported_number",
            "unsupported_date_claim": "unsupported_claim",
            "unsupported_entity_claim": "unsupported_name",
            "unsupported_policy_claim": "unsupported_claim",
            "unsupported_future_claim": "unsupported_claim",
            "generic_speculation": "generic_speculation",
            "repeated_phrases": "repeated_sentence",
            "low_kazakh_quality": "word_count",
            "english_title": "mixed_headline",
        }
        codes.append(mapping.get(reason, reason))
    checks = (quality_details or {}).get("quality_checks", {})
    for check, ok in checks.items():
        if ok is False:
            codes.append(str(check))
    return unique_values(codes)


def log_rejection_diagnostics(issue_codes: list[str], unsupported_claims: list[dict[str, str]], reason: str | None) -> None:
    print(f"[ai] verify issues={','.join(issue_codes) if issue_codes else 'none'}")
    print(f"[ai] unsupported_claims={len(unsupported_claims)}")
    print(f"[ai] quality reason={reason or 'none'}")


def save_article(
    title: str,
    content: str,
    *,
    index: int,
    mode: str,
    source_count: int,
    replace_today: bool = False,
    date: str | None = None,
    slot: str | None = None,
    slot_label: str | None = None,
) -> Path:
    article_date = date or today_str()
    body = content.rstrip()
    article_title = extract_markdown_title(body) or title
    document = render_document(article_title, body, article_date, source_count, mode, slot, slot_label)

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
    return f"""Қазақша түсінікті draft жаз. Қысқа жаңалық мақаласы керек: 180-260 сөз.

Тек берілген тақырып, түйін, дереккөз атауы және сілтемелерді қолдан.
Ойдан факт қоспа. Нақты сан, адам шығыны, дата, тараптың айыптауы, келісім немесе шабуыл нәтижесі тек input ішінде анық болса ғана жаз.
Әртүрлі source-тағы бөлек оқиғаларды бір факт ретінде біріктірме.
Title қазақша болсын. English title-ды сол күйі көшірме.
Техникалық сөз қолданба: cluster, metadata, метадерек, кластер.
Қолданба: Ұлттық Одақ, ООН, адамжарлық, метадерек, кластер.
Markdown ғана қайтар. Қосымша түсіндірме, JSON немесе code block жазба.

Glossary:
- United Nations / UN = БҰҰ
- humanitarian toll = гуманитарлық салдар / адам шығыны
- civilians = бейбіт тұрғындар
- energy sector / power industry = энергетика саласы / энергетикалық инфрақұрылым
- strikes = соққылар / шабуылдар

Бөлім атауларын дәл осылай жаз:

# Тақырып

**Лид:**

**Не болды:**

**Неге маңызды:**

**Әрі қарай не күту керек:**

**Дереккөздер:**

Берілген тақырып: {cluster.get("title", "")}
Берілген түйін: {cluster.get("summary", "")}
Дереккөздер: {sources}
Сілтемелер:
{chr(10).join(links)}
"""


def fallback_article(cluster: dict) -> str:
    original_title = str(cluster.get("title") or "Геосаяси оқиға").strip()
    headline = event_based_title(cluster)
    sources = natural_sources(cluster)
    summary = usable_summary(cluster)
    event_sentence = safe_event_sentence(headline)
    what_happened = fallback_what_happened(cluster, summary)

    article = "\n".join(
        [
            f"# {headline}",
            "",
            "**Лид:**",
            f"{sources} дерегінше, {event_sentence}.",
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
    validate_fallback_article(cluster, article)
    return article


def render_document(
    title: str,
    body: str,
    date: str,
    source_count: int,
    mode: str,
    slot: str | None = None,
    slot_label: str | None = None,
) -> str:
    frontmatter = [
        "---",
        f'title: "{yaml_escape(title)}"',
        f'date: "{date}"',
        f"source_count: {source_count}",
        f'mode: "{mode}"',
    ]
    if slot:
        frontmatter.append(f'slot: "{yaml_escape(slot)}"')
    if slot_label:
        frontmatter.append(f'slot_label: "{yaml_escape(slot_label)}"')
    frontmatter.extend(["---", "", body, ""])
    return "\n".join(frontmatter)


def parse_ai_article_markdown(raw_text: str, cluster: dict) -> tuple[dict | None, str | None]:
    stripped = clean_ai_article(strip_json_fences(raw_text.strip()))
    if not stripped:
        return None, "empty_response"
    if stripped.startswith("{"):
        return None, "markdown_parse_failed"

    lines = stripped.splitlines()
    warnings: list[str] = []
    title, title_index = extract_ai_title(lines, cluster)
    title, title_warnings = normalize_ai_title(title, cluster)
    warnings.extend(title_warnings)
    fatal_reason = (
        "english_title"
        if is_mostly_english_title(title, cluster) and "event_title_paraphrased" not in title_warnings
        else None
    )
    heading_positions: list[tuple[str, int, bool]] = []
    seen_fields: set[str] = set()
    for index, line in enumerate(lines):
        field, normalized = normalize_heading_line(line)
        if field and field not in seen_fields:
            heading_positions.append((field, index, normalized))
            seen_fields.add(field)

    if heading_positions:
        if any(normalized for _, _, normalized in heading_positions):
            warnings.append("headings_normalized")
        sections: dict[str, Any] = {"title": title, "_warnings": warnings}
        if fatal_reason:
            sections["_fatal_reason"] = fatal_reason
        ordered = sorted(heading_positions, key=lambda item: item[1])
        for position, (field, index, _) in enumerate(ordered):
            start = index + 1
            end = ordered[position + 1][1] if position + 1 < len(ordered) else len(lines)
            value = "\n".join(line.strip() for line in lines[start:end]).strip()
            if field != "sources":
                sections[field] = clean_section_text(value)

        missing = [field for field in REQUIRED_JSON_FIELDS if not sections.get(field)]
        if not missing and title_index <= ordered[0][1]:
            if [field for field, _, _ in ordered[:5]] != list(CANONICAL_HEADING_BY_FIELD):
                warnings.append("headings_normalized")
            sections["_warnings"] = unique_values(warnings)
            return sections, None

    wrapped = auto_wrap_ai_article(stripped, title, cluster)
    if wrapped:
        wrapped["_warnings"] = unique_values([*warnings, "auto_wrapped_missing_headings"])
        if fatal_reason:
            wrapped["_fatal_reason"] = fatal_reason
        return wrapped, None

    return None, "empty_response"


def extract_ai_title(lines: list[str], cluster: dict) -> tuple[str, int]:
    for index, line in enumerate(lines):
        clean_line = line.strip()
        if clean_line.startswith("# "):
            title = clean_line[2:].strip()
            if title and title.lower() not in {"тақырып", "[қысқа тақырып]", "қысқа тақырып"}:
                return title, index
    return event_based_title(cluster), 0


def normalize_ai_title(title: str, cluster: dict) -> tuple[str, list[str]]:
    warnings: list[str] = []
    original_title = str(cluster.get("title") or "").strip().lower()
    latin_count = len(re.findall(r"[A-Za-z]", title))
    cyrillic_count = len(re.findall(r"[А-Яа-яӘәҒғҚқҢңӨөҰұҮүҺһІі]", title))
    if latin_count > cyrillic_count or title.strip().lower() == original_title or fallback_headline_rejected(title):
        title = event_based_title(cluster)
        warnings.append("event_title_paraphrased")
    return title, warnings


def is_mostly_english_title(title: str, cluster: dict) -> bool:
    title = title.strip()
    if not title:
        return False
    original_title = str(cluster.get("title") or "").strip().lower()
    latin_count = len(re.findall(r"[A-Za-z]", title))
    cyrillic_count = len(re.findall(r"[А-Яа-яӘәҒғҚқҢңӨөҰұҮүҺһІі]", title))
    if title.lower() == original_title and latin_count > 0:
        return True
    return latin_count >= 12 and latin_count > cyrillic_count * 2


def normalize_heading_line(line: str) -> tuple[str | None, bool]:
    cleaned = re.sub(r"^[#>\-\*\s]+", "", line.strip())
    cleaned = cleaned.replace("*", "").strip()
    cleaned = cleaned.rstrip(":：").strip().lower()
    if not cleaned:
        return None, False
    for field, aliases in HEADING_ALIASES.items():
        if cleaned in aliases:
            canonical = CANONICAL_HEADING_BY_FIELD[field].replace("*", "").rstrip(":").lower()
            return field, cleaned != canonical
    return None, False


def clean_section_text(text: str) -> str:
    lines = [line.strip() for line in text.splitlines()]
    cleaned = []
    for line in lines:
        if not line:
            continue
        if line.startswith("#"):
            continue
        cleaned.append(normalize_ai_loanwords(line))
    return "\n".join(cleaned).strip()


def normalize_ai_loanwords(text: str) -> str:
    replacements = {
        r"\bООН\b": "БҰҰ",
        r"\bоон\b": "БҰҰ",
        r"\bВасингтон\b": "Вашингтон",
        r"\bвасингтон\b": "Вашингтон",
        r"\bпроливі(?:ндегі)?\b": "бұғазы",
        r"\bпроливіндегі\b": "бұғазындағы",
        r"\bэкстрен\b": "шұғыл",
        r"\bКіргізстан\b": "Қырғызстан",
        r"\bқырғызстаннан \(нато\)\b": "НАТО-дан",
        r"\bҚырғызстаннан \(НАТО\)\b": "НАТО-дан",
    }
    normalized = text
    for pattern, replacement in replacements.items():
        normalized = re.sub(pattern, replacement, normalized)
    return normalized


def auto_wrap_ai_article(text: str, title: str, cluster: dict) -> dict | None:
    body = re.sub(r"^# .*$", "", text, count=1, flags=re.MULTILINE).strip()
    body = remove_known_heading_lines(body)
    paragraphs = [paragraph.strip() for paragraph in re.split(r"\n\s*\n+", body) if paragraph.strip()]
    paragraphs = [paragraph for paragraph in paragraphs if not looks_like_source_list(paragraph)]
    if not paragraphs:
        return None
    combined = "\n\n".join(paragraphs)
    word_count = len(re.findall(r"\b[\wӘәҒғҚқҢңӨөҰұҮүҺһІі-]+\b", combined))
    if word_count < 35:
        return None
    lead = paragraphs[0]
    what_happened = "\n\n".join(paragraphs[1:3]).strip() or safe_event_sentence(title)
    return {
        "title": title or event_based_title(cluster),
        "lead": lead,
        "what_happened": what_happened,
        "why_important": importance_text(cluster),
        "what_next": next_watch_text(cluster),
    }


def remove_known_heading_lines(text: str) -> str:
    kept = []
    for line in text.splitlines():
        if normalize_heading_line(line)[0]:
            continue
        kept.append(line)
    return "\n".join(kept)


def looks_like_source_list(paragraph: str) -> bool:
    lower = paragraph.lower()
    return lower.startswith(("дереккөз", "дерек көз", "ақпарат көз", "sources")) or "http://" in lower or "https://" in lower


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
    article_title = str(sections.get("title") or title).strip()
    return "\n".join(
        [
            f"# {article_title}",
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
    fatal_reason = sections.get("_fatal_reason")
    if fatal_reason:
        quality_details["quality_checks"][fatal_reason] = False
        quality_details["quality_error_sample"] = str(sections.get("title") or "")[:160]
        return False, str(fatal_reason), quality_details

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
        quality_details.setdefault("warnings", []).append("needs_editorial_cleanup")

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
    warnings: list[str] = list(sections.get("_warnings", []))

    for field in REQUIRED_JSON_FIELDS:
        value = sections[field].strip()
        if value.startswith(BULLET_FIELD_PREFIXES):
            warnings.append("needs_editorial_cleanup")
            sections[field] = value.lstrip("-• ").strip()

    bad_phrase = find_bad_kazakh_phrase(combined_lower)
    if bad_phrase:
        quality_details["quality_checks"]["bad_phrase"] = False
        quality_details["bad_phrase_detected"] = bad_phrase
        quality_details["quality_error_sample"] = combined[:160]
        return False, "gibberish_text", quality_details

    technical_term = find_technical_ai_term(combined_lower)
    if technical_term:
        quality_details["quality_checks"]["technical_terms"] = False
        quality_details["quality_error_sample"] = technical_term
        return False, "technical_terms", quality_details

    gibberish_match = find_gibberish_pattern(combined_lower)
    if gibberish_match:
        quality_details["quality_checks"]["gibberish_text"] = False
        quality_details["quality_error_sample"] = gibberish_match[:160]
        return False, "gibberish_text", quality_details

    text_for_language = re.sub(r"https?://\S+", "", combined)
    cyrillic_count = len(re.findall(r"[А-Яа-яӘәҒғҚқҢңӨөҰұҮүҺһІі]", text_for_language))
    latin_count = len(re.findall(r"[A-Za-z]", text_for_language))
    word_count = len(re.findall(r"\b[\wӘәҒғҚқҢңӨөҰұҮүҺһІі-]+\b", text_for_language))
    quality_details["quality_checks"]["cyrillic_ratio"] = cyrillic_count >= 80 and cyrillic_count >= latin_count
    quality_details["quality_checks"]["word_count"] = word_count >= 45
    if cyrillic_count < 80 or cyrillic_count < latin_count or word_count < 45:
        quality_details["quality_error_sample"] = combined[:160]
        return False, "low_kazakh_quality", quality_details
    if word_count < 80:
        warnings.append("weak_kazakh_style")

    overlap, matched_keywords = count_event_keyword_overlap(combined_lower, event_keywords)
    quality_details["event_keyword_overlap"] = overlap
    quality_details["matched_event_keywords"] = matched_keywords
    entity_ok, entity_reason = has_required_event_entities(combined_lower, cluster)
    quality_details["quality_checks"]["event_entities"] = entity_ok
    if not entity_ok:
        quality_details["quality_error_sample"] = combined[:160]
        return False, entity_reason, quality_details
    if overlap < MIN_EVENT_KEYWORD_OVERLAP_REQUIRED:
        warnings.append("event_title_paraphrased")

    unsupported_reason = unsupported_specific_claim_reason(combined, cluster)
    if unsupported_reason:
        quality_details["quality_error_sample"] = combined[:160]
        return False, unsupported_reason, quality_details

    if is_too_generic(combined_lower, overlap):
        quality_details["quality_checks"]["too_generic"] = False
        warnings.append("generic_style")

    repeated, repeated_sample, repeated_count = find_repeated_phrase_detail(combined)
    quality_details["repeated_phrase_sample"] = repeated_sample
    quality_details["repeated_phrase_count"] = repeated_count
    quality_details["quality_checks"]["repeated_phrases"] = not repeated
    if repeated:
        quality_details["quality_error_sample"] = repeated_sample or combined[:160]
        return False, "repeated_phrases", quality_details

    if awkward_sentence(combined):
        warnings.append("awkward_sentence")
    if warnings:
        warnings.append("needs_editorial_cleanup")
    quality_details["warnings"] = unique_values(warnings)
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
        "warnings": [],
    }


def find_bad_kazakh_phrase(text_lower: str) -> str | None:
    for phrase in EXTRA_BAD_AI_PHRASES:
        if phrase in text_lower:
            return phrase
    for phrase in BAD_KAZAKH_PHRASES:
        if phrase in text_lower:
            return phrase
    return None


def find_technical_ai_term(text_lower: str) -> str | None:
    for term in TECHNICAL_AI_TERMS:
        if re.search(rf"(?<![a-zа-яәғқңөұүһі0-9-]){re.escape(term)}(?![a-zа-яәғқңөұүһі0-9-])", text_lower):
            return term
    return None


def has_required_markdown_headings(text: str) -> bool:
    lines = [line.strip() for line in text.splitlines()]
    if not any(line.startswith("# ") and len(line[2:].strip()) >= 4 for line in lines):
        return False
    return all(heading in lines for heading in REQUIRED_MARKDOWN_HEADINGS)


def has_required_event_entities(text_lower: str, cluster: dict) -> tuple[bool, str]:
    title = cluster_search_text(cluster)
    tags = set(cluster.get("tags") or [])
    checks: list[tuple[bool, set[str]]] = []
    is_tech_story = is_tech_geopolitics_cluster(cluster) and not china_is_main_actor(cluster)
    if is_tech_story:
        checks.append((True, {"ақш", "anthropic", "ai", "экспорт"}))
    if "ukraine" in title or "ukraine" in tags:
        checks.append((True, {"украина", "ресей", "бұұ"}))
    if "russia" in title or "russia" in tags:
        checks.append((True, {"ресей", "мәскеу", "путин", "украина"}))
    if "iran" in title or "iran" in tags:
        checks.append((True, {"иран", "ақш", "бахрейн", "кувейт"}))
    if "kazakhstan" in title or "tokayev" in title or "kazakhstan" in tags:
        checks.append((True, {"қазақстан", "тоқаев", "путин"}))
    if "pakistan" in title or "afghanistan" in title:
        checks.append((True, {"пәкістан", "ауғанстан"}))
    if not is_tech_story and ("china" in title or "taiwan" in title or tags & {"china", "taiwan", "china_influence"}):
        checks.append((True, {"қытай", "тайвань"}))
    for _, required_terms in checks:
        if not any(term in text_lower for term in required_terms):
            return False, "event_not_mentioned"
    return True, ""


def unsupported_specific_claim_reason(text: str, cluster: dict) -> str | None:
    claim_upgrades = detect_claim_strength_upgrades(text, cluster)
    if claim_upgrades:
        return "unsupported_claim_upgrade"
    specificity_upgrades = detect_specificity_upgrades(text, cluster)
    if specificity_upgrades:
        return "unsupported_specificity"
    if detect_generic_speculation(text):
        return "generic_speculation"
    source_text = cluster_search_text(cluster)
    text_lower = text.lower()
    if has_unsupported_casualty_claim(text_lower, source_text):
        return "unsupported_casualty_claim"
    if has_unsupported_date_claim(text_lower, source_text):
        return "unsupported_date_claim"
    if has_unsupported_entity_claim(text_lower, source_text):
        return "unsupported_entity_claim"
    if has_unsupported_agreement_claim(text_lower, source_text):
        return "unsupported_agreement_claim"
    if has_unsupported_policy_claim(text_lower, source_text):
        return "unsupported_policy_claim"
    if has_unsupported_future_claim(text_lower, source_text):
        return "unsupported_future_claim"
    return None


def has_unsupported_casualty_claim(text_lower: str, source_text: str) -> bool:
    casualty_patterns = (
        r"\bқаза\b",
        r"\bқаза тап",
        r"\bмерт\b",
        r"\bжарақат",
        r"\bадам шығыны\b",
        r"\bбейбіт тұрғын",
        r"\bkilled\b",
        r"\binjured\b",
        r"\bdead\b",
        r"\bcasualt",
    )
    if not any(re.search(pattern, text_lower) for pattern in casualty_patterns):
        return False
    output_number_claims = extract_qualified_numbers(text_lower)
    if not output_number_claims:
        return False
    source_number_claims = extract_qualified_numbers(source_text)
    return any(claim not in source_number_claims for claim in output_number_claims)


def has_unsupported_date_claim(text_lower: str, source_text: str) -> bool:
    months = "қаңтар|ақпан|наурыз|сәуір|мамыр|маусым|шілде|тамыз|қыркүйек|қазан|қараша|желтоқсан"
    output_dates = set(
        re.findall(
            rf"\b(?:\d{{4}}\s+жылғы\s+)?\d{{1,2}}[\s‑-]*(?:ші\s+)?(?:{months})(?:де|да|те|та)?\b",
            text_lower,
        )
    )
    concrete_durations = extract_concrete_duration_claims(text_lower)
    if not output_dates and not concrete_durations:
        return False
    source_lower = source_text.lower()
    if any(date not in source_lower for date in output_dates):
        return True
    return any(not duration_supported_by_source(duration, source_lower) for duration in concrete_durations)


def extract_concrete_duration_claims(text_lower: str) -> list[tuple[str, str]]:
    number_words = {
        "бір": "one",
        "екі": "two",
        "үш": "three",
        "төрт": "four",
        "бес": "five",
        "алты": "six",
        "жеті": "seven",
        "сегіз": "eight",
        "тоғыз": "nine",
        "он": "ten",
    }
    number_pattern = r"\d+|бір|екі|үш|төрт|бес|алты|жеті|сегіз|тоғыз|он"
    unit_pattern = r"күн|апта|ай|жыл|сағат"
    claims: list[tuple[str, str]] = []
    for match in re.finditer(rf"\b({number_pattern})\s+({unit_pattern})(?:дан|ден|тан|тен)?\s+(?:ішінде|кейін|бұрын)\b", text_lower):
        number, unit = match.group(1), match.group(2)
        normalized_number = number_words.get(number, number)
        claims.append((normalized_number, unit))
    return claims


def duration_supported_by_source(duration: tuple[str, str], source_lower: str) -> bool:
    number, unit = duration
    unit_variants = {
        "күн": ("day", "days", "күн"),
        "апта": ("week", "weeks", "апта"),
        "ай": ("month", "months", "ай"),
        "жыл": ("year", "years", "жыл"),
        "сағат": ("hour", "hours", "сағат"),
    }.get(unit, (unit,))
    number_variants = {
        "one": ("one", "1", "бір"),
        "two": ("two", "2", "екі"),
        "three": ("three", "3", "үш"),
        "four": ("four", "4", "төрт"),
        "five": ("five", "5", "бес"),
        "six": ("six", "6", "алты"),
        "seven": ("seven", "7", "жеті"),
        "eight": ("eight", "8", "сегіз"),
        "nine": ("nine", "9", "тоғыз"),
        "ten": ("ten", "10", "он"),
    }.get(number, (number,))
    return any(number_variant in source_lower and unit_variant in source_lower for number_variant in number_variants for unit_variant in unit_variants)


def has_unsupported_entity_claim(text_lower: str, source_text: str) -> bool:
    entity_sources = {
        "қытай": ("china", "chinese", "beijing", "қытай"),
        "тайвань": ("taiwan", "taipei", "тайвань"),
        "ресей": ("russia", "russian", "moscow", "kremlin", "ресей"),
        "иран": ("iran", "iranian", "иран"),
        "израиль": ("israel", "israeli", "израиль"),
    }
    source_lower = source_text.lower()
    for output_entity, source_terms in entity_sources.items():
        if output_entity in text_lower and not any(term in source_lower for term in source_terms):
            return True
    return False


def has_unsupported_agreement_claim(text_lower: str, source_text: str) -> bool:
    strong_claims = (
        "келісімге қол қойды",
        "келісімдерге қол жеткізу",
        "келісімге қол жеткізу",
        "шартқа қол қойды",
        "мәмілеге келді",
    )
    if not any(claim in text_lower for claim in strong_claims):
        return False
    return not any(claim in source_text for claim in strong_claims)


def detect_unsupported_claims(text: str, cluster: dict) -> list[dict[str, str]]:
    claims: list[dict[str, str]] = []
    for claim in detect_claim_strength_upgrades(text, cluster):
        claims.append(claim)
    for claim in detect_specificity_upgrades(text, cluster):
        claims.append(claim)
    for claim in detect_generic_speculation(text):
        claims.append(claim)
    source_text = cluster_search_text(cluster)
    text_lower = text.lower()
    checks = (
        ("unsupported_casualty_claim", has_unsupported_casualty_claim(text_lower, source_text)),
        ("unsupported_date_claim", has_unsupported_date_claim(text_lower, source_text)),
        ("unsupported_entity_claim", has_unsupported_entity_claim(text_lower, source_text)),
        ("unsupported_agreement_claim", has_unsupported_agreement_claim(text_lower, source_text)),
        ("unsupported_policy_claim", has_unsupported_policy_claim(text_lower, source_text)),
        ("unsupported_future_claim", has_unsupported_future_claim(text_lower, source_text)),
    )
    for code, failed in checks:
        if failed:
            claims.append({"code": code, "claim": code, "evidence": compact_source_evidence(cluster)})
    return claims


def detect_claim_strength_upgrades(text: str, cluster: dict) -> list[dict[str, str]]:
    source_lower = cluster_search_text(cluster)
    output_lower = text.lower()
    checks = (
        (
            "talks_to_agreement",
            ("talk", "talks", "discussion", "debate", "debating", "negotiation", "negotiations", "талқыла"),
            ("agreement", "deal", "treaty", "signed agreement", "келісімге қол", "келісім жас", "мәміле", "шартқа қол"),
        ),
        (
            "negotiations_to_deal",
            ("negotiation", "negotiations", "talk", "talks", "келіссөз"),
            ("deal", "treaty", "мәміле", "шарт"),
        ),
        (
            "discussion_to_decision",
            ("discussion", "debate", "debating", "талқыла"),
            ("decision", "decided", "approved", "adopted", "шешім қабыл", "шешімі", "шешімін", "бекіт", "қабылдады"),
        ),
        (
            "proposal_to_decision",
            ("proposal", "proposed", "ұсыныс", "ұсын"),
            ("decision", "decided", "approved", "adopted", "шешім қабыл", "шешімі", "шешімін", "бекіт", "қабылдады"),
        ),
        (
            "statement_to_action",
            ("statement", "said", "says", "мәлімд", "айтты"),
            ("action", "acted", "implemented", "enforced", "іске асыр", "орындады"),
        ),
        (
            "threat_to_attack",
            ("threat", "threaten", "threatens", "қауіп", "қорқыт"),
            ("attack", "attacked", "strike hit", "шабуыл жасады", "соққы жасады"),
        ),
        (
            "plan_to_completed_event",
            ("plan", "plans", "planned", "жоспар"),
            ("completed", "finished", "done", "аяқталды", "өткізді", "жүзеге асырды"),
        ),
    )
    upgrades: list[dict[str, str]] = []
    for code, weak_terms, strong_terms in checks:
        source_has_weak = any(term in source_lower for term in weak_terms)
        source_has_strong = any(term in source_lower for term in strong_terms)
        output_strong = next((term for term in strong_terms if term in output_lower), "")
        if source_has_weak and output_strong and not source_has_strong:
            upgrades.append(
                {
                    "code": "claim_upgrade",
                    "claim": offending_sentence(output_lower, output_strong),
                    "term": output_strong,
                    "evidence": compact_source_evidence(cluster),
                }
            )
    return upgrades


def detect_specificity_upgrades(text: str, cluster: dict) -> list[dict[str, str]]:
    source_lower = cluster_search_text(cluster)
    output_lower = text.lower()
    checks = (
        (
            "attack_to_artillery_or_missile_attack",
            ("attack", "attacks", "assault", "шабуыл", "соққы"),
            ("artillery attack", "missile attack", "артиллериялық шабуыл", "зымыран шабуылы", "ракеталық шабуыл"),
        ),
        (
            "meeting_to_rescue_measure",
            ("meeting", "session", "кездесу", "отырыс"),
            ("rescue measure", "rescue operation", "құтқару шарасы", "құтқару операциясы"),
        ),
        (
            "discussion_to_official_policy",
            ("discussion", "debate", "debating", "талқылау", "талқылады"),
            ("official policy", "policy decision", "ресми саясат", "саяси шешім"),
        ),
        (
            "concern_to_accusation",
            ("concern", "concerns", "алаңдаушылық", "мазасыздық"),
            ("accusation", "accused", "accuses", "айыптау", "айыптады"),
        ),
    )
    upgrades: list[dict[str, str]] = []
    for label, weak_terms, strong_terms in checks:
        source_has_weak = any(term in source_lower for term in weak_terms)
        source_has_strong = any(term in source_lower for term in strong_terms)
        output_strong = next((term for term in strong_terms if term in output_lower), "")
        if source_has_weak and output_strong and not source_has_strong:
            upgrades.append(
                {
                    "code": "unsupported_specificity",
                    "claim": offending_sentence(output_lower, output_strong),
                    "term": output_strong,
                    "evidence": compact_source_evidence(cluster),
                }
            )
    return upgrades


def detect_generic_speculation(text: str) -> list[dict[str, str]]:
    lower = text.lower()
    phrases = (
        "шешімдер қабылдануы мүмкін",
        "жаңа бағыттар ашуы мүмкін",
        "ұсыныстар немесе декларациялар шығуы мүмкін",
        "декларациялар жариялануы мүмкін",
        "ұсыныстарды қамти алады",
    )
    claims = []
    for phrase in phrases:
        if phrase in lower:
            claims.append(
                {
                    "code": "generic_speculation",
                    "claim": offending_sentence(lower, phrase),
                    "term": phrase,
                    "evidence": "",
                }
            )
    return claims


def offending_sentence(text_lower: str, term: str) -> str:
    for sentence in re.split(r"(?<=[.!?])\s+", text_lower):
        if term in sentence:
            return sentence.strip()[:260]
    index = text_lower.find(term)
    if index == -1:
        return term
    start = max(0, index - 120)
    end = min(len(text_lower), index + len(term) + 120)
    return text_lower[start:end].strip()


def compact_source_evidence(cluster: dict) -> str:
    parts = [str(cluster.get("title", "")), str(cluster.get("summary", ""))]
    for link in cluster.get("links", [])[:3]:
        parts.append(str(link.get("title", "")))
    for item in cluster.get("items", [])[:3]:
        parts.append(str(item.get("summary", "")))
    return normalize_spaces_for_log(" | ".join(part for part in parts if part))[:500]


def normalize_spaces_for_log(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def extract_qualified_numbers(text: str) -> set[tuple[str, str]]:
    claims: set[tuple[str, str]] = set()
    lower = text.lower()
    qualifier_patterns = (
        ("at_least", r"\b(?:at least|кемінде|ең аз дегенде)\s+(\d+(?:[.,]\d+)?)\b"),
        ("more_than", r"\b(?:more than|over|астам|көп)\s+(\d+(?:[.,]\d+)?)\b|\b(\d+(?:[.,]\d+)?)\s*(?:-нан|-нен|-дан|-ден|-тан|-тен)?\s+астам\b"),
        ("around", r"\b(?:around|about|approximately|шамамен|жуық)\s+(\d+(?:[.,]\d+)?)\b"),
    )
    consumed: list[tuple[int, int]] = []
    for qualifier, pattern in qualifier_patterns:
        for match in re.finditer(pattern, lower, flags=re.IGNORECASE):
            number = next(group for group in match.groups() if group)
            claims.add((qualifier, normalize_number(number)))
            consumed.append(match.span())
    for match in re.finditer(r"\b\d+(?:[.,]\d+)?\b", lower):
        if any(start <= match.start() < end for start, end in consumed):
            continue
        claims.add(("exact", normalize_number(match.group(0))))
    return claims


def normalize_number(number: str) -> str:
    return number.replace(",", ".")


def has_unsupported_policy_claim(text_lower: str, source_text: str) -> bool:
    source_lower = source_text.lower()
    policy_claims = (
        (("бұйрық бер", "ordered"), ("order", "ordered", "бұйрық")),
        (("тыйым сал", "banned"), ("ban", "banned", "тыйым")),
        (("қайта аш", "reopened"), ("reopen", "reopened", "қайта аш")),
        (("қатаң бақылау", "бақылау күшей", "strict control continues"), ("strict control", "қатаң бақылау", "бақылау күшей")),
    )
    for output_terms, source_terms in policy_claims:
        if any(term in text_lower for term in output_terms) and not any(term in source_lower for term in source_terms):
            return True
    return False


def has_unsupported_future_claim(text_lower: str, source_text: str) -> bool:
    future_claims = (
        "келесі аптада",
        "жоспарлануда",
        "жариялайды деп",
        "жүзеге асырылуы мүмкін",
        "жаңа кезеңінің басталуы",
        "шешімі санкция",
        "ұсыныстарды қамти алады",
    )
    if not any(claim in text_lower for claim in future_claims):
        return False
    return not any(claim in source_text for claim in future_claims)


def extract_numbers(text: str) -> set[str]:
    return set(re.findall(r"\b\d+(?:[.,]\d+)?\b", text))


def awkward_sentence(text: str) -> bool:
    return any(phrase in text for phrase in ("болып табылады болып", "туралы туралы", "дерек дерек"))


def find_gibberish_pattern(text_lower: str) -> str | None:
    for pattern in GIBBERISH_PATTERNS:
        match = re.search(pattern, text_lower, flags=re.IGNORECASE)
        if match:
            return match.group(0)
    mixed = find_mixed_script_word(text_lower)
    if mixed:
        return mixed
    fragment = find_repeated_fragment(text_lower)
    if fragment:
        return fragment
    broken = find_broken_token(text_lower)
    if broken:
        return broken
    punctuation = find_excessive_punctuation(text_lower)
    if punctuation:
        return punctuation
    if abnormal_non_letter_ratio(text_lower):
        return "abnormal_non_letter_ratio"
    duplicated = find_duplicate_sentence(text_lower)
    if duplicated:
        return duplicated
    return None


def find_mixed_script_word(text: str) -> str | None:
    allowed_latin_words = {"ai", "nato", "bbc", "dw", "un", "us", "usa", "live"}
    for word in re.findall(r"\b[\wӘәҒғҚқҢңӨөҰұҮүҺһІі-]{4,}\b", text):
        compact = word.replace("-", "")
        if compact.lower() in allowed_latin_words:
            continue
        has_latin = bool(re.search(r"[a-z]", compact, flags=re.IGNORECASE))
        has_cyrillic = bool(re.search(r"[а-яәғқңөұүһі]", compact, flags=re.IGNORECASE))
        if has_latin and has_cyrillic:
            return word
    return None


def find_repeated_fragment(text: str) -> str | None:
    for match in re.finditer(r"([а-яәғқңөұүһіa-z]{4,})\1{1,}", text, flags=re.IGNORECASE):
        return match.group(0)
    return None


def find_broken_token(text: str) -> str | None:
    for word in re.findall(r"\b[\wӘәҒғҚқҢңӨөҰұҮүҺһІі-]{16,}\b", text):
        vowels = len(re.findall(r"[аеёиоуыэюяәіөүұaeiou]", word, flags=re.IGNORECASE))
        letters = len(re.findall(r"[a-zа-яәғқңөұүһі]", word, flags=re.IGNORECASE))
        if letters >= 16 and vowels <= 2:
            return word
    return None


def find_excessive_punctuation(text: str) -> str | None:
    match = re.search(r"[!?.,:;]{4,}", text)
    return match.group(0) if match else None


def abnormal_non_letter_ratio(text: str) -> bool:
    compact = re.sub(r"\s+", "", text)
    if len(compact) < 120:
        return False
    letters = len(re.findall(r"[a-zа-яәғқңөұүһі]", compact, flags=re.IGNORECASE))
    return letters / max(len(compact), 1) < 0.55


def find_duplicate_sentence(text: str) -> str | None:
    sentences = [sentence.strip() for sentence in re.split(r"[.!?。]+", text) if len(sentence.strip()) > 40]
    seen: set[str] = set()
    for sentence in sentences:
        normalized = re.sub(r"\s+", " ", sentence)
        if normalized in seen:
            return normalized[:120]
        seen.add(normalized)
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
    stripped = strip_model_channel_tokens(text).strip()
    if stripped.startswith("---"):
        parts = stripped.split("---", 2)
        if len(parts) == 3:
            stripped = parts[2].strip()
    return stripped


def strip_model_channel_tokens(text: str) -> str:
    stripped = text.strip()
    final_marker = "<|channel|>final<|message|>"
    if final_marker in stripped:
        stripped = stripped.split(final_marker)[-1]
    stripped = re.sub(r"<\|[^|]+?\|>", "", stripped)
    return stripped.strip()


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
    write_data_ai_debug(index, ai_result, rendered, decision)
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
        "parsed": bool(sections),
        "accepted": not used_fallback,
        "reason": reject_reason,
        "warnings": details.get("warnings", []),
        "slot": str(cluster.get("slot", "")),
        "title": str(sections.get("title") if sections else cluster.get("title", "")),
        "fields": list(REQUIRED_JSON_FIELDS) if sections else [],
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


def write_data_ai_debug(index: int, ai_result: AITextResult, rendered: str, decision: dict) -> None:
    folder = Path(os.getenv("DATA_DIR", str(app_data_dir()))) / "ai_debug" / today_str()
    folder.mkdir(parents=True, exist_ok=True)
    prefix = f"{index:02d}"
    (folder / f"{prefix}_raw.md").write_text(ai_result.raw_response or "", encoding="utf-8")
    (folder / f"{prefix}_normalized.md").write_text(rendered or "", encoding="utf-8")
    validation = {
        "provider": decision.get("provider"),
        "model": decision.get("model"),
        "parsed": decision.get("parsed"),
        "accepted": decision.get("accepted"),
        "reason": decision.get("reason"),
        "warnings": decision.get("warnings", []),
        "slot": decision.get("slot", ""),
        "title": decision.get("title", ""),
    }
    (folder / f"{prefix}_validation.json").write_text(
        json.dumps(validation, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


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
    return Path(os.getenv("AI_STATUS_PATH", str(app_ai_status_path())))


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
    if is_weather_disaster_noise(cluster_search_text(cluster)):
        return False
    if is_tech_geopolitics_cluster(cluster):
        return True
    if {"russia", "ukraine"} <= tags:
        return any(word in text for word in ["russia", "ukraine", "putin", "moscow", "kyiv", "kiev"])
    if {"usa", "iran"} <= tags:
        return True
    if {"china", "taiwan"} & tags:
        return True
    if tags & {
        "nato",
        "eu",
        "sanctions",
        "nuclear",
        "hormuz",
        "middle_east",
        "israel",
        "gaza",
        "lebanon",
        "syria",
        "china_influence",
        "china_aggression",
        "grey_zone",
        "south_china_sea",
        "belt_and_road",
        "kazakhstan_politics",
    }:
        return True
    if "kazakhstan" in tags and any(
        word in text
        for word in ("tokayev", "government", "parliament", "mazhilis", "senate", "minister", "domestic politics")
    ):
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


def is_weak_article_title(cluster: dict) -> bool:
    title = str(cluster.get("title", "")).strip()
    title_lower = title.lower()
    if len(title) < 18:
        return True
    weak_prefixes = (
        "photos:",
        "video:",
        "watch:",
        "listen:",
        "podcast:",
        "live:",
    )
    if title_lower.startswith(weak_prefixes):
        return True
    weak_exact = {
        "world",
        "asia",
        "china",
        "taiwan",
        "kazakhstan",
        "middle east",
        "latest news",
        "breaking news",
    }
    return title_lower in weak_exact


def article_topic(cluster: dict) -> str:
    tags = set(cluster.get("tags") or [])
    if {"russia", "ukraine"} <= tags:
        return "russia_ukraine"
    if {"usa", "iran"} <= tags:
        return "usa_iran"
    if is_tech_geopolitics_cluster(cluster) and not china_is_main_actor(cluster):
        return "tech_geopolitics"
    if tags & {"china_influence", "china_aggression", "grey_zone", "south_china_sea", "belt_and_road"}:
        return "china_influence"
    if {"china", "taiwan"} & tags:
        return "china_taiwan"
    if "kazakhstan_politics" in tags:
        return "kazakhstan_domestic"
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


def event_based_title(cluster: dict) -> str:
    original = str(cluster.get("title") or "").strip()
    text = cluster_search_text(cluster)
    if is_tech_geopolitics_cluster(cluster) and "anthropic" in text:
        return "АҚШ Anthropic AI модельдеріне қатысты экспорттық бақылауды жеңілдетті"
    if "un details humanitarian toll" in text and ("ukrainian power" in text or "power industry" in text):
        return "БҰҰ Украина энергетикасына жасалған соққылардың гуманитарлық салдарын атады"
    if is_kremlin_tokayev_event(cluster):
        return "Путин мен Тоқаев телефон арқылы сөйлесті"
    if "pakistan" in text and "afghanistan" in text and ("militant" in text or "target" in text or "strike" in text):
        return "Пәкістан Ауғанстандағы содырлар нысандарына соққы жасағанын мәлімдеді"
    if "iran" in text and (("bahrain" in text and "kuwait" in text) or "talks" in text or "us strikes" in text):
        return "Иран, Бахрейн, Кувейт және келіссөз дауы"
    mapped = conservative_kazakh_title(original, cluster)
    if mapped.lower() in GENERIC_FALLBACK_TITLES:
        mapped = kazakh_headline(cluster)
    if fallback_headline_rejected(mapped):
        mapped = kazakh_headline(cluster)
    if mapped != original:
        print(f"[fallback] title normalized: {mapped}")
    return mapped


def conservative_kazakh_title(title: str, cluster: dict) -> str:
    if not title or fallback_headline_rejected(title):
        return kazakh_headline(cluster)
    return title.strip()


def fallback_headline_rejected(title: str) -> bool:
    stripped = title.strip()
    if not stripped:
        return True
    latin_count = len(re.findall(r"[A-Za-z]", stripped))
    cyrillic_count = len(re.findall(r"[А-Яа-яӘәҒғҚқҢңӨөҰұҮүҺһІі]", stripped))
    if latin_count >= 8 and latin_count > cyrillic_count:
        return True
    has_latin_words = bool(re.search(r"\b[A-Za-z]{3,}\b", stripped))
    has_cyrillic = cyrillic_count > 0
    return has_latin_words and has_cyrillic and latin_count > cyrillic_count // 2


def is_kremlin_tokayev_event(cluster: dict) -> bool:
    text = cluster_search_text(cluster)
    sources = " ".join(cluster.get("sources") or []).lower()
    return (
        ("kremlin" in sources or "kremlin" in text)
        and ("tokayev" in text or "kazakhstan" in text)
        and ("telephone conversation" in text or "phone" in text)
    )


def safe_event_sentence(title: str) -> str:
    title = title.rstrip(".")
    return title if title else "дереккөз оқиғаны қысқа хабар ретінде берді"


def fallback_what_happened(cluster: dict, summary: str) -> str:
    if is_tech_geopolitics_cluster(cluster) and "anthropic" in cluster_search_text(cluster):
        return "France 24 АҚШ-тың Anthropic AI модельдеріне қатысты экспорттық бақылауды жеңілдетуі туралы хабарлады. Қолда бар дерек осы қысқа хабармен шектеледі, сондықтан нақты шешім тәртібі мен кейінгі саясат туралы қосымша ресми түсіндірме қажет."
    if summary:
        return f"{summary} Нақты салдары мен тараптардың түсіндірмесін қосымша дереккөздер арқылы тексеру қажет."
    return "Дереккөз оқиғаны қысқа хабар ретінде берді. Қосымша мәлімет шектеулі, сондықтан нақты салдары мен тараптардың түсіндірмесін бөлек тексеру қажет."


def validate_fallback_article(cluster: dict, article: str) -> None:
    title = extract_markdown_title(article) or ""
    title_lower = title.lower()
    if title_lower in GENERIC_FALLBACK_TITLES:
        print(f"[fallback] warning: generic title remains: {title}")
    if fallback_headline_rejected(title):
        print(f"[fallback] warning: mixed or high-latin title rejected: {title}")
    for phrase in BROKEN_FALLBACK_PHRASES:
        if phrase in article:
            print(f"[fallback] warning: broken phrase detected: {phrase}")
    body_lower = article.lower()
    source_names = [source.lower() for source in cluster.get("sources") or [] if source]
    if source_names and not any(source in body_lower for source in source_names):
        print("[fallback] warning: source name missing")
    if not fallback_has_main_entity(cluster, body_lower):
        print("[fallback] warning: main entity missing")
    if not fallback_preserves_event_anchor(cluster, article):
        print("[fallback] warning: event anchor missing")


def fallback_has_main_entity(cluster: dict, body_lower: str) -> bool:
    text = cluster_search_text(cluster)
    if is_tech_geopolitics_cluster(cluster):
        return all(term in body_lower for term in ("ақш", "anthropic", "ai", "экспорт"))
    if "ukraine" in text or "russia" in text:
        return "украина" in body_lower or "ресей" in body_lower
    if "iran" in text:
        return "иран" in body_lower or "ақш" in body_lower
    if "tokayev" in text or "kazakhstan" in text:
        return any(term in body_lower for term in ("қазақстан", "тоқаев", "путин"))
    if "pakistan" in text or "afghanistan" in text:
        return "пәкістан" in body_lower or "ауғанстан" in body_lower
    return True


def fallback_preserves_event_anchor(cluster: dict, article: str) -> bool:
    evidence = cluster_search_text(cluster)
    article_lower = article.lower()
    if china_missile_test_event(evidence):
        has_china = "қытай" in article_lower
        has_missile = any(term in article_lower for term in ("зымыран", "ракета", "сынақ"))
        taiwan_injected = "тайвань" in article_lower and "taiwan" not in evidence and "тайвань" not in evidence
        return has_china and has_missile and not taiwan_injected
    return True


def kazakh_headline(cluster: dict) -> str:
    tags = set(cluster.get("tags") or [])
    title = str(cluster.get("title", "")).lower()
    text = cluster_search_text(cluster)
    if is_tech_geopolitics_cluster(cluster):
        return "АҚШ Anthropic AI модельдеріне қатысты экспорттық бақылауды жеңілдетті"
    if "belarus" in text and ("putin" in text or {"russia", "ukraine"} & tags):
        return "Беларусь Ресей мен Украина соғысының қысымында қалды"
    if china_missile_test_event(text):
        if "nuclear" in text or "deterrence" in text or "ядролық" in text:
            return "Қытайдың Тынық мұхитындағы зымыран сынағы ядролық тежеу контекстінде қаралды"
        return "Қытайдың Тынық мұхитындағы зымыран сынағы назарда"
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
        if tags & {"china_influence", "china_aggression", "grey_zone", "south_china_sea", "belt_and_road"}:
            if "taiwan" not in text and "тайвань" not in text:
                return "Қытай ықпалы мен аймақтық қауіпсіздік мәселесі назарда"
            return "Қытай ықпалы мен Тайвань маңындағы қысым назарда"
        if "taiwan" not in text and "тайвань" not in text:
            return "Қытайға қатысты қауіпсіздік мәселесі бақылауда"
        return "Қытай мен Тайвань маңындағы жағдай бақылауда"
    if "kazakhstan_politics" in tags or ("kazakhstan" in tags and any(word in title for word in ["tokayev", "government", "parliament"])):
        return "Қазақстан ішкі саясатындағы жаңа шешім назарда"
    if tags & {"nato", "eu"}:
        return "НАТО мен ЕО күн тәртібіндегі қауіпсіздік мәселесі"
    if tags & {"middle_east", "israel", "gaza", "lebanon", "syria", "hormuz"}:
        if "lebanon" in title or "hormuz" in title:
            return "Ливан мен Ормуз маңындағы уақытша бітім сынақта"
        return "Таяу Шығыстағы қауіпсіздік ахуалы"
    if "sanctions" in tags:
        return "Санкциялар төңірегіндегі жаңа қадам"
    return "Геосаяси оқиғаға қысқа шолу"


def china_missile_test_event(text: str) -> bool:
    has_china = any(term in text for term in ("china", "chinese", "beijing", "қытай"))
    has_missile = any(term in text for term in ("missile", "ballistic", "icbm", "зымыран", "ракета"))
    has_test = any(term in text for term in ("test", "test-fire", "test-fires", "сынақ", "сынады"))
    return has_china and has_missile and has_test


def importance_text(cluster: dict) -> str:
    tags = set(cluster.get("tags") or [])
    text = cluster_search_text(cluster)
    if is_tech_geopolitics_cluster(cluster):
        return "Бұл хабар AI модельдері мен экспорттық бақылаудың технологиялық геосаясаттағы орнына қатысты маңызды. Қолда бар дерек шектеулі болғандықтан, шешімнің нақты тәртібі мен ықтимал салдары ресми түсіндірмелер арқылы нақтылануы керек."
    if is_kremlin_tokayev_event(cluster):
        return "Бұл хабар Қазақстан мен Ресей арасындағы дипломатиялық байланыс ретінде маңызды. Нақты мазмұны дереккөздегі қысқа хабармен шектеледі, сондықтан қосымша мәлімдемелерді бөлек бақылау қажет."
    if "pakistan" in text and "afghanistan" in text:
        return "Бұл хабар Пәкістан мен Ауғанстан арасындағы қауіпсіздік тәуекелдерін көрсетеді. Оқиғаның салдары мен тараптардың түсіндірмесі қосымша дереккөздер арқылы нақтылануы керек."
    if {"usa", "iran"} <= tags or "hormuz" in tags:
        return "Бұл бағыттағы өзгерістер Парсы шығанағы қауіпсіздігіне, келіссөз процесіне және энергетикалық маршруттарға әсер етуі мүмкін. Егер зымыран, дрон немесе теңіз жолдары туралы жаңа дерек шықса, аймақтық тәуекел қайта бағаланады."
    if {"russia", "ukraine"} <= tags:
        return "Бұл бағыттағы хабарлар соғыс динамикасына, инфрақұрылым қауіпсіздігіне және одақтастардың саяси шешімдеріне әсер етуі мүмкін. Қолда бар дерек шектеулі болса, редакциялық қорытындыны қосымша қолмен тексерген дұрыс."
    if tags & {"china_influence", "china_aggression", "grey_zone", "south_china_sea", "belt_and_road"} or {"china", "taiwan"} & tags:
        if china_missile_test_event(text):
            return "Бұл бағыт Қытайдың зымыран сынақтары мен Тынық мұхитындағы әскери-ядролық тепе-теңдікке қатысты маңызды. Ресми мәлімдемелер мен өңір елдерінің реакциясын бөлек тексеру қажет."
        if "taiwan" not in text and "тайвань" not in text:
            return "Бұл бағыт Қытайдың аймақтық ықпалы, әскери белсенділігі және экономикалық-саяси қысым құралдарын бағалау үшін маңызды. Ресми мәлімдемелер мен нақты әскери немесе экономикалық қадамдарды бөлек тексеру қажет."
        return "Бұл бағыт Қытайдың аймақтағы қысым құралдарын, Тайвань қауіпсіздігін және Орталық Азиядағы экономикалық-саяси ықпалын бағалауға маңызды. Ресми мәлімдемелер мен нақты әскери немесе экономикалық қадамдарды бөлек тексеру қажет."
    if "kazakhstan_politics" in tags or "kazakhstan" in tags:
        return "Қазақстан ішкі саясатындағы мұндай хабарлар мемлекеттік басқару, парламент жұмысы және реформалардың орындалуы тұрғысынан маңызды. Ақпаратты ресми дереккөздермен және бірнеше тәуелсіз хабармен салыстырып бағалау керек."
    if tags & {"nato", "eu"}:
        return "Мұндай оқиғалар қорғаныс жоспарлауына, одақтастардың үйлесіміне және саяси міндеттемелердің орындалуына қатысты. НАТО немесе ЕО деңгейіндегі шешімдер кейінгі әскери және дипломатиялық қадамдарға әсер етуі мүмкін."
    return "Оқиға халықаралық саясат, қауіпсіздік немесе дипломатиялық шешімдер контекстінде маңызды болуы мүмкін. Қолда бар дерек шектеулі болса, редакциялық қорытындыны қосымша қолмен тексерген дұрыс."


def lead_text(cluster: dict, title: str, summary: str) -> str:
    tags = set(cluster.get("tags") or [])
    if summary:
        return f"{summary} Бұл оқиға «{title}» тақырыбымен беріліп, ресми мәлімдемелер мен кейінгі реакцияларды бақылауды қажет етеді."
    if is_tech_geopolitics_cluster(cluster):
        return "France 24 АҚШ, Anthropic AI модельдері және экспорттық бақылау туралы қысқа хабар жариялады. Дерек шектеулі болғандықтан, мәтін тек берілген ақпаратқа сүйенеді."
    if {"usa", "iran"} <= tags:
        return "АҚШ пен Иранға қатысты хабарлар шабуыл, соққы, келіссөз және Ормуз бұғазы қауіпсіздігі төңірегінде шоғырланып отыр. Қосымша мәлімет шектеулі болғандықтан, тараптардың ресми реакциясы маңызды."
    if {"russia", "ukraine"} <= tags:
        return "Ресей мен Украина бағытындағы хабарлар дрон, зымыран соққысы және инфрақұрылым қауіпсіздігі тақырыптарын қайта алға шығарды."
    if tags & {"china_influence", "china_aggression", "grey_zone", "south_china_sea", "belt_and_road"} or {"china", "taiwan"} & tags:
        evidence_text = cluster_search_text(cluster)
        if china_missile_test_event(evidence_text):
            return "Қытайдың зымыран сынағы туралы хабар Тынық мұхитындағы қауіпсіздік пен ядролық тежеу тақырыбын алға шығарды."
        if "taiwan" not in evidence_text and "тайвань" not in evidence_text:
            return "Қытайға қатысты хабарлар аймақтық қауіпсіздік, әскери белсенділік және экономикалық-саяси ықпал тақырыптарын алға шығарады."
        return "Қытай мен Тайваньға немесе Қытайдың аймақтық ықпалына қатысты хабарлар әскери қысым, grey-zone тактикасы, теңіз даулары және экономикалық тәуелділік тақырыптарын алға шығарады."
    if "kazakhstan_politics" in tags or "kazakhstan" in tags:
        return "Қазақстанға қатысты хабар ішкі саяси шешімдер, үкімет жұмысы немесе парламент күн тәртібімен байланысты. Қосымша мәлімет шектеулі болса, ресми түсіндірме мен кейінгі реакцияны бақылау қажет."
    if tags & {"middle_east", "lebanon", "hormuz", "israel", "gaza"}:
        return "Таяу Шығыстағы соңғы хабарлар уақытша бітімнің беріктігі мен аймақтық қауіпсіздік тәуекелдерін көрсетеді. Дерек аз болса да, оқиға дипломатиялық күн тәртіппен тығыз байланысты."
    return "Қосымша мәлімет шектеулі, бірақ дереккөздер бұл оқиғаны маңызды халықаралық жаңалық ретінде беріп отыр."


def what_happened_text(cluster: dict, title: str, summary: str) -> str:
    tags = set(cluster.get("tags") or [])
    if summary:
        return f"{summary} Қосымша мәлімет шектеулі болса да, оқиғаның негізгі бағыты осы хабарлар арқылы көрінеді."
    if is_tech_geopolitics_cluster(cluster):
        return "Дереккөз АҚШ-тың Anthropic AI модельдеріне қатысты экспорттық бақылауды жеңілдетуі туралы хабарлады. Қосымша нақты дерек болмағандықтан, бұдан артық саяси немесе әскери қорытынды жасалмайды."
    if {"usa", "iran"} <= tags:
        return "Дереккөздер АҚШ пен Иран арасындағы жаңа шиеленіс туралы хабарлады. Хабарларда соққы, келіссөздің тоқтауы немесе Ормуз бұғазы қауіпсіздігі сияқты тақырыптар қатар аталады. Қосымша мәлімет шектеулі, сондықтан нақты салдарын бөлек тексеру қажет."
    if {"russia", "ukraine"} <= tags:
        return "Дереккөздер Ресей-Украина бағытындағы әскери оқиға туралы хабарлады. Хабардың өзегінде дрон немесе зымыран соққысы, инфрақұрылым және соғыс динамикасы тұр. Толық көрініс үшін ресми тараптардың мәлімдемесін бақылау керек."
    if tags & {"china_influence", "china_aggression", "grey_zone", "south_china_sea", "belt_and_road"} or {"china", "taiwan"} & tags:
        evidence_text = cluster_search_text(cluster)
        if china_missile_test_event(evidence_text):
            return "Дереккөздер Қытайдың Тынық мұхиты бағытындағы зымыран сынағы туралы хабарлады. Толық қорытынды жасау үшін сынақ туралы ресми түсіндірмелер мен өңір елдерінің реакциясын салыстыру керек."
        if "taiwan" not in evidence_text and "тайвань" not in evidence_text:
            return "Дереккөздер Қытайдың аймақтық ықпалы немесе қауіпсіздікке қатысты қадамы туралы хабарлады. Толық қорытынды жасау үшін Бейжің және өңір үкіметтерінің ресми ұстанымын салыстыру керек."
        return "Дереккөздер Қытайдың Тайваньға, теңіз аймақтарына немесе Орталық Азияға қатысты қысым және ықпал құралдары туралы хабарлады. Толық қорытынды жасау үшін Бейжің, Тайбэй және өңір үкіметтерінің ресми ұстанымын салыстыру керек."
    if "kazakhstan_politics" in tags or "kazakhstan" in tags:
        return "Дереккөздер Қазақстан ішкі саясатына қатысты жаңа хабар жариялады. Хабар үкімет, парламент немесе президент әкімшілігі деңгейіндегі шешімдермен байланысты болуы мүмкін, сондықтан нақты құжат пен ресми түсіндірмені бақылау қажет."
    if tags & {"middle_east", "lebanon", "hormuz", "israel", "gaza"}:
        return "Дереккөздер Таяу Шығыстағы қауіпсіздік ахуалы туралы хабарлады. Негізгі назар уақытша бітім, ықтимал соққы және теңіз жолдары қауіпсіздігіне ауып отыр. Қосымша мәлімет шектеулі болса, ақпаратты сақ бағалау қажет."
    return "Дереккөздер бұл оқиғаны халықаралық саясаттағы маңызды хабар ретінде берді. Қосымша мәлімет шектеулі, сондықтан ақпаратты сақ бағалау қажет."


def next_watch_text(cluster: dict) -> str:
    tags = set(cluster.get("tags") or [])
    text = cluster_search_text(cluster)
    if is_tech_geopolitics_cluster(cluster):
        return "Әрі қарай АҚШ ведомстволарының, Anthropic компаниясының және ресми құжаттардың қосымша түсіндірмелері бақыланады. Қазір мәтін дереккөзде берілген қысқа хабармен ғана шектеледі."
    if is_kremlin_tokayev_event(cluster):
        return "Әрі қарай Ақорда мен Кремльдің қосымша түсіндірмелері және екіжақты күн тәртібіне қатысты ресми хабарлар бақыланады."
    if "pakistan" in text and "afghanistan" in text:
        return "Әрі қарай Исламабад пен Кабулдың ресми мәлімдемелері, шекара маңындағы қауіпсіздік хабарлары және тәуелсіз дереккөздердің растауы маңызды болады."
    if {"usa", "iran"} <= tags or "hormuz" in tags:
        return "Әрі қарай АҚШ, Иран және өңір елдерінің ресми мәлімдемелері, келіссөз туралы сигналдар және Ормуз бұғазы маңындағы қауіпсіздік хабарлары маңызды болады."
    if {"russia", "ukraine"} <= tags:
        return "Әрі қарай соққы салдары, дрон немесе зымыран шабуылдары туралы ресми мәліметтер және одақтастардың реакциясы назарда болады."
    if tags & {"china_influence", "china_aggression", "grey_zone", "south_china_sea", "belt_and_road"} or {"china", "taiwan"} & tags:
        if china_missile_test_event(text):
            return "Әрі қарай Қытайдың ресми түсіндірмелері, өңір елдерінің реакциясы және Тынық мұхитындағы қауіпсіздікке қатысты қосымша расталған деректер бақыланады."
        if "taiwan" not in text and "тайвань" not in text:
            return "Әрі қарай Бейжіңнің реакциясы, әскери белсенділік, санкциялық немесе экономикалық қысым белгілері және өңір үкіметтерінің ұстанымы бақыланады."
        return "Әрі қарай Бейжің мен Тайбэйдің реакциясы, әскери белсенділік, санкциялық немесе экономикалық қысым белгілері және Орталық Азия үкіметтерінің ұстанымы бақыланады."
    if "kazakhstan_politics" in tags or "kazakhstan" in tags:
        return "Әрі қарай Ақорда, үкімет, парламент және негізгі саяси акторлардың ресми шешімдері мен түсіндірмелері маңызды болады."
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
