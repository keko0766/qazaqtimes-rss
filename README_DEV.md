# README_DEV.md — geo-news-bot developer guide

Бұл құжат developer үшін. README.md қарапайым user-ге арналған, ал мұнда код құрылымы, data flow, CLI, GUI, Docker және maintenance ережелері толық түсіндіріледі.

Негізгі mental model: бұл автожурналист емес. Бұл редакторға көмектесетін local tool. Ол RSS/GDELT metadata жинайды, SQLite-ке сақтайды, геосаяси маңызды оқиғаларды іріктейді, Markdown digest және қысқа қазақша мақала draft-тарын жасайды. Соңғы шешім, фактчекинг және жариялау редакторда қалады.

## 1. Жоба не істейді

geo-news-bot күнделікті геосаяси жаңалықтарды жеңіл pipeline арқылы өңдейді:

1. RSS және optional GDELT деректерін алады.
2. Тек title, url, source, published_at, summary сияқты metadata сақтайды.
3. SQLite ішіндегі бұрынғы жазбалармен салыстырып duplicate жаңалықтарды кеседі.
4. Keyword-based classifier арқылы tags және score есептейді.
5. Noise/filter қабаты sport, crash, domestic weak topic сияқты артық нәрселерді алып тастайды.
6. Ұқсас жаңалықтарды event cluster-ге біріктіреді.
7. `output/digest_YYYY-MM-DD.md` дайджестін жазады.
8. Optional AI provider арқылы немесе fallback template арқылы қазақша мақалалар жазады.
9. GUI арқылы қарапайым user-ге бір батырмалық daily workflow береді.

Маңызды шектеулер:

- Full article text жүктелмейді.
- Автопубликация жоқ.
- AI қолжетімсіз болса app құламайды, fallback мәтін жазады.
- Docker default режимде Ollama image download/start жасамайды.
- Daily article selection редакциялық 5 slot бойынша жүреді; жетпеген slot үшін fake мақала жасалмайды.

## 2. Негізгі user flow

Қарапайым daily flow:

1. User `./start.sh` немесе `start.command` ашады.
2. Docker GUI сервисін көтереді.
3. Browser `http://localhost:8000` ашады.
4. User **Бүгінгі 5 мақаланы жасау** батырмасын басады.
5. GUI іште екі command орындайды:

```bash
python app/main.py all --mode fast
python app/main.py article --mode fast --limit 5 --replace-today
```

Нәтиже:

- DB жаңарады: `data/news.sqlite3`
- Digest жазылады: `output/digest_YYYY-MM-DD.md`
- Бүгінгі таза article result жазылады: `output/articles/YYYY-MM-DD/latest/*.md`

Егер collect кезінде `жаңа жазбалар: 0` шықса, article step бәрібір бұрын сақталған соңғы релевант оқиғалардан мақала жасай алады. GUI бұл жағдайды user-friendly мәтінмен түсіндіреді.

## 3. Жоғары деңгейдегі архитектура

```text
                 sources.json
                      |
        +-------------+-------------+
        |                           |
   RSS collector              GDELT collector
        |                           |
        +-------------+-------------+
                      |
                 raw items
                      |
              deduplicate_items
                      |
                classify_items
                      |
             filter_relevant_items
                      |
                 SQLite news
                      |
              fetch_recent_news
                      |
                 cluster_events
                      |
        +-------------+-------------+
        |                           |
  report_generator            article_writer
        |                           |
 output/digest_*.md      output/articles/YYYY-MM-DD/latest/*.md
        |                           |
        +-------------+-------------+
                      |
                    GUI
```

AI генерация бөлек optional қабат:

```text
article/report prompt
        |
  ai_writer.generate_article_text
        |
  +-----+----------+-----------+
  |                |           |
 none           ollama     lmstudio
  |                |           |
fallback      /api/generate  /chat/completions
```

## 4. Repo structure

```text
.
├── app/
│   ├── main.py                    # CLI entrypoint: collect/report/article/all
│   ├── web.py                     # local GUI және JSON API
│   ├── db.py                      # SQLite schema, migrations, insert/fetch helpers
│   ├── models.py                  # NewsItem dataclass
│   ├── collectors/
│   │   ├── rss_collector.py       # RSS feed collection
│   │   └── gdelt_collector.py     # GDELT Doc API collection
│   ├── services/
│   │   ├── ai_writer.py           # AI_PROVIDER router
│   │   ├── article_writer.py      # қазақша article selection/generation/save
│   │   ├── classifier.py          # tags, importance, scores
│   │   ├── deduplicate.py         # URL/title duplicate filtering
│   │   ├── event_clusterer.py     # event cluster logic
│   │   ├── lmstudio_writer.py     # LM Studio OpenAI-compatible API
│   │   ├── ollama_writer.py       # Ollama API
│   │   ├── relevance.py           # relevance/noise filters
│   │   ├── report_generator.py    # Markdown digest
│   │   ├── source_quality.py      # source/domain scoring
│   │   └── topic_score.py         # topic helper checks
│   └── utils/
│       ├── datetime.py            # APP_TIMEZONE, today_str
│       └── text.py                # HTML/text/url cleanup
├── data/                          # local SQLite volume, gitignored
├── output/                        # digest/articles output, gitignored
├── sources.json                   # active RSS + GDELT config
├── sources.disabled.json          # disabled/candidate sources with notes
├── .env.example                   # default env values
├── docker-compose.yml             # app/gui + optional Ollama profiles
├── docker-compose.gpu.yml         # future NVIDIA PC override
├── Dockerfile
├── requirements.txt
├── start.sh
├── start.command
├── stop.sh
├── stop.command
├── start_gui.sh
└── README_DEV.md
```

## 5. `app/main.py` командалары

`app/main.py` негізгі CLI entrypoint. Бар командалар:

```bash
python app/main.py collect --mode fast
python app/main.py report --mode fast
python app/main.py all --mode fast
python app/main.py article --mode fast --limit 5
python app/main.py article --mode fast --limit 5 --replace-today
```

Args:

- `command`: `collect`, `report`, `article`, `all`
- `--mode`: `fast` немесе `normal`, default `fast`
- `--limit`: article саны, default `5`
- `--replace-today`: article нәтижесін `output/articles/YYYY-MM-DD/latest/` ішіне таза қайта жазу

Run modes:

- `fast`: RSS only. GDELT өшіріледі. GUI daily default осы.
- `normal`: RSS + GDELT. GDELT `maxrecords=20`, `delay_seconds=15`.

Негізгі функциялар:

- `main()` — argparse, env load, command routing.
- `load_settings()` — DB/source/output/timeout env мәндерін жинайды.
- `load_sources(path)` — `sources.json` оқиды, қате болса бос config береді.
- `collect(settings)` — collect -> dedupe -> classify -> filter -> insert.
- `apply_run_mode(gdelt_config, mode)` — fast/normal параметрлерін GDELT config-ке қолданады.
- `report(settings)` — DB-ден recent news алып digest жасайды.
- `article(settings, limit, replace_today)` — DB-ден recent news алып cluster таңдайды, мақалаларды сақтайды.

`all` командасы `collect` және `report` орындайды. `article` бөлек command, сондықтан GUI daily preset `all` кейін `article --replace-today` қосады.

## 5.1. Редакциялық 5 slot

