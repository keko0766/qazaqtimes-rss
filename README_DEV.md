# geo-news-bot developer notes

## Daily GUI workflow

GUI-дегі **Бүгінгі 5 мақаланы жасау** батырмасы `/api/run-preset` endpoint-ін шақырады:

```json
{
  "preset": "daily_articles",
  "mode": "fast",
  "limit": 5,
  "ai_provider": "none"
}
```

Ішкі орындау реті:

```bash
python app/main.py all --mode fast
python app/main.py article --mode fast --limit 5 --replace-today
```

`--replace-today` режимі `output/articles/YYYY-MM-DD/latest/` папкасын тазалап, сол жерге жаңа daily run нәтижесін жазады. Күндік папканың түбіріндегі ескі файлдар өшірілмейді, бірақ GUI оларды көрсетпейді.

## Article filtering

Article generation digest-тен бөлек сүзгіден өтеді. Мақалаға мынадай әлсіз aggregation/live форматтар алынбайды:

- `World News in Brief`
- `News in Brief`
- `as it happened`
- `live updates`
- `liveblog`
- `briefing`
- `roundup`
- `opinion`
- `analysis video`
- `video only`

Topic diversity article selection ішінде сақталады:

- USA/Iran: максимум 2
- Middle East: максимум 2
- Russia/Ukraine: максимум 2
- NATO/EU: максимум 2
- China/Taiwan: максимум 1

## GUI status summary

GUI `/api/status` журналдан summary metrics шығарады:

- Жиналған RSS жазбалар
- Бірегей жаңалықтар
- Жаңа жазбалар
- Мақалаға таңдалған оқиғалар
- Сақталған мақалалар

Егер жаңа жазба `0` болса, GUI user-ге мақалалар бұрын сақталған соңғы релевант оқиғалардан жасалғанын түсіндіреді.
