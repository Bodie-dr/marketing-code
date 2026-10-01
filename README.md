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
├── foto_generation/          # Qwen test-app: stijl leren + foto bewerken
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
| Qwen foto-app starten | `python foto_generation/qwen_app.py` (http://127.0.0.1:7861) |
| Tests Qwen-app | `cd foto_generation; python -m unittest test_qwen_backend -v` |
| Kleurpalet uit foto's | `python foto_generation/kleurpalet.py <map> --png palet.png` |
| Captions voor LoRA-training | `python foto_generation/maak_captions.py <map> --trigger tvbstijl` |
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

### Qwen foto-app

Tabblad **Stijl leren**: upload referentiefoto's, Qwen3-VL beschrijft de
gemeenschappelijke stijl (kleuren, licht, compositie, sfeer, nabewerking) en
slaat die op in `outputs/qwen/stijlen/`. Tabblad **Foto bewerken**: pas een foto
aan met een instructie en/of een opgeslagen stijl; resultaten komen in
`outputs/qwen/bewerkt/`.

`QWEN_BACKEND` in `.env`: `auto` (lokaal als er een CUDA-GPU is, anders cloud),
`lokaal` (het gedownloade Qwen-Image-2.1, ±31 GB, NVIDIA-GPU nodig) of `cloud`
(Hugging Face Inference Providers; `HF_TOKEN` moet de permissie
*Make calls to Inference Providers* hebben).