`app/services/article_writer.py` article command үшін `select_editorial_article_clusters(clusters, limit=5)` қолданады. Күнделікті output мына slot-тарды ретімен толтыруға тырысады:

1. `ukraine_russia` — Украина-Ресей
2. `middle_east` — Таяу Шығыс
3. `china_influence` — Қытайдың агрессиялық ықпалы
4. `kazakhstan_domestic` — Қазақстанның ішкі саясаты
5. `world_geopolitics` — Жалпы әлемдік геосаяси ахуал

Әр slot үшін ең жақсы cluster `final_score`, `source_count`, `max_source_score` бойынша таңдалады. Selector rejected немесе weak aggregation title-дарды өткізбейді және title fingerprint duplicate болса, келесі кандидатқа өтеді. Slot табылмаса, log:

```text
[article] slot missing: china_influence
```

Бұл жағдайда fake мақала жасалмайды; saved article саны available slot санына тең болады. Article frontmatter ішінде slot metadata сақталады:

```yaml
slot: "china_influence"
slot_label: "Қытайдың агрессиялық ықпалы"
```

GUI card осы `slot_label` мәнін көрсетеді. Digest ішінде `## Редакциялық 5 бағыт` бөлімі slot бойынша available summary жазады, missing бағыттарды бөлек белгілейді.

China/Taiwan influence coverage үшін classifier tags:

- `china_influence`
- `china_aggression`
- `grey_zone`
- `south_china_sea`
- `belt_and_road`
- `central_asia`

Kazakhstan domestic coverage үшін:

- `kazakhstan`
- `kazakhstan_politics`

`sources.json` RSS үшін тек metadata feed-терді қолданады. Working RSS бар жерде RSS қосылады; Taiwan News, Taiwan Today және Taiwan MOFA сияқты RSS тұрақсыз немесе RSS емес endpoint болған жағдайда coverage GDELT query және domain allowlist арқылы жүреді. Full article scraping қосылмайды.

## 6. `app/web.py` GUI және API endpoints

GUI `ThreadingHTTPServer` және `BaseHTTPRequestHandler` арқылы жазылған. Flask/FastAPI жоқ.

Негізгі state:

- `JobState.running`
- `JobState.command`
- `JobState.preset`
- `JobState.mode`
- `JobState.limit`
- `JobState.ai_provider`
- `JobState.output`
- `JobState.process`
- `JobState.stop_requested`

GUI батырмалары:

- **Бүгінгі 5 мақаланы жасау** — daily preset.
- **Тек жаңалық жинау** — `collect`.
- **Дайджест жасау** — `report`.
- **Мақала жасау** — `article --replace-today`.
- **Тоқтату** — running subprocess-ті terminate етеді, 5 секундтан кейін kill жасайды.

Advanced settings:

- Mode: `fast`, `normal`
- Мақала саны: 1-10 аралығы, default 5
- AI provider: `none`, `ollama`, `lmstudio`

Endpoints:

### `GET /`

HTML GUI қайтарады.

### `GET /api/status`

Current job snapshot қайтарады. Ішінде:

- status label/message
- соңғы log output
- latest digest preview
- today folder label
- latest articles: тек `output/articles/YYYY-MM-DD/latest/*.md`
- `ai_provider`
- `ollama_available`
- `ollama_loading`
- `ollama_status`: `Қосылмаған`, `Дайындалып жатыр`, `Дайын`, `Қате`
- `ollama_status_message`
- `lmstudio_available`
- `current_model`
- `last_ai_provider`
- `last_ai_model`
- `last_ai_used_fallback`
- `last_ai_reject_reason`
- `last_ai_json_parsed`
- `last_ai_debug_folder`
- `last_ai_raw_preview`
- `last_ai_rendered_preview`

Ескі article файлдары негізгі экранда көрсетілмейді.

### `GET /api/digest`

Соңғы `output/digest_*.md` толық content-ін қайтарады.

### `POST /api/run-preset`

Daily preset іске қосады.

Payload үлгісі:

```json
{
  "preset": "daily_articles",
  "mode": "fast",
  "limit": 5,
  "ai_provider": "ollama"
}
```

Ішкі steps:

```bash
python app/main.py all --mode fast
python app/main.py article --mode fast --limit 5 --replace-today
```

### `POST /api/run`

Жеке command іске қосады.

Payload үлгісі:

```json
{
  "command": "article",
  "mode": "fast",
  "limit": 5,
  "ai_provider": "lmstudio"
}
```

Егер command `article` болса, GUI автоматты түрде `--replace-today` қосады.

### `POST /api/ai-provider`

GUI-дегі **ИИ режимі** select өзгергенде шақырылады.

Payload үлгісі:

```json
{
  "ai_provider": "ollama"
}
```

Бұл endpoint тек GUI state ауыстырады. Docker/Ollama setup бұл жерде жүрмейді; Ollama service/model дайындауды тек `start.sh` background-та бастайды.

### `POST /api/stop`

Running job тоқтатады. Жұмыс жоқ болса `409` қайтарады.

### `POST /api/open-folder`

`output/articles/YYYY-MM-DD/latest/` папкасын host-та ашуға тырысады. Docker ішінде `open`/`xdg-open` әрдайым жұмыс істемеуі мүмкін, сондықтан response ішінде path беріледі.

GUI summary `build_run_summary()` арқылы log-тан мына сандарды оқиды:

- Жиналған RSS жазбалар
- Бірегей жаңалықтар
- Жаңа жазбалар
- Мақалаға таңдалған оқиғалар
- Сақталған мақалалар

`жаңа жазбалар: 0` болса, user-ге мақалалар бұрын сақталған соңғы релевант оқиғалардан жасалғанын түсіндіреді.

## 7. Data flow

Толық flow:

```text
sources.json
  |
  +-- rss_sources[] ----------------------+
  |                                       |
  |       collect_rss_sources             |
  |       collect_rss_source              |
  |       parse_entry_date                |
  |                                       |
  +-- gdelt.queries[] --------------------+
          collect_gdelt
          fetch_gdelt
          parse_article
          parse_gdelt_date
                  |
                  v
              NewsItem dict
                  |
          deduplicate_items
                  |
          classify_items
                  |
          filter_relevant_items
                  |
             insert_news
                  |
           data/news.sqlite3
                  |
           fetch_recent_news
                  |
          classify/filter again
                  |
             cluster_events
                  |
       +----------+----------+
       |                     |
 generate_report       select_article_clusters
       |                     |
 output/digest       generate_kazakh_article
                             |
                       save_article
                             |
                output/articles/YYYY-MM-DD/latest
```

Назар аудар: RSS және GDELT collector толық article body алмайды. RSS summary feed ішінен келеді; GDELT summary ретінде `"Found by GDELT query: ..."` сияқты қысқа metadata қолданады.

## 8. SQLite schema

DB path default: `data/news.sqlite3`.

Кесте: `news`

```sql
CREATE TABLE IF NOT EXISTS news (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    url TEXT UNIQUE NOT NULL,
    source TEXT,
    published_at TEXT,
    summary TEXT,
    tags TEXT,
    importance INTEGER DEFAULT 0,
    source_score INTEGER DEFAULT 0,
    relevance_score INTEGER DEFAULT 0,
    final_score INTEGER DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    processed INTEGER DEFAULT 0
);
```

Migration helper:

- `migrate_db(conn)` ескі DB-де жоқ болса `source_score`, `relevance_score`, `final_score` бағандарын қосады.

