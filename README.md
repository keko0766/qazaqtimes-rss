# geo-news-bot

Геосаяси дайджест жасауға арналған жеңіл Docker MVP:

RSS/GDELT -> SQLite -> дубльдерді алып тастау -> классификация/сүзгі -> оқиға кластері -> Markdown дайджест -> қосымша Ollama жазушысы -> резерв шаблон.

Жоба тек метадеректерді сақтайды: `title`, `url`, `source`, `published_at`, `summary`, `tags` және қарапайым бағалау өрістері. Мақалалардың толық мәтіні жүктелмейді, автожариялау жоқ.

## Жылдам бастау

Әдепкі режим тек `app` сервисін іске қосады және Ollama image жүктемейді:

```bash
docker compose run --rm app python app/main.py all --mode fast
```

Іске қосылғаннан кейін:

- SQLite: `data/news.sqlite3`
- Дайджест: `output/digest_YYYY-MM-DD.md`

## Командалар

```bash
docker compose run --rm app python app/main.py collect
docker compose run --rm app python app/main.py report
docker compose run --rm app python app/main.py article --mode fast
docker compose run --rm app python app/main.py all
```

- `collect`: RSS/GDELT жинайды, дубль жазбаларды алып тастайды, классификация жасап, жазбаларды сақтайды.
- `report`: сақталған жазбалардан Markdown дайджест құрастырады.
- `article`: ең жоғары бағаланған оқиға кластерінен қысқа қазақша мақала жасап, `output/articles/` ішіне сақтайды.
- `all`: екі қадамды қатар орындайды.

## Қазақша мақала жасау

CLI арқылы:

```bash
docker compose run --rm app python app/main.py article --mode fast
```

GUI арқылы:

```text
http://localhost:8000 -> Қазақша мақала жазу
```

Ollama қосылса, мақала Ollama арқылы жазылады. Ollama жоқ болса, бот қысқа қазақша резерв шаблон жасап, бәрібір `.md` файл сақтайды.

## Режимдер

```bash
docker compose run --rm app python app/main.py all --mode fast
docker compose run --rm app python app/main.py all --mode normal
```

- `fast`: тек RSS, әдепкі режим.
- `normal`: RSS + GDELT.

## GUI

Шағын жергілікті GUI қосымша профиль арқылы іске қосылады:

```bash
docker compose --profile gui up gui
```

Браузерден `http://localhost:8000` ашыңыз. GUI арқылы `collect`, `report` немесе `all` іске қосуға, қысқа қазақша мақала жазуға, `fast`/`normal` таңдауға, журналды көруге, соңғы дайджесті оқуға және жүріп тұрған тапсырманы тоқтатуға болады. GUI Ollama-ны өзі іске қоспайды; ол үшін Ollama профилі бөлек қолданылады.

## Дереккөздер

Белсенді RSS дереккөздері `sources.json` ішінде: White House, Defense.gov, UN News, Kremlin, BBC World, Al Jazeera, The Guardian World, Deutsche Welle, France 24 және GDELT баптауы.

Өшірілген кандидаттар `sources.disabled.json` ішіне шығарылған, сондықтан негізгі тізім қысқа болып қалады.

## Қосымша Ollama

Ollama әдепкі бойынша өшірулі:

```env
USE_OLLAMA=false
OLLAMA_URL=http://ollama:11434
OLLAMA_MODEL=qwen2.5:3b
OLLAMA_TIMEOUT=180
```

Ollama контейнерін іске қосу:

```bash
docker compose --profile ollama up -d ollama
```

Модель жүктеу:

```bash
docker compose --profile ollama --profile setup run --rm ollama-pull
```

Ollama арқылы есеп жасау:

```bash
docker compose --profile ollama run --rm -e USE_OLLAMA=true app python app/main.py report --mode fast
```

Ollama қолжетімсіз болса, қосымша бір ескерту шығарып, резерв шаблондарды қолданады. Модель Docker volume `ollama_data` ішінде сақталады; алғашқы жүктеу үлкен болуы мүмкін, әсіресе Mac-та.

`docker-compose.gpu.yml` тек болашақ NVIDIA бар ПК үшін қалдырылған. NVIDIA driver және NVIDIA Container Toolkit керек:

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml --profile ollama up -d ollama
```

## GDELT 429

Егер GDELT `429 Too Many Requests` қайтарса, жинаушы `retry_delay_seconds` күтіп, бір рет қайталайды. Қайтадан 429 болса, сол сұрау өткізіледі. RSS жинау және есеп жасау жалғаса береді.

Не істеуге болады:

- кейінірек іске қосу;
- `gdelt.queries` санын азайту;
- `gdelt.maxrecords` азайту;
- `gdelt.delay_seconds` ұлғайту;
- `--mode fast` қолдану.

## Қолмен тексеру

Мақала жобасы дайын жарияланым емес. Жариялау алдында `output/digest_YYYY-MM-DD.md` файлын ашып, сілтемелерді, даталарды, есімдерді, сандарды және тұжырымдарды тексеріңіз. Өз талдауыңызды тек факт қолмен тексерілгеннен кейін қосыңыз.
