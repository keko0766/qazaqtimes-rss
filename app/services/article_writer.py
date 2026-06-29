from __future__ import annotations

import re
import os
from pathlib import Path

from app.services.ollama_writer import generate_text, use_ollama
from app.utils.datetime import now_local


def generate_kazakh_article(cluster: dict) -> str | None:
    if use_ollama():
        text = generate_text(build_prompt(cluster), "қазақша мақала жазу")
        if text:
            print("[article] жазу режимі: ollama")
            return text

    print("[article] жазу режимі: резерв")
    return fallback_article(cluster)


def save_article(title: str, content: str) -> Path:
    out_dir = Path(os.getenv("OUTPUT_DIR", "output")) / "articles"
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = now_local().strftime("%Y-%m-%d_%H%M%S")
    slug = slugify(title)
    path = out_dir / f"{timestamp}_{slug}.md"
    path.write_text(content.rstrip() + "\n", encoding="utf-8")
    return path


def build_prompt(cluster: dict) -> str:
    links = [
        f"- {link.get('source', 'source')}: {link.get('title', 'Untitled')} — {link.get('url', '')}"
        for link in cluster.get("links", [])[:5]
        if link.get("url")
    ]
    sources = ", ".join(cluster.get("sources", [])[:5])
    tags = ", ".join(tag for tag in cluster.get("tags", []) if tag != "untagged")

    return f"""Сен қазақ тілінде қысқа аналитикалық мақала жазасың.

Тек төмендегі оқиға кластері деректерін қолдан:

Тақырып: {cluster.get("title", "")}
Түйін: {cluster.get("summary", "")}
Тегтер: {tags}
Дереккөздер: {sources}
Сілтемелер:
{chr(10).join(links)}

Ережелер:
- Тек title, summary, tags, sources және links деректерін қолдан.
- Факт, есім, сан, цитата немесе деталь ойдан шығарма.
- Мақалалардың толық мәтінін жүктеме және қайталап берме.
- Дереккөз мәтінін сөзбе-сөз көшірме.
- Ақпарат аз болса, сақ тұжырым қолдан.
- Қысқа әрі редакцияға ыңғайлы жаз.

Құрылым дәл осылай болсын:

# [қысқа нақты тақырып]

Лид:
2-3 сөйлем.

Не болды:
қысқа түсіндіру.

Неге маңызды:
геосаяси мәні.

Әрі қарай не күту керек:
1-2 сақ болжам, нақты факт ойдан шығармай.

Дереккөздер:
- source + url
"""


def fallback_article(cluster: dict) -> str:
    original_title = str(cluster.get("title") or "Геосаяси оқиға").strip()
    headline = kazakh_headline(cluster)
    tags = ", ".join(tag for tag in cluster.get("tags", []) if tag != "untagged") or "көрсетілмеген"
    sources = ", ".join(cluster.get("sources", [])[:5]) or "дереккөздер көрсетілмеген"
    focus = kazakh_focus(cluster)

    return "\n".join(
        [
            f"# {headline}",
            "",
            "Лид:",
            f"{focus} Бұл қысқа мақала тек сақталған оқиға кластерінің метадеректеріне сүйеніп жазылды. Дереккөздер оқиғаны «{original_title}» тақырыбы арқылы сипаттайды.",
            "",
            "Не болды:",
            f"Кластердегі метадеректер бұл оқиғаның негізгі бағытын көрсетеді. Байланысты тегтер: {tags}. Ақпарат {sources} дереккөздерінен келген сілтемелер арқылы тексеріледі.",
            "",
            "Неге маңызды:",
            importance_text(cluster),
            "",
            "Әрі қарай не күту керек:",
            "Алдағы қадам ретінде ресми мәлімдемелерді, жаңа санкциялар немесе келіссөз сигналдарын және негізгі тараптардың реакциясын бақылау керек. Нақты болжам жасау үшін қосымша расталған дерек қажет.",
            "",
            "Дереккөздер:",
            *format_sources(cluster),
        ]
    )