Негізгі DB функциялар:

- `get_connection(db_path)` — parent folder жасап, sqlite connection ашады.
- `init_db(db_path)` — schema және migration.
- `get_existing_titles(conn)` — title duplicate тексеруге керек.
- `insert_news(conn, items)` — `INSERT OR IGNORE`, URL unique.
- `fetch_recent_news(conn, limit=500)` — `final_score`, `importance`, date бойынша top recent items.
- `row_to_dict(row)` — JSON tags-ті list-ке қайтарады.

## 9. RSS collector

Файл: `app/collectors/rss_collector.py`

Негізгі функциялар:

- `collect_rss_source(source, timeout=20, max_items=30)`
- `collect_rss_sources(sources, timeout=20, max_items=30)`
- `parse_entry_date(entry)`

Қалай істейді:

- `requests.get()` арқылы feed жүктейді.
- User-Agent: `geo-news-bot/0.1 (+local research MVP)`.
- `feedparser.parse()` арқылы entries оқиды.
- Әр entry үшін:
  - title: `normalize_spaces`
  - url: `normalize_url`
  - summary/description: `clean_html`, max 600 chars
  - published_at: UTC ISO date
- `NewsItem(...).to_dict()` қайтарады.

RSS source ішінде `"enabled": false` болса, collector оны өткізіп кетеді.

## 10. GDELT collector

Файл: `app/collectors/gdelt_collector.py`

Endpoint:

```text
https://api.gdeltproject.org/api/v2/doc/doc
```

Негізгі функциялар:

- `collect_gdelt(queries, timeout, max_records, delay_seconds, retry_delay_seconds)`
- `fetch_gdelt(params, timeout)`
- `parse_article(article, query)`
- `parse_gdelt_date(value)`

Қалай істейді:

- Әр query үшін `mode=ArtList`, `format=json`, `sort=HybridRel`.
- `429` болса бір рет `retry_delay_seconds` күтіп қайта сұрайды.
- Қайта `429` болса query өткізіледі, app құламайды.
- `parse_article()` доменді `source_quality.is_allowed_gdelt_domain()` арқылы тексереді.
- GDELT summary толық мақала емес, тек `Found by GDELT query: ...`.

Default мәндер:

- `DEFAULT_MAX_RECORDS = 20`
- `DEFAULT_DELAY_SECONDS = 15`
- `DEFAULT_RETRY_DELAY_SECONDS = 60`
- `DEFAULT_TIMEOUT_SECONDS = 20`

`fast` режимде GDELT толық өшіріледі.

## 11. `app/services` файлдары

### `ai_writer.py`

Ортақ AI router.

- `generate_article_text(prompt) -> AITextResult`
- `selected_provider() -> str`

Provider таңдау:

- `AI_PROVIDER=lmstudio` болса LM Studio.
- `AI_PROVIDER=ollama` болса Ollama.
- Әйтпесе `USE_OLLAMA=true` болса compatibility ретінде Ollama.
- Басқа жағдайда fallback.

### `article_writer.py`

Қазақша мақалаларға жауапты.

Негізгі функциялар:

- `select_article_clusters(clusters, limit=5)`
- `generate_kazakh_article(cluster)`
- `save_article(title, content, index, mode, source_count, replace_today=False, date=None)`
- `prepare_article_output(replace_today=False, date=None)`
- `article_output_dir(article_date, replace_today=False)`
- `build_prompt(cluster)`
- `parse_ai_article_json(raw_text)`
- `render_structured_article(title, sections, cluster)`
- `is_quality_structured_article(sections, rendered, ai_result, cluster)`
- `is_good_kazakh_article_sections(sections, cluster)`
- `fallback_article(cluster)`
- `unique_filename(out_dir, index, slug)`
- `title_fingerprint(cluster)`
- `is_article_topic(cluster)`
- `is_rejected_article_title(cluster)`
- `article_topic(cluster)`
- `is_duplicate_fingerprint(fingerprint, selected)`
- `extract_markdown_title(content)`
- `kazakh_headline(cluster)`
- `slugify(title)`
- `yaml_escape(value)`

Article-specific reject patterns:

- `world news in brief`
- `news in brief`
- `as it happened`
- `live updates`
- `liveblog`
- `briefing`
- `roundup`
- `opinion`
- `analysis video`
- `video only`
- `europe live`

Topic diversity limits:

- `usa_iran`: 2
- `middle_east`: 2
- `russia_ukraine`: 2
- `nato_eu`: 2
- `china_taiwan`: 1
- `other`: 1

AI Kazakh quality guard (`is_good_kazakh_article_sections`):

- JSON parse сәтті болса да pseudo-Kazakh / gibberish мәтін қабылданбайды.
- Bad phrase, bullet-prefix (`- `, `• `), event keyword overlap (<2), repeated phrase және too generic checks бар.
- Сапа тексерісінен өтпесе `reject_reason` `*_decision.json` ішінде (`gibberish_text`, `event_not_mentioned`, т.б.) жазылып, fallback template қолданылады.
- Debug: `quality_checks`, `bad_phrase_detected`, `event_keyword_overlap`, `quality_error_sample`.

### `classifier.py`

Keyword classifier және score есептейді.

Негізгі функциялар:

- `classify_item(item)`
- `classify_items(items)`
- `find_tags(text)`
- `find_importance(text)`
- `find_relevance_score(item)`
- `find_final_score(item)`

Tags `TAG_KEYWORDS` арқылы табылады: `usa`, `iran`, `russia`, `ukraine`, `china`, `nato`, `eu`, `sanctions`, `war`, `nuclear`, `middle_east`, `taiwan`, `diplomacy`, `military`, тағы басқа.

### `deduplicate.py`

Duplicate filter.

- `deduplicate_items(items, existing_titles=None, similarity_threshold=0.92)`
- `is_similar_to_existing(title, existing_titles, threshold=0.92)`

URL exact duplicate және normalized title similarity қолданылады.

### `event_clusterer.py`

Ұқсас жаңалықтарды event cluster-ге біріктіреді.

Негізгі функциялар:

- `cluster_events(items, similarity_threshold=0.55)`
- `finalize_cluster(cluster)`
- `item_sort_key(item)`
- `title_tokens(title)`
- `should_join_cluster(...)`
- `event_signature(tokens, tags)`
- `strong_signature_match(left, right)`
- `has_common_keywords(left, right)`
- `best_summary(items)`
- `unique_links(items)`
- `is_good_supporting_source(item)`
- `unique_values(values)`

Cluster output өрістері:

- `title`
- `summary`
- `tags`
- `sources`
- `links`
- `items`
- `source_count`
- `max_source_score`
- `final_score`

Cluster `final_score` формуласы:

```text
max(item.final_score) + source_count * 2 + min(len(items), 5)
```

### `lmstudio_writer.py`

LM Studio local server provider.

Defaults:

- `LMSTUDIO_URL=http://host.docker.internal:1234/v1`
- `LMSTUDIO_MODEL=model-identifier`
- `LMSTUDIO_TIMEOUT=180`

Негізгі функциялар:

- `is_available()` — `GET /models`, timeout 5 sec.
- `generate_text(prompt)` — `POST /chat/completions`.
- `base_url()`
- `timeout()`
- `log_unavailable(exc)`
- `debug_ai()`

Қате болса `None` қайтарады. Бір рет:

