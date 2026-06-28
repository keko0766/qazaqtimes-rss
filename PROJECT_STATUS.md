# geo-news-bot — статус работ

Дата: 2026-06-29

## Кратко

Проект `geo-news-bot` уже собран как локальный Docker/Python MVP для сбора геополитических новостей из RSS и GDELT, сохранения метаданных в SQLite и генерации Markdown-дайджеста.

После первого рабочего варианта добавлены улучшения качества дайджеста: фильтрация мусора, blacklist тем, оценка источников, `final_score`, белый список GDELT и event clustering.

## Текущая структура проекта

```text
geo-news-bot/
  docker-compose.yml
  Dockerfile
  requirements.txt
  README.md
  PROJECT_STATUS.md
  .env.example
  .gitignore
  .dockerignore
  sources.json
  app/
    __init__.py
    main.py
    db.py
    models.py
    collectors/
      __init__.py
      rss_collector.py
      gdelt_collector.py
    services/
      __init__.py
      classifier.py
      deduplicate.py
      event_clusterer.py
      relevance.py
      report_generator.py
      source_quality.py
    utils/
      __init__.py
      text.py
  data/
    .gitkeep
    news.sqlite3
  output/
    .gitkeep
    digest_YYYY-MM-DD.md
```

Примечание: `__pycache__/` и `.pyc` файлы могут появляться после локального запуска Python. Они добавлены в `.gitignore` и `.dockerignore` и не являются частью логики проекта.

## Что уже было сделано

### Базовый Docker-проект

- Создана папка `geo-news-bot/`.
- Добавлен `Dockerfile` на базе `python:3.12-slim`.
- Добавлен `docker-compose.yml` с сервисом `app`.
- Смонтированы папки:
  - `./data:/app/data`
  - `./output:/app/output`
  - `./sources.json:/app/sources.json:ro`
- Команда по умолчанию: `python app/main.py all`.

### CLI

В `app/main.py` добавлены команды:

```bash
python app/main.py collect
python app/main.py report
python app/main.py all
```

Команда `all`:

- создаёт БД при необходимости;
- собирает RSS;
- собирает GDELT;
- дедуплицирует;
- классифицирует;
- сохраняет записи;
- генерирует Markdown-дайджест.

### SQLite

В `app/db.py` создана таблица `news`.

Изначальные поля:

```sql
id INTEGER PRIMARY KEY AUTOINCREMENT
title TEXT NOT NULL
url TEXT UNIQUE NOT NULL
source TEXT
published_at TEXT
summary TEXT
tags TEXT
importance INTEGER DEFAULT 0
created_at TEXT DEFAULT CURRENT_TIMESTAMP
processed INTEGER DEFAULT 0
```

Добавлены новые поля для улучшенного качества:

```sql
source_score INTEGER DEFAULT 0
relevance_score INTEGER DEFAULT 0
final_score INTEGER DEFAULT 0
```

Миграция сделана безопасно через `ALTER TABLE` с проверкой существующих колонок.

### Сбор RSS

Файл: `app/collectors/rss_collector.py`

Сделано:

- чтение RSS URL;
- получение entries через `feedparser`;
- извлечение `title`, `link`, `published`, `summary`;
- очистка HTML из summary;
- обработка ошибок источников;
- поддержка `enabled: false` в `sources.json`.

### Сбор GDELT

Файл: `app/collectors/gdelt_collector.py`

Сделано:

- подключение GDELT Doc API;
- запросы:
  - `Russia Ukraine war`
  - `USA Iran sanctions`
  - `China Taiwan`
  - `NATO Ukraine`
  - `Middle East escalation`
  - `Iran nuclear`
  - `US China tensions`
- параметры:
  - `format=json`
  - `mode=ArtList`
  - `maxrecords=50`
  - `sort=HybridRel`
- добавлена пауза между запросами;
- добавлен один retry при `429 Too Many Requests`;
- добавлен белый список доменов GDELT.

### Источники

Файл: `sources.json`

Добавлены официальные и бесплатные источники:

- GDELT;
- U.S. Department of State;
- White House;
- Defense.gov;
- NATO;
- UN News;
- IAEA;
- President of Ukraine;
- Ukraine MFA;
- Kremlin;
- Russia MFA;
- China MFA;
- European Council;
- BBC World;
- Al Jazeera;
- The Guardian World;
- Deutsche Welle;
- France 24.

Часть официальных RSS сейчас оставлена как `enabled: false`, потому что при проверке они отдавали HTML, 403 или 404 вместо стабильного RSS.

### Дедупликация

Файл: `app/services/deduplicate.py`

Сделано:

- дедупликация по URL;
- нормализация URL;
- нормализация title;
- сравнение похожих заголовков через `difflib.SequenceMatcher`.

### Классификация

Файл: `app/services/classifier.py`

Сделано:

- keyword rules без ИИ;
- теги:
  - `usa`
  - `iran`
  - `russia`
  - `ukraine`
  - `china`
  - `nato`
  - `eu`
  - `sanctions`
  - `war`
  - `nuclear`
  - `middle_east`
  - `taiwan`
  - `diplomacy`
  - `military`
  - `israel`
  - `gaza`
  - `lebanon`
  - `syria`
  - `hormuz`
- importance:
  - `3` для attack/missile/invasion/nuclear/sanctions/ceasefire/troops/strike;
  - `2` для diplomacy/talks/minister/president/warning/agreement;
  - `1` для остального;
- добавлен расчёт:
  - `source_score`
  - `relevance_score`
  - `final_score`

### Фильтр релевантности

