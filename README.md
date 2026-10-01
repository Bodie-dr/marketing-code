# Marketing AI (TVB)

## Mappenstructuur

```
marketing code/
├── .env                      # jouw sleutels (niet in git) — zie .env.example
├── requirements.txt          # alle dependencies
├── Procfile                  # startcommando voor Railway
├── tekstgenerator/           # Gradio-app: marketingteksten + tabblad Weekplanning
│   ├── app.py                # start de app
│   ├── text_generation.py    # prompt + Azure OpenAI
│   ├── web_reader.py         # tekst van een webpagina ophalen
│   ├── assets/               # afbeelding bovenaan het Word-document
│   └── tests/
├── kennisbank/               # documenten inlezen en doorzoekbaar maken
│   ├── ingest_documents.py   # documenten inlezen in de database
│   ├── config.py             # paden en instellingen (.env)
│   └── database.py, chunking.py, embedding_service.py, ...
├── kalender/                 # social-media jaarplanning uit Excel
│   ├── kalender.py           # startpunt (week, excel, ics, concepten)
│   └── tests/
├── fotogeneratie/            # Qwen foto-app: stijl leren + foto bewerken
│   ├── lora/                 # product-LoRA trainen (handleiding: lora/README.md)
│   ├── pas_lut_toe.py        # vaste kleurstijl (.cube-LUT) toepassen
│   ├── voeg_logo_toe.py      # TVB-logo op beelden zetten
│   ├── assets/               # TVB-logo
│   └── tests/
├── data/
│   ├── documents/            # trainingsdocumenten, één submap per bedrijf
│   ├── jaarplanning/         # kopie van de jaarplanning-Excel
│   └── marketing.sqlite3     # kennisbank (lokaal, niet in git)
├── outputs/                  # gegenereerde bestanden (niet in git)
└── _archief/                 # oude code en databases (lokaal, niet in git)
```

## Installatie

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env   # en vul de sleutels in
```

## Gebruik

Alle commando's start je vanuit de projectmap.

| Wat | Commando |
|---|---|
| Tekstgenerator starten | `python tekstgenerator/app.py` (http://127.0.0.1:7860) |
| Documenten inlezen | `python kennisbank/ingest_documents.py` |
| Qwen foto-app starten | `python fotogeneratie/qwen_app.py` (http://127.0.0.1:7861) |
| Kleurpalet uit foto's | `python fotogeneratie/kleurpalet.py <map> --png palet.png` |
| Captions voor LoRA-training | `python fotogeneratie/maak_captions.py <map> --trigger tvbstijl` |
| Product-LoRA (stap 1–8) | zie [fotogeneratie/lora/README.md](fotogeneratie/lora/README.md) |
| Huisstijl-LUT toepassen | `python fotogeneratie/pas_lut_toe.py <map> --lut tvb_stijl.cube` |
| TVB-logo op beelden | `python fotogeneratie/voeg_logo_toe.py <map>` |
| Jaarplanning inlezen | `python kalender/kalender.py` |
| Weekoverzicht | `python kalender/kalender.py week --weken 2` |
| Planning als Excel | `python kalender/kalender.py excel` |
| Agenda voor Outlook (.ics) | `python kalender/kalender.py ics` |
| Concepten volgende week | `python kalender/kalender.py concepten` |
| Concepten één bedrijf/week | `python kalender/kalender.py concepten --vanaf 2026-10-05 --bedrijf TVB` |
| Filter per bedrijf | `--bedrijf TTI` (naam of werkblad) werkt bij `week`, `ics`, `concepten` en de lijst |

### Tests

```powershell
python -m unittest discover -s tekstgenerator/tests -t tekstgenerator -v
python -m unittest discover -s kalender/tests -t kalender -v
python -m unittest discover -s fotogeneratie/tests -t fotogeneratie -v
```

### Tekstgenerator

De app draait standaard alleen op je eigen computer. Een publieke
gradio.live-link maak je met `APP_SHARE=1` in `.env`; dan zijn `APP_USERNAME`
en `APP_PASSWORD` verplicht, anders start de app niet.

`ingest_documents.py` leest standaard de map uit `DOCUMENTS_FOLDER` in `.env`
(leeg = `data/documents/`); elke submap wordt een bedrijf in de dropdown van de
app. De database staat in `data/marketing.sqlite3` (aan te passen met
`DATABASE_PATH`).

### Kalender

Concepten komen in `outputs/concepten/<jaar>-week-<nr>/<bedrijf>/`. Bestaande
concepten worden overgeslagen (scheelt API-kosten); gebruik `--opnieuw` om ze
te overschrijven. Hetzelfde kan in de app via het tabblad **Weekplanning**.

`kalender.py` toont één regel per post (datum, bedrijf, kanaal, onderwerp,
soort content) en slaat die ook op als CSV in `outputs/kalender/`.

Het pad naar de jaarplanning stel je in met `CALENDAR_EXCEL_FILE` in `.env`
(bijvoorbeeld de versie op OneDrive). Leeg = de kopie in `data/jaarplanning/`.

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

## Railway deployment

Railway start de app met de `Procfile` in de projectmap en zet zelf `PORT`.
Laat de *Root Directory* in de service-instellingen leeg. Zet in Railway:
`AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_DEPLOYMENT`,
`AZURE_OPENAI_API_VERSION`, `APP_USERNAME` en `APP_PASSWORD`.

De database staat niet in git. Railway's schijf is tijdelijk; gebruik een
Railway Volume en zet `DATABASE_PATH` naar een pad op dat volume.