```text
[ai] LM Studio қолжетімсіз, резерв шаблон қолданылады
```

Толық exception тек `DEBUG_AI=true` болса шығады.

### `ollama_writer.py`

Ollama provider.

Defaults:

- `OLLAMA_URL=http://ollama:11434`
- `OLLAMA_MODEL=qwen2.5:7b` — recommended default for Kazakh article quality
- `OLLAMA_TIMEOUT=180`

Recommended models for Kazakh news writing:

- `qwen2.5:3b` — light mode; weak Kazakh quality, fallback often
- `qwen2.5:7b` — recommended balance of quality and resource use
- `qwen2.5:14b` — heavy quality mode if hardware allows

Article JSON generation options (sent in `/api/generate` payload):

- `temperature`: 0.2
- `top_p`: 0.8
- `repeat_penalty`: 1.2
- `num_predict`: 500

Негізгі функциялар:

- `use_ollama()`
- `generate_draft(cluster)`
- `generate_text(prompt, task_name="мәтін генерациялау")`
- `ollama_available()` — `GET /api/tags`; selected `OLLAMA_MODEL` must be present.
- `log_ollama_unavailable(message)`
- `ollama_timeout()`
- `build_prompt(cluster)`

Text generation endpoint:

```text
POST {OLLAMA_URL}/api/generate
```

Payload ішінде `stream: false` және article JSON options:

```json
{
  "options": {
    "temperature": 0.2,
    "top_p": 0.8,
    "repeat_penalty": 1.2,
    "num_predict": 500
  }
}
```

### `relevance.py`

Геосаяси relevance және noise filter.

Негізгі функциялар:

- `is_relevant_item(item)`
- `filter_relevant_items(items)`
- `has_blacklisted_topic(text, tags)`
- `is_domestic_noise(text, tags)`
- `is_single_country_admin_noise(text, tags)`
- `is_weak_single_tag_noise(text, tags)`
- `item_text(item)`
- `keyword_in_text(text, keyword)`

Blacklist мысалдары: sport, entertainment, weather, crash, crime, music, football, earthquake, cybersecurity және т.б. Бірақ `war`, `sanctions`, `military` сияқты exceptions бар.

### `report_generator.py`

Markdown digest жасайды.

Негізгі функциялар:

- `generate_report(items, output_dir)`
- `select_top_clusters(clusters)`
- `select_topic_clusters(clusters)`
- `is_report_topic(cluster)`
- `build_headlines(clusters)`
- `build_top_events(clusters)`
- `build_topic_sections(clusters)`
- `group_clusters_by_topic(clusters)`
- `render_event_block(cluster, heading_level=3)`
- `build_draft_articles(clusters)`
- `has_draft_ready_summary(cluster)`
- `render_article(cluster)`
- `article_profile(cluster)`
- `human_topic(cluster)`
- `short_summary(cluster)`
- `format_tags(cluster)`
- `format_links(cluster, limit=3)`
- `cluster_text(cluster)`
- `link_label(link)`

### `source_quality.py`

Source/domain trust score.

Негізгі функциялар:

- `get_domain(url)`
- `domain_matches(domain, allowed_domain)`
- `is_allowed_gdelt_domain(domain)`
- `is_gdelt_item(item)`
- `source_score_for_item(item)`

Score мысалдары:

- Reuters/AP/official domains: 10
- BBC/DW/France 24: 8
- Al Jazeera/The Guardian: 7
- allowed GDELT item: 7
- fallback: 3

### `topic_score.py`

Topic helper functions.

- `is_usa_iran(tags)`
- `is_china_taiwan(tags, text)`
- `is_weak_gdelt_summary(summary)`

`is_weak_gdelt_summary()` GDELT query-only summary сияқты әлсіз summary-ларды supporting link ретінде сақтықпен қолдануға көмектеседі.

## 12. Scoring system

Item-level төрт негізгі score:

### `importance`

`classifier.find_importance()` есептейді:

- 3: attack, missile, killed, invasion, nuclear, sanctions, ceasefire, troops, strike.
- 2: diplomacy, talks, minister, president, warning, agreement.
- 1: қалған relevant item.

### `source_score`

`source_quality.source_score_for_item()` есептейді. Ресми және сапалы халықаралық дереккөздер жоғары score алады.

### `relevance_score`

`classifier.find_relevance_score()` есептейді:

- Егер `is_relevant_item()` false болса: 0.
- Әйтпесе: `2 + min(important_tag_count, 4)`.

### `final_score`

`classifier.find_final_score()` формуласы:

```text
importance * 10 + source_score + relevance_score
```

Cluster-level `final_score` бөлек:

```text
max(item.final_score) + source_count * 2 + min(len(items), 5)
```

## 13. Event clustering

Event clustering `app/services/event_clusterer.py` ішінде.

Мақсаты: бір оқиғаны әр дереккөз бөлек жазса, оларды бір cluster-ге жинау.

Қолданылатын белгілер:

- normalized title tokens
- stopwords алып тастау
- aliases: `us`, `u.s`, `america` -> `usa`; `strikes` -> `strike`; `iranian` -> `iran` т.б.
- signature keywords: `iran`, `nuclear`, `usa`, `strike`, `ceasefire`, `hormuz`, `ukraine`, `russia`, `nato`, `china`, `taiwan`, т.б.
- special markers:
  - `usa_iran_escalation`
  - `iran_nuclear`
  - `hormuz_evacuation`
  - `israel_lebanon`
  - `russia_ukraine_strikes`

Join logic:

- Strong signature match болса cluster-ге қосылады.
- Әйтпесе common important keywords керек.
- Similarity ratio threshold default `0.55`.
- Common token саны және Jaccard fallback қолданылады.

Cluster finalization:

- Lead item ең жоғары score/source/date бойынша таңдалады.
- Summary ретінде weak емес алғашқы summary алынады.
- Links URL және `(source, title)` duplicate бойынша тазартылады.
- Weak GDELT summary бар link тек source сапасы жеткілікті болса supporting source ретінде өтеді.

## 14. Digest generation

Digest output:

```text
output/digest_YYYY-MM-DD.md
```

Күні `APP_TIMEZONE` арқылы `today_str()` функциясынан алынады.

Digest құрылымы:

```markdown
# Геосаяси дайджест — YYYY-MM-DD

## Негізгі жаңалықтар
## Басты оқиғалар
## Бағыттар бойынша
### Ресей / Украина
### АҚШ / Иран
### Қытай / Тайвань
### НАТО / ЕО
### Таяу Шығыс
## Мақала жобалары
```

`select_top_clusters()`:

- `final_score >= 25`
- `is_report_topic(cluster)` true
- максимум 12 cluster

`select_topic_clusters()`:

- `final_score >= 20`
- `is_report_topic(cluster)` true
- максимум 20 cluster

`build_draft_articles()`:

- top clusters ішінен `final_score >= 40`
- `source_count >= 2` немесе `max_source_score >= 10`
- weak емес summary болуы керек
- максимум 3 draft
- AI provider бар болса `ai_writer.generate_article_text()` қолданады, болмаса `render_article()` fallback.

## 15. Article generation, limit, latest folder, fallback

CLI:

```bash
python app/main.py article --mode fast
python app/main.py article --mode fast --limit 5
python app/main.py article --mode fast --limit 5 --replace-today
```

Default `--limit` мәні: 5.

Article flow:

