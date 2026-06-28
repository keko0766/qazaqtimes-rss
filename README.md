# geo-news-bot

Локальный Docker-проект для бесплатного сбора геополитических новостей из RSS и GDELT Doc API. Система сохраняет только метаданные, убирает дубли, классифицирует новости простыми правилами, группирует похожие события и создаёт Markdown-дайджест с черновиками статей на русском языке.

Это MVP: он не публикует материалы автоматически, не использует платные API и не копирует полный текст чужих статей.

## Быстрый запуск

Запустите сбор и генерацию отчёта одной командой:

```bash
docker compose up --build
```

Или выполните разовый запуск:

```bash
docker compose run --rm app python app/main.py all
```

После запуска база будет в `data/news.sqlite3`, а отчёт появится в `output/digest_YYYY-MM-DD.md`.

Файл `.env` не обязателен: у приложения есть настройки по умолчанию. Если хотите поменять пути, таймауты или лимиты, скопируйте `.env.example` в `.env` и измените значения.

## Команды

```bash
docker compose run --rm app python app/main.py collect
docker compose run --rm app python app/main.py report
docker compose run --rm app python app/main.py all
```

- `collect` создаёт базу при необходимости, собирает новости и сохраняет новые записи.
- `report` создаёт Markdown-дайджест из уже сохранённых новостей.
- `all` делает оба шага подряд.

## Run modes

Для экономии времени можно выбрать режим запуска:

```bash
docker compose run --rm app python app/main.py all --mode fast
docker compose run --rm app python app/main.py all --mode normal
docker compose run --rm app python app/main.py all --mode deep
```

- `fast`: только RSS, без GDELT.
- `normal`: RSS + GDELT, `maxrecords=20`, `delay_seconds=15`.
- `deep`: RSS + GDELT, `maxrecords=50`, `delay_seconds=30`.

Если `--mode` не указан, используется `normal`.

## Как добавить RSS-источник

Откройте `sources.json` и добавьте объект в массив `rss_sources`:

```json
{
  "name": "Example Source",
  "url": "https://example.com/rss.xml"
}
```

Если источник временно недоступен или отдаёт неправильный RSS, программа напечатает предупреждение и продолжит работу с остальными источниками.

## Источники

В `sources.json` уже добавлены бесплатные источники: GDELT, U.S. Department of State, White House, Defense.gov, NATO, UN News, IAEA, President of Ukraine, Ukraine MFA, Kremlin, Russia MFA, China MFA, European Council, BBC World, Al Jazeera, The Guardian World, Deutsche Welle и France 24.

Некоторые официальные ведомства периодически меняют адреса RSS, отключают ленты или блокируют автоматические запросы. Такие записи оставлены в `sources.json` с `"enabled": false` и пояснением в поле `note`. В частности, China MFA часто не предоставляет стабильную RSS-ленту на английском сайте; её лучше добавить вручную позже, если появится официальный RSS.

## Что сохраняется

Система сохраняет только:

- `title`
- `url`
- `source`
- `published_at`
- `summary`
- `tags`

Полные тексты чужих статей не скачиваются и не копируются. Краткие описания берутся из RSS/API, если источник сам их отдаёт.

## Где смотреть результат

Откройте файл:

```bash
output/digest_YYYY-MM-DD.md
```

Внутри будут:

- главное;
- главные события, сгруппированные по event clusters;
- новости по направлениям;
- 1–3 черновика статей на русском языке;
- ссылки на источники.

## Как работает фильтрация

После сбора каждая новость проходит несколько простых проверок без ИИ:

