from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

from app.services.ai_writer import generate_article_text
from app.utils.datetime import today_str


BANNED_PHRASES = {
    "ұшқындар",
    "ғарыштық атқару",
    "шексіз күндері",
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


def generate_kazakh_article(cluster: dict) -> tuple[str | None, str]:
    prompt = build_prompt(cluster)
    text, mode = generate_article_text(prompt)
    if text and is_quality_article(text):
        print(f"[article] жазу режимі: {mode}")
        return clean_ai_article(text), mode

    if text:
        print("[article] AI мәтіні сапа тексерісінен өтпеді; fallback қолданылады")
    print("[article] жазу режимі: fallback")
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
        f"* {link.get('source', 'source')} — {link.get('url', '')}"
        for link in cluster.get("links", [])[:6]
        if link.get("url")
    ]
    sources = ", ".join(cluster.get("sources", [])[:6])
    tags = ", ".join(tag for tag in cluster.get("tags", []) if tag != "untagged")

    return f"""Сен қазақ тілінде қысқа аналитикалық жаңалық мақаласын жазасың.

Тек төмендегі оқиға кластері деректерін қолдан:

title: {cluster.get("title", "")}
summary: {cluster.get("summary", "")}
tags: {tags}
sources: {sources}
links:
{chr(10).join(links)}

Қатаң ережелер:
- Тек title, summary, tags, sources және links деректерін қолдан.
- Full article text жүктеме, сұрама және ойдан қоспа.
- Факт, есім, сан, цитата, орын немесе деталь ойдан шығарма.
- Қазақша жаз; ағылшын title-ды қазақша табиғи тақырыпқа айналдыр.
- 180-250 сөз аралығында жаз.
- Қайталама, бір ойды екі рет айтпа.
- Қажет жерде "шабуыл", "соққы", "зымыран", "дрон", "келіссөз", "уақытша бітім" сияқты нақты сөздерді қолдан.
- Түсініксіз тіркес, калька және мағынасыз аударма қолданба.
- "ұшқындар", "ғарыштық атқару", "шексіз күндері" сияқты мағынасыз тіркестерге тыйым салынады.
- Дерек жетіспесе қысқа әрі сақ жаз.
- Дереккөздер бөлімінде тек берілген source және url жұптарын көрсет.
- YAML front matter қоспа; тек төмендегі Markdown body құрылымын жаз.

Құрылым дәл осылай болсын:

# [қазақша табиғи тақырып]

**Лид:**
2-3 сөйлем.

**Не болды:**
Қысқа түсіндіру.

**Неге маңызды:**
Геосаяси мәні.

**Әрі қарай не күту керек:**
Сақ, факт ойдан шығармайтын 1-2 абзац.

**Дереккөздер:**

* Source — URL
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


def is_quality_article(text: str) -> bool:
    stripped = text.strip()
    if not stripped or any(phrase in stripped.lower() for phrase in BANNED_PHRASES):
        return False
    required = ["# ", "**Лид:**", "**Не болды:**", "**Неге маңызды:**", "**Әрі қарай не күту керек:**", "**Дереккөздер:**"]
    if not all(item in stripped for item in required):
        return False
    if "source + url" in stripped.lower() or "[қазақша" in stripped.lower():
        return False
    text_for_language = re.sub(r"https?://\S+", "", stripped)
    cyrillic_count = len(re.findall(r"[А-Яа-яӘәҒғҚқҢңӨөҰұҮүҺһІі]", text_for_language))
    latin_count = len(re.findall(r"[A-Za-z]", text_for_language))
    if cyrillic_count < 250 or cyrillic_count < latin_count:
        return False
    word_count = len(re.findall(r"\b[\wӘәҒғҚқҢңӨөҰұҮүҺһІі-]+\b", text_for_language))
    return 120 <= word_count <= 320


def clean_ai_article(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("---"):
        parts = stripped.split("---", 2)
        if len(parts) == 3:
            stripped = parts[2].strip()
    return stripped


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