1. `fetch_recent_news()` соңғы 500 жаңалықты алады.
2. `classify_items()` және `filter_relevant_items()` қайта қолданылады.
3. `cluster_events()` cluster жасайды.
4. `select_article_clusters(clusters, limit)` article candidates таңдайды.
5. Әр cluster үшін `generate_kazakh_article(cluster)` шақырылады.
6. `save_article(...)` Markdown файл сақтайды.

Output:

- `--replace-today` жоқ болса: `output/articles/YYYY-MM-DD/`
- `--replace-today` болса: `output/articles/YYYY-MM-DD/latest/`

`prepare_article_output(replace_today=True)` тек `latest/` папкасын тазалайды. `output/articles/YYYY-MM-DD/` түбіріндегі архив/ескі файлдарды өшірмейді.

Filename:

```text
01_slug.md
02_slug.md
```

Егер файл бар болса:

```text
01_slug_2.md
```

`latest/` daily workflow-та әр run алдында тазаланатындықтан GUI-де `_4`, `_6`, `_7` сияқты ескі файлдар шықпауы керек.

Article Markdown front matter:

```yaml
---
title: "..."
date: "YYYY-MM-DD"
source_count: 3
mode: "fallback"
---
```

Body құрылымы:

```markdown
# Тақырып

**Лид:**

**Не болды:**

**Неге маңызды:**

**Әрі қарай не күту керек:**

**Дереккөздер:**
```

Fallback:

- `fallback_article(cluster)` техникалық сөздерді қолданбайды.
- Мақала ішінде `кластер`, `метадерек` сияқты сөздер болмауы керек.
- Source атаулары табиғи беріледі.
- Summary әлсіз немесе ағылшын болса, сақ generic емес, topic-based мәтінге түседі.

AI quality check:

- AI модель толық Markdown жазбайды; тек JSON section content қайтарады.
- App JSON-ды parse edip, Markdown құрылымын өзі render ededi.
- JSON parse сәтті болса, барлық 4 өріс (`lead`, `what_happened`, `why_important`, `what_next`) бар және тым қысқа емес.
- `finish_reason`/`done_reason` = `length` болса қабылданбайды.
- Banned phrases болмауы керек.
- Cyrillic/Kazakh мәтін жеткілікті болуы керек.
- Сапасыз AI output болса fallback қолданылады.
- Reject reason әрқашан log/debug status ішінде сақталады.

### Structured JSON AI output

AI енді толық Markdown мақала жазбайды. Ол тек мына JSON қайтарады:

```json
{
  "lead": "...",
  "what_happened": "...",
  "why_important": "...",
  "what_next": "..."
}
```

App `parse_ai_article_json()` арқылы JSON-ды оқиды, `render_structured_article()` арқылы Markdown құрылымын өзі жасайды. Heading, дереккөз тізімі және `# тақырып` app кодында беріледі; модель тек section мәтінін жазады.

Prompt тек cluster title, summary, tags, max 3 source және max 3 source title/URL қамтиды. Толық digest немесе ұзын unrelated context жіберілмейді. Prompt ішінде қысқа GOOD JSON мысалы бар — модель стильді еліктеуі керек, фактілерді емес.

### AI article debug

Қосу:

```bash
DEBUG_AI_ARTICLES=true AI_PROVIDER=ollama python app/main.py article --mode fast --limit 1 --replace-today
```

Default:

```env
DEBUG_AI_ARTICLES=false
```

Debug output:

```text
output/debug_ai/YYYY-MM-DD/
├── 01_prompt.md
├── 01_raw_response.md
├── 01_parsed_sections.json
├── 01_rendered_article.md
├── 01_decision.json
└── latest_status.json
```

`data/ai_status.json` әр generation сайын жазылады. GUI және `/api/status` соңғы AI күйін осы файлдан немесе `output/debug_ai/YYYY-MM-DD/latest_status.json` ішінен оқиды. Job жүріп тұрғанда GUI ескі AI diagnostics көрсетпейді.

`01_decision.json` негізгі өрістері:

```json
{
  "provider": "ollama",
  "model": "qwen2.5:7b",
  "used_fallback": false,
  "reject_reason": null,
  "raw_length": 1704,
  "json_parsed": true,
  "fields": ["lead", "what_happened", "why_important", "what_next"]
}
```

`DEBUG_AI_ARTICLES=true` болса raw response ешқашан silent жоғалмайды: quality guard reject етсе де `*_raw_response.md` сақталады. Parsed sections `*_parsed_sections.json` ішінде, app render etken Markdown `*_rendered_article.md` ішінде сақталады. Paragraph break (`\n\n`) сақталады; whitespace collapse үшін `" ".join(text.split())` қолданылмайды.

Reject reason meanings:

- `json_parse_failed` — AI response ішінен JSON оқылмады.
- `missing_json_fields` — `lead`, `what_happened`, `why_important`, `what_next` өрістерінің біреуі жоқ.
- `empty_json_field` — JSON өрісі бос немесе тым қысқа.
- `empty_response` — provider бос мәтін қайтарды.
- `too_short` — section мәтіні сөз саны бойынша жеткіліксіз.
- `too_long` — section мәтіні 320 сөзден көп.
- `finish_reason_length` — provider output-ты length/truncation себебімен тоқтатты.
- `repeated_phrases` — бір сөйлем/ұзын тіркес шамадан тыс қайталанды.
- `banned_phrase` — banned nonsense phrase табылды.
- `low_kazakh_text_ratio` — қазақ/кирилл мәтіні жеткіліксіз немесе latin үлесі көп.
- `markdown_broken` — Markdown fence немесе merge marker сияқты broken белгі бар.
- `ollama_not_ready` — Ollama `/api/tags` немесе generation endpoint қолжетімсіз.
- `lmstudio_not_ready` — LM Studio `/models` немесе chat endpoint қолжетімсіз.
- `provider_disabled` — `AI_PROVIDER=none` немесе provider таңдалмаған.

Troubleshoot flow:

1. `DEBUG_AI_ARTICLES=true` қойып бір мақала жаса.
2. `output/debug_ai/YYYY-MM-DD/01_prompt.md` ішінде prompt JSON-only екенін және cluster title, summary, 3 source max, tags ғана барын тексер.
3. `01_raw_response.md` ішінде AI нақты не қайтарғанын қара.
4. `01_parsed_sections.json` ішінде parse edilgen section content-ті қара.
5. `01_rendered_article.md` ішінде app render etken final Markdown-ды қара.
6. `01_decision.json` ішінен `used_fallback`, `reject_reason`, `json_parsed`, `fields`, `raw_length` қара.
7. `reject_reason=ollama_not_ready` болса `data/ollama_status.json`, `data/ollama_setup.log`, `docker compose --profile ollama exec ollama ollama list` тексер.
8. `reject_reason=finish_reason_length` болса provider max output қысқа; бұл run fallback қолданады.
9. `reject_reason=json_parse_failed` болса модель JSON орнына Markdown/түсіндіру жазған болуы мүмкін; fallback қолданылады.

Article writer log үлгісі:

```text
[ai] provider=ollama model=qwen2.5:7b
[ai] ollama available=true
[ai] raw response length=1234
[ai] json parsed=true
[ai] quality accepted=true
```

Fallback болса:

```text
[ai] json parsed=false reason=json_parse_failed
[ai] quality accepted=false reason=json_parse_failed
[article] fallback қолданылды
```