- классификация по ключевым словам добавляет теги вроде `usa`, `iran`, `russia`, `ukraine`, `china`, `nato`, `eu`, `middle_east`, `taiwan`, `nuclear`, `sanctions`, `war`, `diplomacy`, `military`;
- нерелевантные и `untagged` новости не попадают в дайджест;
- blacklist исключает темы вроде sport, celebrity, entertainment, weather, crash, plane crash, wildfire, crime, accident, music, film, football и tennis;
- blacklist не применяется, если материал явно связан с войной, санкциями, правительством, военными действиями или дипломатией;
- итоговый `final_score` учитывает keyword importance, качество источника и геополитическую релевантность;
- `core_topic_score` отделяет ядро дайджеста от второстепенных международных новостей;
- core topics: `usa_iran`, `russia_ukraine`, `china_taiwan`, `nato_ukraine`, `middle_east_security`, `iran_nuclear`, `sanctions`, `war_escalation`;
- `China / Taiwan` требует не просто упоминания Китая, а связи с Тайванем, безопасностью, санкциями, обороной, технологиями, торговым конфликтом или export controls;
- обычные USA-only сюжеты не попадают в `USA / Iran`, если они не связаны с Ираном, санкциями, войной, дипломатией или ключевой геополитикой;
- похожие новости группируются в один event cluster через нормализацию заголовка, stopwords, общие смысловые ключи и `difflib.SequenceMatcher`.

Это не идеальная редакторская оценка, а прозрачные правила MVP, которые легко менять в `app/services/classifier.py`, `app/services/relevance.py` и `app/services/event_clusterer.py`.

## Почему GDELT ограничен белым списком

GDELT индексирует очень много сайтов, включая слабые, повторяющиеся и нерелевантные источники. Чтобы дайджест не превращался в шум, GDELT-новости сохраняются только с доменов из `ALLOWED_GDELT_DOMAINS` в `app/services/source_quality.py`.

В белом списке оставлены Reuters, AP, BBC, France 24, DW, Al Jazeera, The Guardian, UN, NATO, IAEA и официальные государственные сайты. Если нужен новый домен, добавьте его в `ALLOWED_GDELT_DOMAINS` и перезапустите сбор.

## GDELT 429 Too Many Requests

Если GDELT возвращает `429 Too Many Requests`, это значит, что API ограничил частоту запросов.

Решения:

- уменьшить количество `queries` в блоке `gdelt` файла `sources.json`;
- уменьшить `maxrecords`;
- увеличить `delay_seconds`;
- запустить сбор позже;
- временно отключить GDELT через `gdelt.enabled=false`.

По умолчанию GDELT настроен осторожно:

```json
{
  "maxrecords": 20,
  "delay_seconds": 15,
  "retry_delay_seconds": 60,
  "timeout_seconds": 20
}
```

При `429` collector ждёт `retry_delay_seconds`, делает один повтор и, если API снова ограничивает запрос, пропускает этот query. RSS-сбор и генерация digest продолжаются.

## Почему это не автопубликация

Проект только собирает метаданные, создаёт дайджест и черновики. Он не отправляет материалы на сайт, в CMS, Telegram или соцсети.

Система не копирует полный текст чужих статей. В базе сохраняются только `title`, `url`, `source`, `published_at`, `summary`, `tags`, `importance`, `source_score`, `relevance_score` и `final_score`.

## Как проверить черновик перед публикацией

Перед публикацией на сайте:

1. Откройте свежий файл `output/digest_YYYY-MM-DD.md`.
2. Перейдите по ссылкам в блоке `Источники`.
3. Проверьте дату, формулировки, имена, цифры и контекст.
4. Уберите спорные или неподтверждённые утверждения.
5. Перепишите черновик в редакторском стиле вашего сайта.
6. Добавьте собственный анализ только после ручной проверки фактов.

Черновики стоит считать заготовками, а не готовыми публикациями.

## Optional Ollama writer

По умолчанию черновики создаются без LLM: только шаблоны, event clusters и сохранённые метаданные. Можно включить локальный Ollama writer:

```bash
ollama pull qwen2.5:7b
```

В `.env`:

```env
USE_OLLAMA=true
OLLAMA_URL=http://host.docker.internal:11434
OLLAMA_MODEL=qwen2.5:7b
OLLAMA_TIMEOUT=120
```

Запуск:

```bash
docker compose run --rm app python app/main.py all --mode normal
```

Если Ollama недоступен, программа не падает и автоматически использует fallback-шаблоны.

Важно оставить правило: не передавать и не генерировать полный копипаст чужих статей, использовать только заголовки, summaries и ссылки.