def kazakh_headline(cluster: dict) -> str:
    tags = set(cluster.get("tags") or [])
    if {"russia", "ukraine"} <= tags:
        return "Ресей мен Украина бағытындағы жаңа оқиға"
    if {"usa", "iran"} <= tags:
        return "АҚШ пен Иран арасындағы шиеленіс қайта назарда"
    if {"china", "taiwan"} & tags:
        return "Қытай мен Тайвань маңындағы жағдай бақылауда"
    if tags & {"nato", "eu"}:
        return "НАТО мен ЕО күн тәртібіндегі қауіпсіздік мәселесі"
    if tags & {"middle_east", "israel", "gaza", "lebanon", "syria", "hormuz"}:
        return "Таяу Шығыстағы қауіпсіздік ахуалы"
    if "sanctions" in tags:
        return "Санкциялар төңірегіндегі жаңа қадам"
    return "Геосаяси оқиғаға қысқа шолу"


def kazakh_focus(cluster: dict) -> str:
    tags = set(cluster.get("tags") or [])
    if {"russia", "ukraine"} <= tags:
        return "Оқиға Ресей-Украина соғысы, әскери қысым және халықаралық реакция контекстінде қаралады."
    if {"usa", "iran"} <= tags:
        return "Оқиға АҚШ-Иран қатынастары, дипломатия, қауіпсіздік және өңірлік тұрақтылық контекстінде қаралады."
    if {"china", "taiwan"} & tags:
        return "Оқиға Қытай, Тайвань және Азиядағы қауіпсіздік теңгерімі контекстінде қаралады."
    if tags & {"nato", "eu"}:
        return "Оқиға НАТО, ЕО және еуроатлантикалық қауіпсіздік шешімдері контекстінде қаралады."
    if tags & {"middle_east", "israel", "gaza", "lebanon", "syria", "hormuz"}:
        return "Оқиға Таяу Шығыстағы қауіпсіздік, дипломатия және ықтимал эскалация контекстінде қаралады."
    if "sanctions" in tags:
        return "Оқиға санкциялық қысым және дипломатиялық келіссөздер контекстінде қаралады."
    return "Оқиға халықаралық саясат және негізгі тараптардың реакциясы контекстінде қаралады."


def importance_text(cluster: dict) -> str:
    tags = set(cluster.get("tags") or [])
    if {"usa", "iran"} <= tags or "hormuz" in tags:
        return "Бұл бағыттағы өзгерістер Парсы шығанағы қауіпсіздігіне, келіссөз процесіне және энергетикалық маршруттарға әсер етуі мүмкін. Қолда бар дерек шектеулі болса, редакциялық қорытындыны қосымша қолмен тексерген дұрыс."
    if {"russia", "ukraine"} <= tags:
        return "Бұл бағыттағы хабарлар соғыс динамикасына, инфрақұрылым қауіпсіздігіне және одақтастардың саяси шешімдеріне әсер етуі мүмкін. Қолда бар дерек шектеулі болса, редакциялық қорытындыны қосымша қолмен тексерген дұрыс."
    if tags & {"nato", "eu"}:
        return "Мұндай оқиғалар қорғаныс жоспарлауына, одақтастардың үйлесіміне және саяси міндеттемелердің орындалуына қатысты. Қолда бар дерек шектеулі болса, редакциялық қорытындыны қосымша қолмен тексерген дұрыс."
    return "Оқиға халықаралық саясат, қауіпсіздік немесе дипломатиялық шешімдер контекстінде маңызды болуы мүмкін. Қолда бар дерек шектеулі болса, редакциялық қорытындыны қосымша қолмен тексерген дұрыс."


def format_sources(cluster: dict) -> list[str]:
    links = [link for link in cluster.get("links", []) if link.get("url")][:5]
    if not links:
        return ["- Сілтеме жоқ"]
    return [f"- {link.get('source', 'source')} — {link['url']}" for link in links]


def slugify(title: str) -> str:
    normalized = re.sub(r"[^\wа-яА-ЯәғқңөұүһіӘҒҚҢӨҰҮҺІ]+", "-", title, flags=re.UNICODE)
    normalized = normalized.strip("-_").lower()
    return normalized[:80] or "maqala"