## 16. AI providers: none, LM Studio, Ollama

Preferred env:

```env
AI_PROVIDER=none
# none | ollama | lmstudio
DEBUG_AI_ARTICLES=false
```

Compatibility env:

```env
USE_OLLAMA=false
```

### none

AI қолданылмайды. Report draft және article generation fallback template арқылы жүреді.

```bash
docker compose run --rm -e AI_PROVIDER=none app python app/main.py article --mode fast --limit 5
```

### LM Studio

Mac-та local LM Studio server қолдануға арналған.

Env:

```env
AI_PROVIDER=lmstudio
LMSTUDIO_URL=http://host.docker.internal:1234/v1
LMSTUDIO_MODEL=model-identifier
LMSTUDIO_TIMEOUT=180
```

LM Studio endpoint:

- `GET /models`
- `POST /chat/completions`

Docker ішінен Mac host-қа жету үшін default URL `host.docker.internal`.

Run:

```bash
docker compose run --rm \
  -e AI_PROVIDER=lmstudio \
  -e LMSTUDIO_MODEL=model-identifier \
  app python app/main.py article --mode fast --limit 5
```

LM Studio өшірулі болса app құламайды, бір рет log жазып fallback қолданады.

### Ollama

Ollama user үшін default AI режим. Docker/Ollama setup GUI ішінде жүрмейді; оны `start.sh` background-та іске қосады.

Env:

```env
AI_PROVIDER=ollama
USE_OLLAMA=true
OLLAMA_URL=http://ollama:11434
OLLAMA_MODEL=qwen2.5:7b
OLLAMA_TIMEOUT=180
```

`qwen2.5:7b` ұсынылатын default. `qwen2.5:3b` жеңіл режим ретінде жұмыс істейді, бірақ қазақша мәтіні әлсіз болғандықтан fallback жиі болады. `qwen2.5:14b` — ауыр quality mode.

Ollama endpoint:

- preflight: `GET /api/tags`
- generation: `POST /api/generate`

One-click lifecycle:

- `start.command` → `start.sh`.
- `start.sh` GUI service-ті көтереді.
- `start.sh` `docker compose --profile ollama up -d ollama` және `ollama-pull` командаларын background-та жүргізеді.
- Setup log: `data/ollama_setup.log`.
- Setup status: `data/ollama_status.json`.
- `/api/status` осы status file мен live `/api/tags` check нәтижесін біріктіріп, `ollama_available`, `ollama_loading`, `ollama_status_message`, `current_model` қайтарады.
- Job басталғанда Ollama дайын болса subprocess env: `AI_PROVIDER=ollama`, `USE_OLLAMA=true`.
- Дайын болмаса subprocess env: `AI_PROVIDER=none`, `USE_OLLAMA=false`; fallback template қолданылады.
- Background setup жалғаса береді; дайын болған соң келесі генерация автоматты Ollama қолданады.

Manual developer commands әлі де бар:

```bash
docker compose --profile ollama up -d ollama
docker compose --profile ollama --profile setup run --rm ollama-pull
docker compose --profile ollama run --rm -e AI_PROVIDER=ollama -e USE_OLLAMA=true app python app/main.py article --mode fast --limit 5
```

Default `docker compose config` Ollama image жүктемейді. One-click user flow кезінде `start.sh` Ollama setup-ты background-та бастайды.

## 17. Docker architecture және profiles

`docker-compose.yml` services:

### `app`

- Build: local Dockerfile.
- Command: `python app/main.py all`
- Volumes:
  - `./data:/app/data`
  - `./output:/app/output`
  - `./sources.json:/app/sources.json:ro`
- Default compose service. Ollama-ға `depends_on` жоқ.

### `gui`

- Profile: `gui`
- Port: `8000:8000`
- Command: `python app/web.py`
- Сол data/output/sources volumes қолданады.
- Docker socket mount жоқ.
- GUI Docker/Ollama command жүргізбейді; тек local subprocess арқылы `app/main.py` командаларын іске қосады.

Run:

```bash
docker compose --profile gui up -d --build gui
```

### `ollama`

- Profile: `ollama`
- Image: `ollama/ollama:latest`
- Container: `geo-news-ollama`
- Port: `11434:11434`
- Volume: `ollama_data:/root/.ollama`
- Restart: `unless-stopped`

Default `docker compose config` ішінде іске қосылмайды. One-click user flow кезінде `start.sh` осы service-ті background-та көтереді.

### `ollama-pull`

- Profiles: `ollama`, `setup`
- `OLLAMA_HOST=http://ollama:11434`
- `OLLAMA_MODEL=${OLLAMA_MODEL:-qwen2.5:7b}`
- Command: `sleep 10 && ollama pull $$OLLAMA_MODEL`

### `docker-compose.gpu.yml`

Future PC only. NVIDIA GPU бар ПК-да Ollama сервисіне GPU device reservation қосады.

Run:

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml --profile ollama up -d ollama
```

NVIDIA driver және NVIDIA Container Toolkit керек.

## 18. `start.sh` / `start.command` / `stop.sh` / `stop.command`

### `start.sh`

Қарапайым user launcher:

1. Script орналасқан папкаға `cd` жасайды.
2. Docker command барын тексереді.
3. Docker daemon running екенін `docker info` арқылы тексереді.
4. `.env` жоқ болса `.env.example`-ден көшіреді.
5. `data/` және `output/` папкаларын дайындайды.
6. GUI container көтереді:

```bash
docker compose --profile gui up -d --build gui
```

7. Ollama setup-ты background-та бастайды:

```bash
docker compose --profile ollama up -d ollama
docker compose --profile ollama --profile setup run --rm ollama-pull
```

8. Setup log/status жазады:

```text
data/ollama_setup.log
data/ollama_status.json
```

9. Browser ашады: `http://localhost:8000`.

### `start.command`

macOS double-click launcher:

```bash
cd "$(dirname "$0")"
./start.sh
```

### `stop.sh`

GUI және Ollama service-терін тоқтатады:

```bash
docker compose --profile gui --profile ollama down
```

### `stop.command`

macOS double-click stop launcher:

```bash
cd "$(dirname "$0")"
./stop.sh
```

### `start_gui.sh`

Compatibility wrapper:

```sh
cd "$(dirname "$0")"
./start.sh
```

## 19. Output files

Gitignored local output:

```text
data/news.sqlite3
output/digest_YYYY-MM-DD.md
output/articles/YYYY-MM-DD/*.md
output/articles/YYYY-MM-DD/latest/*.md
```

Digest:

```text
output/digest_2026-06-30.md
```

Article latest:

```text
output/articles/2026-06-30/latest/
├── 01_*.md
├── 02_*.md
├── 03_*.md
├── 04_*.md
└── 05_*.md
```

Күн `APP_TIMEZONE` арқылы анықталады. Default: `Asia/Almaty`.

## 20. Config files

### `.env.example`

Негізгі env:

```env
DATABASE_PATH=data/news.sqlite3
SOURCES_PATH=sources.json
OUTPUT_DIR=output
APP_TIMEZONE=Asia/Almaty
REQUEST_TIMEOUT=20
MAX_RSS_ITEMS_PER_SOURCE=30
AI_PROVIDER=none
USE_OLLAMA=false
OLLAMA_URL=http://ollama:11434
OLLAMA_MODEL=qwen2.5:7b
OLLAMA_TIMEOUT=180
LMSTUDIO_URL=http://host.docker.internal:1234/v1
LMSTUDIO_MODEL=model-identifier
LMSTUDIO_TIMEOUT=180
```

