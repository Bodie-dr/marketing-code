# Marketing AI (TVB)

## Mappenstructuur

```
marketing code/
├── .env                      # jouw sleutels (niet in git) — zie .env.example
├── requirements.txt          # alle dependencies
├── text_generator/           # Gradio-app voor marketingteksten + kennisbank
│   ├── app.py                # start de app
│   ├── ingest_documents.py   # documenten inlezen in de database
│   ├── marketing.sqlite3     # kennisbank (lokaal, niet in git)
│   └── test_performance.py   # tests
├── foto_generation/          # upscalen via Claid.ai en Pixelcut
├── calander_automatisering/  # social-media jaarplanning uit Excel
├── documents/                # trainingsdocumenten, één submap per bedrijf
└── outputs/                  # gegenereerde bestanden (niet in git)
    ├── word/
    ├── claid/
    └── pixelcut/
```

## Installatie

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env   # en vul de sleutels in
```

## Gebruik

| Wat | Commando |
|---|---|
| Tekstgenerator starten | `python text_generator/app.py` |
| Documenten inlezen | `python text_generator/ingest_documents.py` |
| Tests | `cd text_generator; python -m unittest test_performance -v` |
| Claid upscale-test | `python foto_generation/test_claid.py` |
| Pixelcut upscale-test | `python foto_generation/test_pixelcut.py` |
| Jaarplanning inlezen | `python calander_automatisering/calander.py` |

`ingest_documents.py` leest standaard de map uit `DOCUMENTS_FOLDER` in `.env`;
elke submap wordt een bedrijf in de dropdown van de app.
