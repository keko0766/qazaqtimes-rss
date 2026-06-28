from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from app.services.event_clusterer import cluster_events
from app.services.ollama_writer import generate_draft, use_ollama
from app.services.topic_score import (
    GEOPOLITICAL_TAGS,
    is_china_taiwan,
    is_usa_iran,
    is_weak_gdelt_summary,
)
from app.utils.datetime import today_str


TOPIC_RULES = {
    "Russia / Ukraine": {"russia", "ukraine"},
    "USA / Iran": {"usa", "iran"},
    "China / Taiwan": {"china", "taiwan"},
    "NATO / EU": {"nato", "eu"},
    "Middle East": {"middle_east", "iran", "israel", "gaza", "lebanon", "syria", "hormuz"},
}


def generate_report(items: list[dict], output_dir: str | Path) -> Path:
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    today = today_str()
    path = out_dir / f"digest_{today}.md"

    clusters = cluster_events(items)
    top_clusters = select_top_clusters(clusters)
    topic_clusters = [cluster for cluster in clusters if cluster.get("core_topic_score", 0) >= 2]
    secondary_clusters = select_secondary_clusters(clusters, top_clusters)

    lines: list[str] = [
        f"# Geopolitical Digest — {today}",
        "",
        "## Главное",
        "",
        *build_headlines(top_clusters),
        "",
        "## Главные события",
        "",
        *build_top_events(top_clusters),
        "",
        "## По направлениям",
        "",
        *build_topic_sections(topic_clusters),
        "",
        "## Черновики статей",
        "",
        *build_draft_articles(top_clusters),
        "",
        "## Второстепенные международные новости",
        "",
        *build_secondary_news(secondary_clusters),
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    print(f"[report] created {path}")
    return path


def select_top_clusters(clusters: list[dict]) -> list[dict]:
    top = []
    for cluster in clusters:
        tags = set(cluster.get("tags") or [])
        core_score = int(cluster.get("core_topic_score", 0))
        if core_score >= 2 and int(cluster.get("final_score", 0)) >= 35:
            top.append(cluster)
            continue
        if cluster.get("max_source_score", 0) >= 8 and tags & GEOPOLITICAL_TAGS and core_score >= 2:
            top.append(cluster)
    return top[:12]


def select_secondary_clusters(clusters: list[dict], top_clusters: list[dict]) -> list[dict]:
    top_ids = {id(cluster) for cluster in top_clusters}
    secondary = []
    for cluster in clusters:
        if id(cluster) in top_ids:
            continue
        if int(cluster.get("core_topic_score", 0)) == 1:
            secondary.append(cluster)
    return secondary[:12]


def build_headlines(clusters: list[dict]) -> list[str]:
    if not clusters:
        return ["- Нет сильных core-событий для дайджеста."]

    lines = []
    for cluster in clusters[:8]:
        topic = human_topic(cluster)
        sources = ", ".join(cluster["sources"][:3])
        lines.append(f"- {topic}: {cluster['title']} ({sources}).")
    return lines


def build_top_events(clusters: list[dict]) -> list[str]:
    if not clusters:
        return ["Нет данных."]

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
            lines.extend(["- Нет заметных событий в сохранённой выборке.", ""])
            continue
        for cluster in section_clusters:
            sources = ", ".join(cluster["sources"][:3])
            tags = format_tags(cluster)
            lines.append(f"- **{cluster['title']}** — {short_summary(cluster)}")
            lines.append(f"  Tags: {tags}. Sources: {sources}.")
            lines.append(f"  Links: {format_links(cluster, limit=3)}")
        lines.append("")
    return lines


def group_clusters_by_topic(clusters: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for cluster in clusters:
        tags = set(cluster.get("tags") or [])
        text = cluster_text(cluster)
        if tags & {"russia", "ukraine"}:
            grouped["Russia / Ukraine"].append(cluster)
        if is_usa_iran(tags):
            grouped["USA / Iran"].append(cluster)
        if is_china_taiwan(tags, text):
            grouped["China / Taiwan"].append(cluster)
        if tags & {"nato", "eu"}:
            grouped["NATO / EU"].append(cluster)
        if tags & TOPIC_RULES["Middle East"]:
            grouped["Middle East"].append(cluster)
    return grouped


def render_event_block(cluster: dict, heading_level: int = 3) -> list[str]:
    marker = "#" * heading_level
    links = [link for link in cluster["links"] if link.get("url")][:5]
    return [
        f"{marker} Event: {cluster['title']}",
        "",
        f"Short summary: {short_summary(cluster)}",
        "",
        f"Tags: {format_tags(cluster)}",
        "",
        f"Core topics: {format_core_topics(cluster)}",
        "",
        "Sources:",
        *[f"- {source}" for source in cluster["sources"][:5]],
        "",
        "Links:",
        *[f"- [{link_label(link)}]({link['url']})" for link in links],
    ]


def build_draft_articles(clusters: list[dict]) -> list[str]:
    candidates = [
        cluster
        for cluster in clusters
        if cluster["final_score"] >= 40
        and cluster.get("core_topic_score", 0) >= 2
        and (cluster["source_count"] >= 2 or cluster["max_source_score"] >= 10)
        and has_draft_ready_summary(cluster)
    ][:3]
    if not candidates:
        return ["Нет достаточно сильных event clusters для черновиков."]

    lines: list[str] = []
    ollama_enabled = use_ollama()
    print(f"[report] draft writer: {'ollama' if ollama_enabled else 'fallback'}")
    for cluster in candidates:
        if ollama_enabled:
            ollama_text = generate_draft(cluster)
            if ollama_text:
                print(f"[report] draft writer: ollama used for '{cluster['title']}'")
                lines.extend(ollama_text.splitlines())
                lines.append("")
                continue
            print(f"[report] draft writer: fallback used for '{cluster['title']}'")
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
        "**Почему это важно:**",
        "",
        importance_text(profile),
        "",
        "**Что дальше:**",
        "",
        next_steps_text(profile),
        "",
        "**Источники:**",
        "",
        *[f"- [{link['title'] or link['source']}]({link['url']}) — {link['source']}" for link in cluster["links"][:5] if link.get("url")],
    ]


def article_profile(cluster: dict) -> str:
    topics = set(cluster.get("core_topics") or [])
    tags = set(cluster.get("tags") or [])
    if "russia_ukraine" in topics:
        return "russia_ukraine"
    if {"usa_iran", "iran_nuclear"} & topics:
        return "usa_iran"
    if "china_taiwan" in topics:
        return "china_taiwan"
    if {"nato_ukraine"} & topics or tags & {"nato", "eu"}:
        return "nato_eu"
    if "sanctions" in topics:
        return "sanctions"
    if "middle_east_security" in topics or tags & {"middle_east", "israel", "gaza", "lebanon", "syria", "hormuz"}:
        return "middle_east"
    return "general"


def lead_text(profile: str, cluster: dict, summary: str) -> str:
    sources = ", ".join(cluster["sources"][:3])
    if profile == "russia_ukraine":
        return f"{summary} Сообщения {sources} указывают на развитие военной динамики вокруг Украины, ударов по инфраструктуре или давления на линии фронта."
    if profile == "usa_iran":
        return f"{summary} В центре события — переговоры, санкции, ядерная тема, безопасность Ормузского пролива или американские базы в регионе."
    if profile == "china_taiwan":
        return f"{summary} Сюжет относится к балансу сил вокруг Тайваня, технологическим ограничениям, торговле или военному давлению в регионе."
    if profile == "nato_eu":
        return f"{summary} Речь идёт о координации союзников, европейской безопасности и практических решениях НАТО или ЕС."
    if profile == "sanctions":
        return f"{summary} Санкционная линия показывает, какие инструменты давления используют государства и как это влияет на переговорные позиции."
    if profile == "middle_east":
        return f"{summary} Событие связано с региональной безопасностью на Ближнем Востоке, перемирием, ударами или угрозами для морских маршрутов."
    return f"{summary} Несколько источников связывают событие с международной политикой и решениями государственных игроков."


def context_text(profile: str) -> str:
    if profile == "russia_ukraine":
        return "Для России и Украины такие сообщения важны в связке с ударами по энергетике, состоянием фронта, поставками вооружений и реакцией союзников Киева."
    if profile == "usa_iran":
        return "Американо-иранская повестка держится на трёх узлах: ядерные ограничения, санкционное давление и безопасность Персидского залива."
    if profile == "china_taiwan":
        return "Напряжение вокруг Тайваня часто проявляется через военные манёвры, экспортные ограничения, полупроводники и заявления США или союзников."
    if profile == "nato_eu":
        return "Решения НАТО и ЕС задают рамку для оборонного планирования, помощи Украине и распределения нагрузки между союзниками."
    if profile == "sanctions":
        return "Санкции обычно идут рядом с дипломатией и военным давлением: они ограничивают ресурсы, но требуют координации с партнёрами."
    if profile == "middle_east":
        return "Ближневосточные кризисы быстро переходят из локальных столкновений в вопросы международной дипломатии, энергетики и безопасности маршрутов."
    return "Контекст зависит от реакции официальных институтов, соседних государств и международных организаций."


def importance_text(profile: str) -> str:
    if profile == "russia_ukraine":
        return "Изменения на этом направлении влияют на темп войны, устойчивость украинской инфраструктуры и готовность союзников расширять поддержку."
    if profile == "usa_iran":
        return "Любая эскалация между США и Ираном повышает риск ударов по региональным базам, срыва переговоров и новых санкционных решений."
    if profile == "china_taiwan":
        return "Тайваньская и технологическая повестка затрагивает безопасность в Азии, цепочки поставок чипов и стратегическую конкуренцию США и Китая."
    if profile == "nato_eu":
        return "Такие решения показывают, насколько быстро западные институты готовы адаптировать оборону и политическую поддержку."
    if profile == "sanctions":
        return "Санкции меняют стоимость внешнеполитических решений и показывают, какие отрасли считаются критическими для давления."
    if profile == "middle_east":
        return "Региональная эскалация влияет на перемирия, гуманитарную ситуацию и безопасность судоходства, особенно вокруг Ормузского пролива."
    return "Значение события определяется тем, последуют ли за ним официальные решения, санкции или дипломатические шаги."


def next_steps_text(profile: str) -> str:
    if profile == "russia_ukraine":
        return "Дальше важны данные о последствиях ударов, заявления Киева и Москвы, а также решения НАТО и ЕС по помощи и ПВО."
    if profile == "usa_iran":
        return "Следить нужно за заявлениями США, Ирана, МАГАТЭ и стран Залива, а также за сигналами о санкциях и переговорах."
    if profile == "china_taiwan":
        return "Ключевые индикаторы — реакция Пекина и Тайбэя, заявления Вашингтона, экспортные меры и активность флота или авиации."
    if profile == "nato_eu":
        return "Следующими будут детали финансирования, сроки поставок, позиции отдельных стран и возможные решения на уровне министров."
    if profile == "sanctions":
        return "Нужно смотреть, кто присоединится к ограничениям, какие компании попадут под меры и будет ли ответная реакция."
    if profile == "middle_east":
        return "Важны подтверждения о прекращении огня, сообщения о новых ударах и заявления ООН, США и региональных правительств."
    return "Следующий шаг — сверить официальные заявления и реакцию ключевых участников."


def build_secondary_news(clusters: list[dict]) -> list[str]:
    if not clusters:
        return ["- Нет второстепенных международных новостей после фильтрации."]
    lines = []
    for cluster in clusters:
        sources = ", ".join(cluster["sources"][:3])
        lines.append(f"- **{cluster['title']}** — {short_summary(cluster)} Sources: {sources}.")
    return lines


def human_topic(cluster: dict) -> str:
    topics = set(cluster.get("core_topics") or [])
    tags = set(cluster.get("tags") or [])
    if "russia_ukraine" in topics:
        return "Россия/Украина"
    if "china_taiwan" in topics:
        return "Китай/Тайвань"
    if {"usa_iran", "iran_nuclear"} & topics:
        return "США/Иран"
    if "nato_ukraine" in topics or tags & {"nato", "eu"}:
        return "НАТО/ЕС"
    if "middle_east_security" in topics or tags & {"middle_east", "israel", "gaza", "lebanon", "syria", "hormuz"}:
        return "Ближний Восток"
    if "sanctions" in topics:
        return "Санкции"
    return "Геополитика"


def short_summary(cluster: dict) -> str:
    summary = cluster.get("summary", "").strip()
    if not summary or summary.startswith("Несколько источников сообщили"):
        return "Событие подтверждается ссылками в блоке источников, но требует ручной редакторской формулировки."
    if len(summary) > 280:
        return summary[:279].rstrip() + "..."
    return summary


def format_tags(cluster: dict) -> str:
    tags = [tag for tag in cluster.get("tags", []) if tag != "untagged"]
    return ", ".join(tags) if tags else "none"


def format_core_topics(cluster: dict) -> str:
    topics = cluster.get("core_topics") or []
    return ", ".join(topics) if topics else "secondary"


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
