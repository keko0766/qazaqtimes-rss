# geo-news-bot

Жергілікті браузер GUI арқылы геосаяси жаңалық жинап, дайджест және қазақша Markdown мақалалар жасайтын жеңіл app.

Жоба мақалалардың толық мәтінін интернеттен жүктемейді және автожариялау жасамайды. Тек сақталған metadata, summary және links қолданылады.

## Қарапайым іске қосу

### Mac

1. `start.command` файлын екі рет басыңыз.
2. Браузер автоматты ашылады.
3. **Бүгінгі 5 мақаланы жасау** батырмасын басыңыз.

Егер macOS рұқсат сұраса:

```bash
chmod +x start.command
```

### Terminal

```bash
chmod +x start.sh
./start.sh
```

Скрипт Docker барын, Docker Desktop қосулы екенін тексереді, `.env` жоқ болса `.env.example` ішінен жасайды, GUI контейнерін іске қосады және браузер ашады.

## GUI

Браузер адресі:

```text
http://localhost:8000
```

Негізгі батырма:

- **Бүгінгі 5 мақаланы жасау**: жаңалық жинайды, digest жасайды, 5 қазақша мақала шығарады.

Қосымша батырмалар:

- **Тек жаңалық жинау**
- **Дайджест жасау**
- **Мақала жасау**
- **Тоқтату**
- **Папканы ашу**

Кеңейтілген баптаулар:

- `fast`: тек RSS, жылдам режим.
- `normal`: RSS + GDELT.
- мақала саны: 1-10.
- ИИ provider: өшірулі, LM Studio, Ollama.

Нәтиже:

```text
output/articles/YYYY-MM-DD/latest/
output/digest_YYYY-MM-DD.md
data/news.sqlite3
```

GUI ішінде **Бүгінгі мақалалар** блогы тек `latest/` папкасындағы соңғы daily run нәтижесін көрсетеді. Әр карточкада **Көшіру** және **Толық көру** батырмалары бар.

## LM Studio

LM Studio қолдану үшін:

1. LM Studio ашыңыз.
2. Developer / Local Server бөлімінде серверді іске қосыңыз.
3. Port: `1234`.
4. GUI ішінде ИИ provider ретінде `LM Studio` таңдаңыз.

Әдепкі URL:

```text
http://host.docker.internal:1234/v1
```

Хосттан тексеру:

```bash
curl http://localhost:1234/v1/models
```

Егер LM Studio табылмаса, app құламайды: резерв шаблонмен мақала сақтайды және GUI-де қысқа ескерту көрсетеді.

## Ollama

Ollama default-та қосылмайды және image download жасамайды. Ол тек бөлек profile арқылы керек кезде іске қосылады:

```bash
docker compose --profile ollama up -d ollama
docker compose --profile ollama --profile setup run --rm ollama-pull
```

GUI ішінде ИИ provider ретінде `Ollama` таңдауға болады. Егер Ollama profile қосылмаған болса, app fallback қолданады.

## Әзірлеушілер үшін

CLI командалар сақталған:

```bash
docker compose run --rm app python app/main.py collect
docker compose run --rm app python app/main.py report
docker compose run --rm app python app/main.py article --mode fast --limit 5 --replace-today
docker compose run --rm app python app/main.py all --mode fast
```

LM Studio арқылы CLI:

```bash
docker compose run --rm \
  -e AI_PROVIDER=lmstudio \
  -e LMSTUDIO_MODEL=openai/gpt-oss-20b \
  app python app/main.py article --mode fast --limit 5 --replace-today
```

Тексеру:

```bash
python3 -m compileall app
docker compose config
docker compose --profile gui up -d --build gui
curl http://localhost:8000/api/status
```

GDELT `429 Too Many Requests` қайтарса, `fast` режимін қолданыңыз немесе кейінірек қайталап көріңіз.