### `sources.json`

Active sources:

- The White House News
- Defense.gov
- UN News
- Kremlin
- BBC World
- Al Jazeera
- The Guardian World
- Deutsche Welle
- France 24

GDELT queries:

- Russia Ukraine war
- USA Iran sanctions
- China Taiwan
- NATO Ukraine
- Middle East escalation
- Iran nuclear
- US China tensions

### `sources.disabled.json`

Қазіргі MVP-де disabled/candidate ретінде сақталған sources. Әр source жанында неге active емес екені `note` арқылы жазылған. Мысалы тұрақты RSS расталмаған, HTML қайтарған немесе automatic request-ті бұғаттауы мүмкін.

## 21. Developer commands

Local Python:

```bash
python3 -m compileall app
python app/main.py collect --mode fast
python app/main.py report --mode fast
python app/main.py all --mode fast
python app/main.py article --mode fast --limit 5 --replace-today
python app/web.py
```

Docker:

```bash
docker compose config
docker compose run --rm app python app/main.py all --mode fast
docker compose run --rm app python app/main.py all --mode normal
docker compose run --rm app python app/main.py article --mode fast --limit 5 --replace-today
docker compose --profile gui up -d --build gui
```

GUI API quick checks:

```bash
curl http://localhost:8000/api/status
curl http://localhost:8000/api/digest
```

LM Studio fallback smoke:

```bash
docker compose run --rm \
  -e AI_PROVIDER=lmstudio \
  -e LMSTUDIO_URL=http://127.0.0.1:9 \
  app python app/main.py article --mode fast --limit 5
```

Ollama optional:

```bash
docker compose --profile ollama up -d ollama
docker compose --profile ollama --profile setup run --rm ollama-pull
docker compose --profile ollama run --rm -e AI_PROVIDER=ollama -e USE_OLLAMA=true app python app/main.py article --mode fast --limit 5
```

## 22. Troubleshooting

### Docker image тым көп жүктеліп жатыр

Default command Ollama жүктемеуі керек:

```bash
docker compose run --rm app python app/main.py all --mode fast
```

Егер Ollama жүктелсе, `docker-compose.yml` ішінде `app.depends_on: ollama` жоқ екенін және `ollama` сервисінде `profiles: [ollama]` барын тексер.

GUI ашылғанда да Ollama жүктелмеуі керек. Pull/start тек user GUI-де **ИИ режимі → Ollama** таңдағанда басталады.

### GUI ашылмайды

Тексеру:

```bash
docker compose --profile gui ps
docker compose --profile gui logs gui
curl http://localhost:8000/api/status
```

Port 8000 бос емес болса, compose port mapping өзгерту керек.

### `жаңа жазбалар: 0`

Бұл normal жағдай. DB-де URL unique, duplicate title filter бар. Article step бұрын сақталған соңғы релевант оқиғалардан жасай алады.

### GUI ескі `_4`, `_6`, `_7` файлдарды көрсетсе

GUI тек `output/articles/YYYY-MM-DD/latest/*.md` оқу керек. `today_article_folder()` және `today_articles()` функцияларын тексер.

Daily preset міндетті түрде `article --replace-today` қолдануы керек.

### GDELT 429

GDELT rate limit normal. Код бір retry жасайды, кейін query өткізіледі. `fast` mode қолдансаң GDELT мүлде жүрмейді.

### LM Studio fallback-қа түсіп жатыр

Тексеру:

```bash
curl http://localhost:1234/v1/models
docker compose run --rm app python -c "import requests; print(requests.get('http://host.docker.internal:1234/v1/models', timeout=5).text)"
```

LM Studio ішінде Developer / Local Server іске қосылғанын, port 1234 екенін және `LMSTUDIO_MODEL` нақты model identifier екенін тексер.

### Ollama fallback-қа түсіп жатыр

Тексеру:

```bash
docker compose --profile ollama up -d ollama
docker compose --profile ollama --profile setup run --rm ollama-pull
docker compose --profile ollama exec ollama ollama list
```

Container ішіндегі app үшін URL default: `http://ollama:11434`.

One-click startup үшін қосымша тексер:

- `data/ollama_setup.log` ішінде `docker compose --profile ollama up -d ollama` және `ollama-pull` нәтижесін қара.
- `data/ollama_status.json` ішінде `state` мәнін қара: `starting`, `pulling`, `ready`, `error`.
- `/api/status` ішінде `ollama_loading=true` болса, image/model background-та жүктеліп жатыр.
- `ollama_status=Қате` болса, `ollama_status_message` және `data/ollama_setup.log` қара.
- Mac-та бірінші image/model pull ұзақ болуы қалыпты.

### Article сапасы generic болып кетті

Тексер:

- cluster summary weak емес пе?
- source/title нақты ма?
- `is_rejected_article_title()` aggregation/live тақырыпты өткізіп жіберіп тұрған жоқ па?
- `fallback_article()` ішінде техникалық сөздер жоқ па?
- AI output `is_quality_article()` арқылы құлап fallback-қа түскен жоқ па?

### Sport/crash/noise digest немесе article-ге өтті

Тексерілетін жерлер:

- `relevance.BLACKLIST_KEYWORDS`
- `relevance.has_blacklisted_topic()`
- `relevance.is_domestic_noise()`
- `article_writer.is_article_topic()`
- `article_writer.is_rejected_article_title()`

### DB schema ескі

`init_db()` әр command басында жүреді. Ол `migrate_db()` арқылы missing scoring columns қосады. Егер DB қатты бүлінсе, `data/news.sqlite3` backup жасап, fresh DB-мен smoke test жасауға болады.

## 23. Maintenance rules

- Full article text жүктейтін feature қоспа.
- Автопубликация қоспа; output әрдайым draft ретінде қалсын.
- Default Docker режимін жеңіл сақта: Ollama default-та download/start жасамауы керек.
- `app` service ішіне `depends_on: ollama` қайтарма.
- GUI-де Ollama үшін бөлек setup батырмасын қоспа; setup тек `start.sh` арқылы background-та жүруі керек.
- GUI service-ке Docker socket mount қоспа және `web.py` ішінен `docker compose` жүргізбе.
- Ollama дайын болмаса job күтпей fallback қолдансын.
- User-facing GUI daily flow бір батырмамен қалсын.
- `--replace-today` логикасы тек `latest/` папкасын тазаласын, бүкіл күндік папканы өшірмесін.
- Article selection digest selection-нан бөлек екенін ұмытпа; aggregation/live titles article-ге өтпеуі керек.
- AI provider қате болса exception сыртқа шықпасын.
- `AI_PROVIDER` preferred way, `USE_OLLAMA` compatibility ғана.
- `data/`, `output/`, `.env`, `__pycache__`, `.pyc` git-ке кірмеуі керек.
- Жаңа source қоспас бұрын RSS шынымен тұрақты екенін тексер.
- Scoring күрделенсе README_DEV-тегі формулаларды жаңарт.
- GUI endpoint немесе CLI args өзгерсе README.md және README_DEV.md қатар жаңарт.
- Smoke test-ті кемінде compileall + fast pipeline арқылы жүргіз.

## 24. Smoke test checklist

