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
| Weekoverzicht | `python calander_automatisering/calander.py week --weken 2` |
| Planning als Excel | `python calander_automatisering/calander.py excel` |
| Agenda voor Outlook (.ics) | `python calander_automatisering/calander.py ics` |
| Concepten volgende week | `python calander_automatisering/calander.py concepten` |
| Concepten één bedrijf/week | `python calander_automatisering/calander.py concepten --vanaf 2026-10-05 --bedrijf TVB` |
| Filter per bedrijf | `--bedrijf TTI` (naam of werkblad) werkt bij `week`, `ics`, `concepten` en de lijst |
| Tests jaarplanning | `cd calander_automatisering; python -m unittest test_excel_normalizer test_planning_posts test_weekplanning_concepten -v` |

Concepten komen in `outputs/concepten/<jaar>-week-<nr>/<bedrijf>/`. Bestaande
concepten worden overgeslagen (scheelt API-kosten); gebruik `--opnieuw` om ze
te overschrijven. Hetzelfde kan in de app via het tabblad **Weekplanning**.

`calander.py` toont één regel per post (datum, bedrijf, kanaal, onderwerp,
soort content) en slaat die ook op als CSV in `outputs/kalender/`.

Het pad naar de jaarplanning stel je in met `CALENDAR_EXCEL_FILE` in `.env`
(bijvoorbeeld de versie op OneDrive). Leeg = de kopie in `calander_automatisering/`.

`ingest_documents.py` leest standaard de map uit `DOCUMENTS_FOLDER` in `.env`;
elke submap wordt een bedrijf in de dropdown van de app.
