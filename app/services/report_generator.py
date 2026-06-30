from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from app.services.ai_writer import generate_article_text
from app.services.event_clusterer import cluster_events
from app.services.ollama_writer import build_prompt as build_draft_prompt
from app.services.topic_score import (
    is_china_taiwan,
    is_usa_iran,
    is_weak_gdelt_summary,
)
from app.utils.datetime import today_str


TOPIC_RULES = {
    "Ресей / Украина": {"russia", "ukraine"},
    "АҚШ / Иран": {"usa", "iran"},
    "Қытай / Тайвань": {"china", "taiwan"},
    "НАТО / ЕО": {"nato", "eu"},
    "Таяу Шығыс": {"middle_east", "iran", "israel", "gaza", "lebanon", "syria", "hormuz"},
}


def generate_report(items: list[dict], output_dir: str | Path) -> Path:
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    today = today_str()
    path = out_dir / f"digest_{today}.md"

    clusters = cluster_events(items)
    top_clusters = select_top_clusters(clusters)
    topic_clusters = select_topic_clusters(clusters)

    lines: list[str] = [
        f"# Геосаяси дайджест — {today}",
        "",
        "## Негізгі жаңалықтар",
        "",
        *build_headlines(top_clusters),
        "",
        "## Басты оқиғалар",
        "",
        *build_top_events(top_clusters),
        "",
        "## Бағыттар бойынша",
        "",
        *build_topic_sections(topic_clusters),
        "",
        "## Мақала жобалары",
        "",
        *build_draft_articles(top_clusters),
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    print(f"[report] жасалды: {path}")
    return path


def select_top_clusters(clusters: list[dict]) -> list[dict]:
    return [
        cluster
        for cluster in clusters
        if int(cluster.get("final_score", 0)) >= 25
        and is_report_topic(cluster)
    ][:12]


def select_topic_clusters(clusters: list[dict]) -> list[dict]:
    return [
        cluster
        for cluster in clusters
        if int(cluster.get("final_score", 0)) >= 20
        and is_report_topic(cluster)
    ][:20]


def is_report_topic(cluster: dict) -> bool:
    tags = set(cluster.get("tags") or [])
    text = cluster_text(cluster)
    if {"russia", "ukraine"} <= tags:
        return True
    if is_usa_iran(tags):
        return True
    if is_china_taiwan(tags, text):
        return True
    if tags & {"nato", "eu"}:
        return True
    if tags & TOPIC_RULES["Таяу Шығыс"]:
        return True
    return "sanctions" in tags and bool(tags & {"usa", "iran", "russia", "ukraine", "china", "nato", "eu"})


def build_headlines(clusters: list[dict]) -> list[str]:
    if not clusters:
        return ["- Дайджестке кіретін жеткілікті маңызды оқиғалар жоқ."]

    lines = []
    for cluster in clusters[:8]:
        topic = human_topic(cluster)
        sources = ", ".join(cluster["sources"][:3])
        lines.append(f"- {topic}: {cluster['title']} ({sources}).")
    return lines


def build_top_events(clusters: list[dict]) -> list[str]:
    if not clusters:
        return ["Дерек жоқ."]

    lines: list[str] = []
    for cluster in clusters:
        lines.extend(render_event_block(cluster, heading_level=3))
        lines.append("")
    return lines


def build_topic_sections(clusters: list[dict]) -> list[str]:
    grouped = group_clusters_by_topic(clusters)
    lines: list[str] = []
    for section in TOPIC_RULES:
        lines.extend([f"### {section}", ""])
        section_clusters = grouped.get(section, [])[:8]
        if not section_clusters:
            lines.extend(["- Сақталған іріктемеде айқын оқиға жоқ.", ""])
            continue
        for cluster in section_clusters:
            sources = ", ".join(cluster["sources"][:3])
            tags = format_tags(cluster)
            lines.append(f"- **{cluster['title']}** — {short_summary(cluster)}")
            lines.append(f"  Тегтер: {tags}. Дереккөздер: {sources}.")
            lines.append(f"  Сілтемелер: {format_links(cluster, limit=3)}")
        lines.append("")
    return lines


def group_clusters_by_topic(clusters: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for cluster in clusters:
        tags = set(cluster.get("tags") or [])
        text = cluster_text(cluster)
        if {"russia", "ukraine"} <= tags:
            grouped["Ресей / Украина"].append(cluster)
        if is_usa_iran(tags):
            grouped["АҚШ / Иран"].append(cluster)
        if is_china_taiwan(tags, text):
            grouped["Қытай / Тайвань"].append(cluster)
        if tags & {"nato", "eu"}:
            grouped["НАТО / ЕО"].append(cluster)
        if tags & TOPIC_RULES["Таяу Шығыс"]:
            grouped["Таяу Шығыс"].append(cluster)
    return grouped


def render_event_block(cluster: dict, heading_level: int = 3) -> list[str]:
    marker = "#" * heading_level
    links = [link for link in cluster["links"] if link.get("url")][:5]
    return [
        f"{marker} Оқиға: {cluster['title']}",
        "",
        f"Қысқаша түйін: {short_summary(cluster)}",
        "",
        f"Тегтер: {format_tags(cluster)}",
        "",
        "Дереккөздер:",
        *[f"- {source}" for source in cluster["sources"][:5]],
        "",
        "Сілтемелер:",
        *[f"- [{link_label(link)}]({link['url']})" for link in links],
    ]


def build_draft_articles(clusters: list[dict]) -> list[str]:
    candidates = [
        cluster
        for cluster in clusters
        if cluster["final_score"] >= 40
        and (cluster["source_count"] >= 2 or cluster["max_source_score"] >= 10)
        and has_draft_ready_summary(cluster)
    ][:3]
    if not candidates:
        return ["Мақала жобасына жеткілікті күшті оқиға кластері жоқ."]

    lines: list[str] = []
    for cluster in candidates:
        ai_result = generate_article_text(build_draft_prompt(cluster))
        if ai_result.text and not ai_result.error_reason:
            print(f"[report] мақала жазу режимі={ai_result.mode} тақырып='{cluster['title']}'")
            lines.extend(ai_result.text.splitlines())
            lines.append("")
            continue
        print(f"[report] мақала жазу режимі=fallback тақырып='{cluster['title']}'")
        lines.extend(render_article(cluster))
        lines.append("")
    return lines


def has_draft_ready_summary(cluster: dict) -> bool:
    for item in cluster.get("items", []):
        if not is_weak_gdelt_summary(item.get("summary")):
            return True
    return False


def render_article(cluster: dict) -> list[str]:
    profile = article_profile(cluster)
    title = cluster["title"]
    summary = short_summary(cluster)

    return [
        f"### {title}",
        "",
        "**Лид:**",
        "",
        lead_text(profile, cluster, summary),
        "",
        "**Контекст:**",
        "",
        context_text(profile),
        "",
        "**Неге маңызды:**",
        "",
        importance_text(profile),
        "",
        "**Әрі қарай не күту керек:**",
        "",
        next_steps_text(profile),
        "",
        "**Дереккөздер:**",
        "",
        *[f"- [{link['title'] or link['source']}]({link['url']}) — {link['source']}" for link in cluster["links"][:5] if link.get("url")],
    ]


def article_profile(cluster: dict) -> str:
    tags = set(cluster.get("tags") or [])
    if {"russia", "ukraine"} <= tags:
        return "russia_ukraine"
    if is_usa_iran(tags):
        return "usa_iran"
    if is_china_taiwan(tags, cluster_text(cluster)):
        return "china_taiwan"
    if tags & {"nato", "eu"}:
        return "nato_eu"
    if "sanctions" in tags:
        return "sanctions"
    if tags & {"middle_east", "israel", "gaza", "lebanon", "syria", "hormuz"}:
        return "middle_east"
    return "general"


def lead_text(profile: str, cluster: dict, summary: str) -> str:
    sources = ", ".join(cluster["sources"][:3])
    if profile == "russia_ukraine":
        return f"{summary} {sources} хабарлары Украина төңірегіндегі әскери динамикаға, инфрақұрылымға соққыларға немесе майдандағы қысымға назар аудартады."
    if profile == "usa_iran":
        return f"{summary} Оқиғаның өзегінде келіссөздер, санкциялар, ядролық тақырып, Ормуз бұғазының қауіпсіздігі немесе аймақтағы АҚШ базалары тұр."
    if profile == "china_taiwan":
        return f"{summary} Бұл сюжет Тайвань маңындағы күш тепе-теңдігіне, технологиялық шектеулерге, саудаға немесе аймақтағы әскери қысымға қатысты."
    if profile == "nato_eu":
        return f"{summary} Мұнда одақтастардың үйлесімі, Еуропа қауіпсіздігі және НАТО немесе ЕО деңгейіндегі практикалық шешімдер сөз болып отыр."
    if profile == "sanctions":
        return f"{summary} Санкциялық бағыт мемлекеттердің қандай қысым құралдарын қолданатынын және оның келіссөз позицияларына қалай әсер ететінін көрсетеді."
    if profile == "middle_east":
        return f"{summary} Оқиға Таяу Шығыстағы өңірлік қауіпсіздікке, бітімге, соққыларға немесе теңіз маршруттарына төнген қауіптерге байланысты."
    return f"{summary} Бірнеше дереккөз бұл оқиғаны халықаралық саясатпен және мемлекеттік ойыншылардың шешімдерімен байланыстырады."


def context_text(profile: str) -> str:
    if profile == "russia_ukraine":
        return "Ресей мен Украина үшін мұндай хабарлар энергетикаға соққылармен, майдан жағдайымен, қару жеткізілімімен және Киев одақтастарының реакциясымен бірге бағаланады."
    if profile == "usa_iran":
        return "АҚШ-Иран күн тәртібі үш түйінге тіреледі: ядролық шектеулер, санкциялық қысым және Парсы шығанағының қауіпсіздігі."
    if profile == "china_taiwan":
        return "Тайвань маңындағы шиеленіс көбіне әскери маневрлер, экспорттық шектеулер, жартылай өткізгіштер және АҚШ пен одақтастардың мәлімдемелері арқылы көрінеді."
    if profile == "nato_eu":
        return "НАТО мен ЕО шешімдері қорғаныс жоспарлауына, Украинаға көмекке және одақтастар арасындағы жүктемені бөлуге рамка береді."
    if profile == "sanctions":
        return "Санкциялар әдетте дипломатия және әскери қысыммен қатар жүреді: олар ресурстарды шектейді, бірақ серіктестермен үйлесімді қажет етеді."
    if profile == "middle_east":
        return "Таяу Шығыстағы дағдарыстар жергілікті қақтығыстан халықаралық дипломатия, энергетика және маршрут қауіпсіздігі мәселесіне тез айналады."
    return "Контекст ресми институттардың, көрші мемлекеттердің және халықаралық ұйымдардың реакциясына байланысты."


def importance_text(profile: str) -> str:
    if profile == "russia_ukraine":
        return "Бұл бағыттағы өзгерістер соғыс қарқынына, украин инфрақұрылымының тұрақтылығына және одақтастардың қолдауды кеңейту дайындығына әсер етеді."
    if profile == "usa_iran":
        return "АҚШ пен Иран арасындағы кез келген эскалация өңірлік базаларға соққы, келіссөздің үзілуі және жаңа санкция қаупін күшейтеді."
    if profile == "china_taiwan":
        return "Тайвань және технология тақырыбы Азия қауіпсіздігіне, чип жеткізу тізбектеріне және АҚШ-Қытай стратегиялық бәсекесіне әсер етеді."
    if profile == "nato_eu":
        return "Мұндай шешімдер батыс институттарының қорғаныс пен саяси қолдауды қаншалықты тез бейімдей алатынын көрсетеді."
    if profile == "sanctions":
        return "Санкциялар сыртқы саяси шешімдердің құнын өзгертеді және қысым үшін қандай салалар маңызды саналатынын көрсетеді."
    if profile == "middle_east":
        return "Өңірлік эскалация бітімге, гуманитарлық ахуалға және әсіресе Ормуз бұғазы маңындағы кеме қатынасы қауіпсіздігіне әсер етеді."
    return "Оқиғаның маңызы одан кейін ресми шешімдер, санкциялар немесе дипломатиялық қадамдар бола ма дегенге байланысты."


def next_steps_text(profile: str) -> str:
    if profile == "russia_ukraine":
        return "Әрі қарай соққылардың салдары, Киев пен Мәскеудің мәлімдемелері, сондай-ақ НАТО мен ЕО-ның көмек және әуе қорғанысы бойынша шешімдері маңызды."
    if profile == "usa_iran":
        return "АҚШ, Иран, МАГАТЭ және шығанақ елдерінің мәлімдемелерін, сондай-ақ санкциялар мен келіссөздер туралы сигналдарды бақылау керек."
    if profile == "china_taiwan":
        return "Негізгі индикаторлар — Бейжің мен Тайбэйдің реакциясы, Вашингтон мәлімдемелері, экспорттық шаралар және флот не авиация белсенділігі."
    if profile == "nato_eu":
        return "Келесі кезекте қаржыландыру бөлшектері, жеткізу мерзімдері, жекелеген елдердің ұстанымы және министрлер деңгейіндегі шешімдер маңызды болады."
    if profile == "sanctions":
        return "Шектеулерге кім қосылатынын, қандай компаниялар шараға ілінетінін және қарсы реакция бола ма, соны бақылау керек."
    if profile == "middle_east":
        return "Оқ атуды тоқтату туралы растаулар, жаңа соққылар жайлы хабарлар және БҰҰ, АҚШ пен өңір үкіметтерінің мәлімдемелері маңызды."
    return "Келесі қадам — ресми мәлімдемелерді және негізгі қатысушылардың реакциясын салыстыру."


def human_topic(cluster: dict) -> str:
    tags = set(cluster.get("tags") or [])
    if {"russia", "ukraine"} <= tags:
        return "Ресей/Украина"
    if is_china_taiwan(tags, cluster_text(cluster)):
        return "Қытай/Тайвань"
    if is_usa_iran(tags):
        return "АҚШ/Иран"
    if tags & {"nato", "eu"}:
        return "НАТО/ЕО"
    if tags & {"middle_east", "israel", "gaza", "lebanon", "syria", "hormuz"}:
        return "Таяу Шығыс"
    if "sanctions" in tags:
        return "Санкциялар"
    return "Геосаясат"


def short_summary(cluster: dict) -> str:
    summary = cluster.get("summary", "").strip()
    if not summary or summary.startswith("Бірнеше дереккөз"):
        return "Оқиға дереккөздер блогындағы сілтемелермен расталады, бірақ редакторлық қолмен нақтылауды қажет етеді."
    if len(summary) > 280:
        return summary[:279].rstrip() + "..."
    return summary


def format_tags(cluster: dict) -> str:
    tags = [tag for tag in cluster.get("tags", []) if tag != "untagged"]
    return ", ".join(tags) if tags else "жоқ"


def format_links(cluster: dict, limit: int = 3) -> str:
    links = [link for link in cluster.get("links", []) if link.get("url")][:limit]
    return "; ".join(f"[{link_label(link)}]({link['url']})" for link in links)


def cluster_text(cluster: dict) -> str:
    return f"{cluster.get('title', '')} {cluster.get('summary', '')}".lower()


def link_label(link: dict) -> str:
    title = link.get("title") or ""
    source = link.get("source") or "source"
    if title and title.lower() != source.lower():
        return f"{source}: {title}"
    return source