Файл: `app/services/relevance.py`

Сделано:

- новость попадает в отчёт только если имеет важные геополитические теги или ключевые слова;
- `untagged` новости не должны попадать в digest;
- добавлен blacklist тем:
  - sport;
  - celebrity;
  - entertainment;
  - weather;
  - crash;
  - plane crash;
  - wildfire;
  - crime;
  - accident;
  - music;
  - film;
  - football;
  - tennis;
  - earthquake;
  - domestic noise вроде shark attack / vandalism / cryptographic-only news.
- исключение blacklist работает, если материал реально связан с war/sanctions/military/diplomacy.

### Оценка качества источников

Файл: `app/services/source_quality.py`

Сделано:

- добавлен `ALLOWED_GDELT_DOMAINS`;
- GDELT новости с доменов вне whitelist не сохраняются;
- `source_score`:
  - Reuters/AP/UN/IAEA/NATO/official government sources = `10`;
  - BBC/DW/France24 = `8`;
  - Al Jazeera/Guardian = `7`;
  - allowed GDELT domain = по домену;
  - unknown = `3`.

### Event clustering

Файл: `app/services/event_clusterer.py`

Сделано:

- группировка похожих новостей в event clusters;
- нормализация title;
- lowercase;
- удаление пунктуации;
- stopwords;
- сравнение через `difflib.SequenceMatcher`;
- дополнительная проверка общих ключевых слов;
- кластер получает:
  - title;
  - summary;
  - tags;
  - sources;
  - links;
  - source_count;
  - max_source_score;
  - final_score.

### Новый Markdown-отчёт

Файл: `app/services/report_generator.py`

Новая структура:

```md
# Geopolitical Digest — YYYY-MM-DD

## Главное

## Главные события

## По направлениям
### Russia / Ukraine
### USA / Iran
### China / Taiwan
### NATO / EU
### Middle East

## Черновики статей
```

Сделано:

- отчёт строится по event clusters, а не по отдельным новостям;
- Top events сортируются по `final_score`;
- каждый event block показывает:
  - title;
  - short summary;
  - tags;
  - sources;
  - links;
- раздел `China / Taiwan` теперь берёт только `china` или `taiwan`;
- раздел `Russia / Ukraine` берёт только `russia` или `ukraine`;
- раздел `NATO / EU` берёт только `nato` или `eu`;
- раздел `Middle East` берёт `middle_east`, `iran`, `israel`, `gaza`, `lebanon`, `syria`, `hormuz`.

### Черновики статей

Черновики теперь строятся только из event clusters, где:

- высокий `final_score`;
- минимум два источника или один очень авторитетный источник.

Фразы старого шаблона убраны:

- “Новость требует проверки”;
- “может повлиять”;
- “стоит отслеживать”;
- “На основе доступных метаданных”.

Новая структура черновика:

```md
### Заголовок

**Лид:**

**Контекст:**

**Почему это важно:**

**Что дальше:**

**Источники:**
```

## Что уже проверено

Проверено локально:

```bash
python3 -m compileall app
```

Результат: Python-файлы компилируются.

Проверено локально:

```bash
python app/main.py report
```

Результат: отчёт создаётся в `output/digest_2026-06-29.md`.

Проверка качества после улучшений показала:

- `untagged` новости больше не должны попадать в digest;
- новости про крушения, пожары, спорт и бытовые аварии фильтруются blacklist-ом;
- `China / Taiwan` больше не забирает Hormuz/Iran/Middle East из-за слова `strait`;
- похожие события начали группироваться, например US-Iran strikes и Israel/Lebanon strikes.

## Что осталось доделать

После продолжения работы основной список сокращён. Уже сделано:

- event clustering усилен через event signatures для `iran_nuclear`, `usa_iran_escalation`, `hormuz_evacuation`, `israel_lebanon`, `russia_ukraine_strikes`;
- blacklist и weak-tag фильтры усилены, чтобы внутренние административные новости Кремля/White House не проходили только из-за слов `President`, `Government`, `Order`;
- `README.md` обновлён разделами:
   - как работает фильтрация;
   - почему GDELT ограничен белым списком;
   - почему это не автопубликация;
   - как вручную проверить черновик перед публикацией на сайте.

Попытка проверить полный Docker Compose цикл:

```bash
docker compose run --rm app python app/main.py all
```

Результат в текущей среде:

```text
permission denied while trying to connect to the Docker daemon socket
```

Даже после запроса доступа к `/Users/keko/.docker/run/docker.sock` среда не позволила подключиться к Docker daemon. Это ограничение текущей sandbox-сессии, а не ошибка Python-кода проекта.

Финальный `output/digest_2026-06-29.md` проверен локально через `python app/main.py report`:

- нет `untagged`;
- нет `Tags: none`;
- нет `Skydiving`, `plane crash`, `wildfire`, `football`, `tennis`;
- `China / Taiwan` не содержит Iran, Hormuz или Middle East;
- похожие US/Iran strike новости сгруппированы в один event;
- `Iran nuclear` определяется как один кластер на текущей базе.

## Текущие ограничения

- Docker-команда ранее не была проверена до конца, потому что Docker daemon на машине не был запущен.
- GDELT иногда отдаёт `429 Too Many Requests`; в код добавлены пауза и один retry.
- Некоторые официальные RSS нестабильны или блокируют запросы, поэтому они оставлены в `sources.json` как disabled placeholders.
- Проект всё ещё MVP: он помогает собрать и подготовить черновики, но финальная редакторская проверка перед сайтом обязательна.
