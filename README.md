# geo-news-bot

Local GUI app: геосаяси жаңалықтарды жинайды, дайджест жасайды және 5 қысқа қазақша Markdown мақала дайындайды.

Жоба толық мақала мәтінін жүктемейді және автожариялау жасамайды. Тек сақталған metadata, summary және links қолданылады.

## Қосу

Mac-та:

```text
start.command
```

Файлды екі рет басыңыз. Скрипт Docker барын тексереді, `.env` жоқ болса жасайды, GUI ашады және Ollama-ны background-та дайындайды.

Егер macOS рұқсат сұраса:

```bash
chmod +x start.command start.sh
```

GUI ашылады:

```text
http://localhost:8000
```

## Күнделікті жұмыс

1. `start.command` басыңыз.
2. Browser ашылған соң **Бүгінгі 5 мақаланы жасау** батырмасын басыңыз.
3. Bot жаңалық жинайды, digest жасайды және 5 қазақша мақала сақтайды.

Default:

- mode: `fast`
- мақала саны: `5`
- ИИ режимі: `Ollama`

Ollama бірінші рет ұзақ жүктелуі мүмкін. Ол background-та дайындалады. Егер ИИ әлі дайын болмаса, app резерв шаблонмен мақала жасайды; дайын болған соң келесі генерацияда Ollama автоматты қолданылады.

### Ollama модель таңдау

Default `qwen2.5:3b` жұмыс істейді, бірақ қазақша мәтін сапасы әлсіз болуы мүмкін — AI мақалалардың көпшілігі fallback шаблонға түсуі ықтимал.

Жақсырақ сапа:

- `qwen2.5:7b` — қазақша журналистикалық мәтін үшін ұсынылады
- `qwen2.5:14b` — жабдық рұқсат етсе, ең жақсы сапа

`.env` ішінде:

```env
OLLAMA_MODEL=qwen2.5:7b
```

## Тоқтату

Mac-та:

```text
stop.command
```

Немесе terminal:

```bash
./stop.sh
```

Бұл GUI және Ollama контейнерлерін тоқтатады.

## Нәтиже

```text
output/digest_YYYY-MM-DD.md
output/articles/YYYY-MM-DD/latest/
data/news.sqlite3
```

GUI тек `latest/` папкасындағы бүгінгі соңғы нәтижені көрсетеді. Әр daily run алдында `latest/` тазаланады.

## Ескерту

GUI local қолдануға арналған. Docker Compose порттарды `127.0.0.1` арқылы ашады; endpoint-терді сыртқы интернетке жарияламаңыз.

Ollama setup журналы:

```text
data/ollama_setup.log
data/ollama_status.json
```

GDELT `429 Too Many Requests` қайтарса, `fast` режимін қолданыңыз немесе кейінірек қайталап көріңіз.