Өзгерістен кейін минималды тексеріс:

- [ ] `python3 -m compileall app`
- [ ] `docker compose config`
- [ ] `docker compose run --rm app python app/main.py all --mode fast`
- [ ] `docker compose run --rm app python app/main.py article --mode fast --limit 5`
- [ ] `docker compose --profile gui up -d --build gui`
- [ ] GUI-де "Бүгінгі 5 мақаланы жасау" тексерілді
- [ ] `output/articles/YYYY-MM-DD/latest` ішінде мақалалар бар
- [ ] README_DEV жаңартылды

Қосымша local latest check:

```bash
python app/main.py article --mode fast --limit 5 --replace-today
ls -la output/articles/$(date +%Y-%m-%d)/latest
```

## 25. Mental model

Бұл жүйені newsroom assistant ретінде ойла:

- Collector жаңалықтарды жинайды, бірақ толық мәтін оқымайды.
- Classifier rough relevance береді, бірақ редакторлық judgement емес.
- Clusterer бір оқиғаның бірнеше source-тағы нұсқасын біріктіреді.
- Digest редакторға күннің картасын береді.
- Article writer қысқа қазақша draft жасайды.
- AI provider тек writing assistant; факт көзі емес.
- Fallback template әрдайым жұмыс істеуі керек.
- GUI қарапайым user үшін daily workflow-ды таза ұстайды.

Соңғы publish-ready мәтін үшін адам міндетті түрде дереккөздерді ашып, фактіні қолмен тексеруі керек.

## 26. Audit notes — 2026-06-30

Бұл audit local GUI app security, bugs және жеңіл optimization бойынша жасалды. Үлкен feature/framework қосылған жоқ.

### Түзетілген issue-лер

- GUI exposure: `docker-compose.yml` бұрын GUI және Ollama порттарын host-та барлық interface-ке жариялауы мүмкін еді. Fix: порттар `127.0.0.1:8000:8000` және `127.0.0.1:11434:11434` болып шектелді. `app/web.py` local run default host-ы `127.0.0.1`, Docker GUI үшін `GUI_HOST=0.0.0.0` тек container ішінде қолданылады.
- POST payload robustness: `/api/run`, `/api/run-preset`, `/api/ai-provider` invalid немесе empty JSON кезінде default command-қа түсуі мүмкін еді. Fix: `application/json` емес, invalid JSON, invalid command, invalid mode, invalid limit, invalid ai_provider енді `400` қайтарады.
- Command allowlist: GUI command execution `collect/report/all/article` және `daily_articles` preset allowlist арқылы ғана қалады. `shell=True` қолданылмайды.
- CSRF/local hardening: POST request үшін local client және Origin/Referer check қосылды. GUI endpoint-терді сыртқы интернетке ашуға болмайды.
- AI truncation: LM Studio `finish_reason=length` болса және Ollama `done_reason/finish_reason=length` болса, AI мәтіні қабылданбайды, fallback қолданылады.
- Ollama model preflight: CLI және GUI `/api/tags` ішінен selected `OLLAMA_MODEL` барын тексереді; model missing болса fallback қолданылады және status/debug reason анық жазылады.
- Preview memory: `/api/status` preview үшін digest/article файлдарын толық оқымай, тек шағын preview бөлігі оқылады; article preview paragraph breaks сақтайды. `/api/digest` толық content сұралғанда ғана толық оқиды.

### Тексерілген қауіпсіздік нүктелері

- `subprocess.Popen` list args-пен қолданылады, `shell=True` жоқ.
- `open-folder` arbitrary path қабылдамайды; тек `output/articles/YYYY-MM-DD/latest/` ашады.
- GUI latest articles тек `output/articles/YYYY-MM-DD/latest/*.md` оқиды.
- Digest preview тек `output/digest_*.md` ішінен latest digest оқиды.
- `stop` current process-ке `terminate()` жібереді, 5 секундтан кейін `kill()` fallback бар. Sequential daily workflow кезінде non-zero returncode келсе келесі step басталмайды.
- `fast` mode GDELT-ті өшіреді; `normal` mode GDELT 429 кезінде бір retry жасап, қайталанса query өткізіледі.
- Docker default config тек `app` service көрсетеді; Ollama default-та image download/start жасамайды.
- `data/*.sqlite3`, `output/**/*.md`, `.env`, `__pycache__`, `.pyc` gitignore ішінде.

### Қалдық risk

- Ollama setup `start.sh` арқылы background-та жүреді. GUI Docker socket көрмейді және Docker command орындамайды.
- Local browser-дан `/api/digest` толық digest оқуға болады. Бұл expected behavior; arbitrary file read жоқ.

### Smoke test нәтижесі

- `python3 -m compileall app` — өтті.
- `docker compose config` — өтті; default-та тек `app` service, Ollama жоқ.
- `docker compose run --rm app python app/main.py all --mode fast` — өтті. RSS: 248, unique: 132, relevant: 31, new: 31, digest: `output/digest_2026-06-30.md`.
- `docker compose run --rm app python app/main.py article --mode fast --limit 5` — өтті. Таңдалған оқиғалар: 5, сақталған мақалалар: 5.
- `docker compose --profile gui up -d --build gui` — өтті.
- `curl http://localhost:8000/api/status` — өтті; AI status fields бар.
- Invalid JSON `/api/run` — `400`.
- Invalid command `/api/run` — `400`.

## 27. One-click local app update — 2026-06-30

User flow енді:

```text
start.command -> GUI ашылады -> Ollama background-та дайындалады
GUI "Бүгінгі 5 мақаланы жасау" -> all + article --replace-today
stop.command -> GUI және Ollama тоқтайды
```

Өзгерістер:

- `start.sh` Docker installed/running тексереді, `.env` жоқ болса `.env.example` көшіріп, GUI service-ті көтереді.
- `start.sh` Ollama service/model setup-ты detached background режимде бастайды.
- `data/ollama_setup.log` setup журналын сақтайды.
- `data/ollama_status.json` setup күйін сақтайды: `starting`, `pulling`, `ready`, `error`.
- `stop.sh` `docker compose --profile gui --profile ollama down` орындайды және ескі orphan `geo-news-ollama` container қалса, container-ді алып тастайды. Volume өшірілмейді.
- `web.py` Docker command жүргізбейді және Docker socket mount қолданбайды.
- GUI default AI режимі — `Ollama`; Ollama дайын болмаса subprocess `AI_PROVIDER=none` арқылы fallback template қолданады.
- `/api/status` `ai_provider`, `ollama_available`, `ollama_loading`, `ollama_status_message`, `latest_digest`, `latest_articles`, `job_status` қайтарады.
- Daily article output тек `output/articles/YYYY-MM-DD/latest/` ішіне жазылады; `--replace-today` әр run алдында `latest/` тазалайды.

One-click smoke:

- `python3 -m compileall app` — өтті.
- `docker compose config` — өтті.
- `./stop.sh` — өтті.
- `./start.sh` — өтті, GUI көтерілді.
- `curl http://localhost:8000/api/status` — өтті.
- Docker approval лимитіне байланысты соңғы `ollama-pull` run қайта орындалмады, бірақ `docker compose --profile gui --profile ollama --profile setup config` ішінде `ollama-pull` entrypoint дұрыс көрінді: `sh -c "sleep 10 && ollama pull $$OLLAMA_MODEL"`.
