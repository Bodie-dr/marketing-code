import logging
import tempfile
import os
import sys
from pathlib import Path
from threading import Lock, Thread


APP_DIR = Path(__file__).resolve().parent
PROJECT_DIR = APP_DIR.parent
CALENDAR_DIR = PROJECT_DIR / "calander_automatisering"

# Eigen map vooraan, zodat `database`, `config` enz. altijd uit text_generator
# komen, ook als de app vanuit de projectmap wordt gestart. De kalendermap
# achteraan voor het tabblad Weekplanning.
if str(APP_DIR) in sys.path:
    sys.path.remove(str(APP_DIR))
sys.path.insert(0, str(APP_DIR))
if str(CALENDAR_DIR) not in sys.path:
    sys.path.append(str(CALENDAR_DIR))

import gradio as gr
from gradio.themes import Base, LocalFont
from docx import Document
from docx.shared import Inches
from database import create_connection, create_schema
from config import DOCUMENTS_FOLDER
from document_repository import get_or_create_project, get_project_names

from text_generation import generate_text


_database_ready = False
_database_lock = Lock()


def initialize_database() -> None:
    global _database_ready
    with _database_lock:
        if _database_ready:
            return
        connection = create_connection()
        try:
            create_schema(connection)
            _database_ready = True
        finally:
            connection.close()


logger = logging.getLogger(__name__)


def warm_up_embedding_model() -> None:
    """Laad het embeddingmodel (±13 s) op de achtergrond, niet bij de eerste klik."""
    try:
        from embedding_service import EmbeddingService

        EmbeddingService()
    except Exception:
        logger.exception("Embeddingmodel kon niet vooraf worden geladen.")


def laad_bedrijven():
    connection = None

    try:
        initialize_database()
        connection = create_connection()
        bedrijven = get_project_names(connection)
        if not bedrijven and DOCUMENTS_FOLDER.is_dir():
            for bedrijfsmap in sorted(DOCUMENTS_FOLDER.iterdir()):
                if bedrijfsmap.is_dir():
                    get_or_create_project(connection, bedrijfsmap.name)
            connection.commit()
            bedrijven = get_project_names(connection)
    except Exception:
        logger.exception("Bedrijven konden niet uit de database worden geladen.")
        bedrijven = []
    finally:
        if connection is not None:
            connection.close()

    return gr.Dropdown(
        choices=bedrijven,
        value=bedrijven[0] if bedrijven else None,
    )


def save_generated_word(text):
    if not text or not text.strip():
        return None

    output_dir = Path(__file__).resolve().parent.parent / "outputs" / "word"
    output_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile(
        suffix=".docx",
        dir=output_dir,
        delete=False,
    ) as bestand:
        bestand_path = Path(bestand.name)

    document = Document()
    image_path = Path(__file__).resolve().parent / "image.jpg"
    if not image_path.exists():
        image_path = Path(__file__).resolve().parent / "images.jpg"
    if image_path.exists():
        document.add_picture(str(image_path), width=Inches(6.5))

    for regel in text.strip().splitlines():
        document.add_paragraph(regel)
    document.save(str(bestand_path))
    return str(bestand_path)

def _planning_posts():
    """Lees de jaarplanning opnieuw in, zodat wijzigingen in Excel direct zichtbaar zijn."""
    from planning_posts import lees_posts, standaard_excel_bestand

    posts, _ = lees_posts(standaard_excel_bestand())
    return posts


def _posts_in_week(maandag_iso, bedrijf=None):
    from datetime import date

    from weekplanning import filter_bedrijf, posts_in_periode

    if not maandag_iso:
        return []
    posts = filter_bedrijf(_planning_posts(), bedrijf)
    return posts_in_periode(posts, date.fromisoformat(maandag_iso), 1)


def laad_planning_keuzes(huidig_bedrijf=None):
    """Vul de keuzelijsten voor week en bedrijf; een gekozen bedrijf blijft staan."""
    try:
        posts = _planning_posts()
        from weekplanning import (
            ALLE_BEDRIJVEN,
            bedrijven_in_planning,
            standaard_week,
            weken_in_planning,
        )
    except Exception:
        logger.exception("Jaarplanning kon niet worden geladen.")
        gr.Warning("De jaarplanning kon niet worden geladen. Controleer CALENDAR_EXCEL_FILE in .env.")
        return gr.Dropdown(choices=[], value=None), gr.Dropdown(choices=[], value=None)

    bedrijven = [ALLE_BEDRIJVEN, *bedrijven_in_planning(posts)]
    bedrijf = huidig_bedrijf if huidig_bedrijf in bedrijven else ALLE_BEDRIJVEN
    return (
        gr.Dropdown(choices=weken_in_planning(posts), value=standaard_week(posts)),
        gr.Dropdown(choices=bedrijven, value=bedrijf),
    )


def toon_planning_week(maandag_iso, bedrijf=None):
    from weekplanning import posts_tabel

    return posts_tabel(_posts_in_week(maandag_iso, bedrijf))


def maak_planning_concepten(maandag_iso, bedrijf, opnieuw, progress=gr.Progress()):
    from concepten import maak_concepten

    posts = _posts_in_week(maandag_iso, bedrijf)
    if not posts:
        raise gr.Error("Er zijn geen posts gepland in deze week voor deze selectie.")

    resultaten = maak_concepten(
        posts,
        opnieuw=bool(opnieuw),
        voortgang=lambda nummer, totaal, post: progress(
            (nummer - 1) / totaal,
            desc=f"{nummer}/{totaal}: {post.bedrijf} – {post.kanaal}",
        ),
    )

    aantallen = {
        status: sum(resultaat.status == status for resultaat in resultaten)
        for status in ["gemaakt", "bestond al", "mislukt"]
    }
    status = (
        f"{aantallen['gemaakt']} gemaakt, {aantallen['bestond al']} bestonden al, "
        f"{aantallen['mislukt']} mislukt. Map: {resultaten[0].pad.parent.parent}"
    )
    bestanden = [str(resultaat.pad) for resultaat in resultaten if resultaat.pad.exists()]
    return bestanden, status


def download_planning_excel(bedrijf=None):
    from excel_export import schrijf_excel
    from weekplanning import ALLE_BEDRIJVEN, filter_bedrijf

    posts = filter_bedrijf(_planning_posts(), bedrijf)
    if not posts:
        raise gr.Error("Er zijn geen posts voor deze selectie.")

    naam = "social_media_planning"
    if bedrijf and bedrijf != ALLE_BEDRIJVEN:
        naam += f" - {posts[0].bedrijf}"
    return str(schrijf_excel(posts, PROJECT_DIR / "outputs" / "kalender" / f"{naam}.xlsx"))


def update_modus_from_text(style_text, handmatig_gekozen=False):
    """
    Selecteer automatisch 'Tekst herschrijven' wanneer de gebruiker
    eigen tekst invoert. Als het veld leeg is, selecteer 'Nieuwe tekst genereren'.
    Heeft de gebruiker zelf een functie gekozen, dan blijft die keuze staan.
    """
    if handmatig_gekozen:
        return gr.update()

    if style_text and style_text.strip():
        return "Tekst herschrijven"

    return "Nieuwe tekst genereren"

def validate_and_generate(
    document,
    style_text,
    prompt,
    modus,
    aanleiding,
    insteek,
    doelgroep,
    bedrijf,
    kanaal,
):
    opdracht = "\n".join(
        waarde
        for waarde in [aanleiding, insteek, doelgroep, bedrijf]
        if waarde and waarde.strip()
    )

    if modus == "Tekst herschrijven" and not (document or style_text):
        raise gr.Error(
            "Upload of plak de oorspronkelijke tekst die je wilt herschrijven."
        )

    if modus != "Tekst herschrijven" and not opdracht:
        raise gr.Error(
            "Vul minimaal de aanleiding, insteek, doelgroep of het bedrijf in."
        )

    try:
        resultaat = generate_text(
            opdracht.strip(),
            document=document,
            style_text=style_text or "",
            prompt=prompt or "",
            modus=modus or "Nieuwe tekst genereren",
            aanleiding=aanleiding or "",
            insteek=insteek or "",
            doelgroep=doelgroep or "",
            bedrijf=bedrijf or "",
            kanaal=kanaal or "LinkedIn",
        )
    
    except Exception as error:
        raise gr.Error(
            "De factuurtekst kon niet worden gegenereerd. "
            "Controleer je API-configuratie en probeer opnieuw."
        ) from error

    # Toon de tekst direct; Word-export mag de weergave niet ophouden.
    yield resultaat, None
    try:
        bestand = save_generated_word(resultaat)
    except Exception:
        logger.exception("Word-document kon niet worden opgeslagen.")
        gr.Warning("De tekst is klaar, maar het Word-document kon niet worden gemaakt.")
        return
    yield resultaat, bestand


APP_THEME = Base(
    primary_hue="cyan",
    secondary_hue="blue",
    # Gradio kent alleen slate, gray, zinc, neutral en stone ("white" crasht).
    neutral_hue="slate",
    # Standaard laadt Gradio alleen 400 en 600. Zonder 700 maakt de browser
    # vette koppen zelf na, waardoor letters als de "a" vervormd raken.
    font=[
        LocalFont("IBM Plex Sans", weights=(400, 600, 700)),
        "ui-sans-serif",
        "system-ui",
        "sans-serif",
    ],
)

APP_CSS = """
:root {
    --tvb-blue: #222D4F;
    --tvb-blue-dark: #1A2340;
    --tvb-green: #38B5A8;
    --tvb-green-dark: #2D9A8E;
    --tvb-light: #F5F7FA;
    --tvb-secondary: #B8C4D2;
    --tvb-white: #FFFFFF;
}
/* Veldnamen staan op witte kaarten, dus donker maken */
.gradio-container label,
.gradio-container label span,
.gradio-container .label-wrap,
.gradio-container .info,
.gradio-container p {
    color: #222D4F !important;
}

/* Markdown tekst op de donkerblauwe achtergrond */
.gradio-container .prose,
.gradio-container .prose p {
    color: #FFFFFF !important;
}

/* Tekst IN invoervelden juist donker houden */
.gradio-container input,
.gradio-container textarea,
.gradio-container select {
    color: #222D4F !important;
}

/* Placeholder in invoervelden */
.gradio-container input::placeholder,
.gradio-container textarea::placeholder {
    color: #6B7280 !important;
}

.gradio-container {
    background: linear-gradient(
        135deg,
        #222D4F 0%,
        #2A3763 35%,
        #F5F7FA 100%
    ) !important;
}

h1 {
    color: var(--tvb-blue) !important;
    font-size: 3.5rem !important;
    font-weight: 700 !important;
    text-align: center !important;
    border-bottom: 4px solid var(--tvb-green);
    padding-bottom: 10px;
    margin-bottom: 20px;
}

h2,h3,h4,h5,h6 {
    color: var(--tvb-blue) !important;
}

/* Kaarten */
.panel,
.gr-group,
.gr-box {
    background: white !important;
    border: 2px solid var(--tvb-secondary) !important;
    border-radius: 18px !important;
    box-shadow: 0 8px 25px rgba(34,45,79,0.15) !important;
}

/* Tabs (paginakoppen): goed leesbaar op de donkerblauwe achtergrond */
button[role="tab"] {
    color: #FFFFFF !important;
    background: rgba(255, 255, 255, 0.08) !important;
    border: 2px solid var(--tvb-secondary) !important;
    border-radius: 10px 10px 0 0 !important;
    font-size: 1.1rem !important;
    font-weight: 700 !important;
    padding: 10px 22px !important;
    margin-right: 6px !important;
    opacity: 1 !important;
}

button[role="tab"]:hover {
    background: rgba(255, 255, 255, 0.18) !important;
}

button[role="tab"].selected,
button[role="tab"][aria-selected="true"] {
    background: var(--tvb-green) !important;
    border-color: var(--tvb-green) !important;
    color: #FFFFFF !important;
}

/* Gradio zet onder het gekozen tabblad een streep; die hebben we niet nodig */
button[role="tab"].selected::after {
    display: none !important;
}


/* Primaire knoppen */
button.primary,
button[variant="primary"] {
    background: linear-gradient(
        90deg,
        var(--tvb-blue),
        #304064
    ) !important;
    color: white !important;
    border: none !important;
    border-radius: 10px !important;
    font-weight: 700 !important;
    box-shadow: 0 4px 12px rgba(34,45,79,.3) !important;
}


/* Hover */
button.primary:hover,
button[variant="primary"]:hover {
    background: var(--tvb-blue-dark) !important;
}

/* Secondary */
button.secondary,
button[variant="secondary"] {
    background: var(--tvb-green) !important;
    color: white !important;
    border: none !important;
    border-radius: 10px !important;
    font-weight: 700 !important;
}

button.secondary:hover,
button[variant="secondary"]:hover {
    background: var(--tvb-green-dark) !important;
}

/* Radio buttons: de gekozen optie duidelijk groen markeren */
input[type="radio"] {
    accent-color: var(--tvb-green) !important;
}

.gradio-container label:has(> input[type="radio"]) {
    background: var(--tvb-light) !important;
    border: 2px solid var(--tvb-secondary) !important;
    border-radius: 10px !important;
    padding: 8px 14px !important;
    cursor: pointer !important;
}

.gradio-container label:has(> input[type="radio"]:checked),
.gradio-container label.selected:has(> input[type="radio"]) {
    background: var(--tvb-green) !important;
    border-color: var(--tvb-green-dark) !important;
}

.gradio-container label:has(> input[type="radio"]:checked) span,
.gradio-container label.selected:has(> input[type="radio"]) span {
    color: #FFFFFF !important;
    font-weight: 700 !important;
}

/* Upload component */
[data-testid="file-upload"] {
    border: 2px dashed var(--tvb-green) !important;
    border-radius: 12px !important;
}

/* Inputs (niet de rondjes van radio buttons, anders verdwijnt de selectie) */
input:not([type="radio"]):not([type="checkbox"]),
textarea,
select {
    border: 2px solid var(--tvb-secondary) !important;
    border-radius: 10px !important;
    background: white !important;
}

input:focus,
textarea:focus,
select:focus {
    border-color: var(--tvb-green) !important;
    box-shadow: 0 0 0 3px rgba(56,181,168,.2) !important;
}
/* Voorkom witte randen bij scrollen */
html,
body {
    margin: 0 !important;
    padding: 0 !important;
    background-color: #222D4F !important;
    min-height: 100% !important;
}

body {
    min-height: 100vh !important;
}

/* Laat Gradio de volledige pagina bedekken */
.gradio-container {
    width: 100% !important;
    max-width: none !important;
    min-height: 100vh !important;
    margin: 0 !important;
    background-color: #222D4F !important;
}
/* =========================================
   FIX: WITTE ZIJKANTEN BIJ SCROLLEN
   ========================================= */

html,
body,
gradio-app,
.gradio-container,
.main,
main {
    background: #222D4F !important;
    background-color: #222D4F !important;
}

/* Hele browserbreedte gebruiken */
html,
body {
    width: 100% !important;
    min-width: 100% !important;
    min-height: 100vh !important;
    margin: 0 !important;
    padding: 0 !important;
    overflow-x: hidden !important;
}

/* Gradio root volledig vullen */
gradio-app {
    display: block !important;
    width: 100% !important;
    min-height: 100vh !important;
    margin: 0 !important;
    padding: 0 !important;
}

/* Gradio container geen witte buitenruimte geven */
.gradio-container {
    width: 100vw !important;
    max-width: 100vw !important;
    min-height: 100vh !important;
    margin: 0 !important;
    box-sizing: border-box !important;
}
/* Bovenste titelkaart */
#factuur-title {
    background: #FFFFFF !important;
    border: 2px solid #B8C4D2 !important;
    border-left: 7px solid #38B5A8 !important;
    border-radius: 16px !important;
    padding: 22px 26px !important;
    margin-bottom: 18px !important;
    box-shadow: 0 8px 25px rgba(34, 45, 79, 0.18) !important;
}

/* Alle tekst in de bovenste titelkaart donker houden */
#factuur-title,
#factuur-title h1,
#factuur-title h2,
#factuur-title h3,
#factuur-title p,
#factuur-title .prose,
#factuur-title .prose p {
    color: #222D4F !important;
}

/* Hoofdtitel */
#factuur-title h1 {
    color: #222D4F !important;
    font-size: 3rem !important;
    font-weight: 700 !important;
    text-align: center !important;
    border-bottom: 4px solid #38B5A8 !important;
    padding-bottom: 12px !important;
    margin-top: 0 !important;
    margin-bottom: 14px !important;
}

/* Beschrijving onder de hoofdtitel */
#factuur-title p {
    color: #222D4F !important;
    text-align: center !important;
    font-size: 1.05rem !important;
    margin-bottom: 0 !important;
}

/* Titelkaart in de Factuurgenerator-tab */
#originele-tekst-title {
    background: #FFFFFF !important;
    border: 2px solid #B8C4D2 !important;
    border-left: 7px solid #38B5A8 !important;
    border-radius: 14px !important;
    padding: 16px 20px !important;
    margin-top: 14px !important;
    margin-bottom: 18px !important;
    box-shadow: 0 6px 18px rgba(34, 45, 79, 0.15) !important;
}

/* Tekst van de titel donkerblauw houden */
#originele-tekst-title,
#originele-tekst-title h1,
#originele-tekst-title h2,
#originele-tekst-title h3,
#originele-tekst-title p,
#originele-tekst-title .prose,
#originele-tekst-title .prose p {
    color: #222D4F !important;
}

/* Opmaak van de tweede titel */
#originele-tekst-title h2 {
    color: #222D4F !important;
    font-size: 1.55rem !important;
    font-weight: 700 !important;
    margin: 0 !important;
    border: none !important;
}
"""

with gr.Blocks(
    title="AI in marketing",
) as demo:

    # ==================================================
    # TAB 1 - FACTUURGENERATOR
    # ==================================================

    with gr.Tab("Factuurgeneratie"):

        gr.Markdown(
            """
        # Factuurgeneratie

        Genereer automatisch marketingteksten en download ze als Word-document.
        """,
            elem_id="factuur-title",
        )

        gr.Markdown(
            """
        ## Originele tekst maken in de stijl van de trainingsteksten
        """,
            elem_id="originele-tekst-title",
        )

        document = gr.File(
            label="Originele tekst of opdracht voor de AI (optioneel) ",
            file_types=[".txt", ".md", ".csv", ".pdf", ".docx"],
            type="filepath",
        )

        style_text = gr.Textbox(
            label="Originele tekst of opdracht voor de AI",
            lines=6,
            placeholder=(
                "Plak hier een voorbeeldtekst of stijlregels, bijv.: korte zinnen, "
                "formele toon, veel concrete termen."
            ),
        )

        modus = gr.Radio(
            choices=["Nieuwe tekst genereren", "Tekst herschrijven"],
            value="Nieuwe tekst genereren",
            label="Functie",
        )

        # Onthoudt of de gebruiker zelf een functie heeft aangeklikt.
        modus_handmatig = gr.State(False)

        tekst_prompt = gr.Textbox(
            label="Tekstbewerking",
            lines=4,
            placeholder=(
                "Bijvoorbeeld: schrijf kort en gebruik maximaal 5 opsommingstekens."
            ),
        )

        with gr.Row():
            aanleiding = gr.Textbox(
                label="Aanleiding",
                lines=3,
                placeholder="Waarom wordt deze tekst gemaakt?",
            )

            insteek = gr.Textbox(
                label="Insteek",
                lines=3,
                placeholder="Welke invalshoek of boodschap moet centraal staan?",
            )

        with gr.Row():
            doelgroep = gr.Textbox(
                label="Doelgroep",
                lines=3,
                placeholder="Voor wie is deze tekst bedoeld?",
            )

            bedrijf = gr.Dropdown(
                label="Bedrijf",
                choices=[],
                allow_custom_value=False,
                info="De AI zoekt de tone of voice en kernwaarden van dit bedrijf.",
            )

        kanaal = gr.Dropdown(
            choices=["LinkedIn", "Website", "Instagram"],
            value="LinkedIn",
            label="Kanaal",
        )

        genereer_button = gr.Button(
            "Tekst maken",
            variant="primary",
        )

        wis_button = gr.Button("Omschrijving wissen", variant="secondary")

        factuur_resultaat = gr.Textbox(
            label="Gegenereerde factuurtekst",
            lines=12,
        )

        download_file = gr.File(
            label="Download als Word-document",
            type="filepath",
        )

        genereer_button.click(
            fn=validate_and_generate,
            inputs=[
                document,
                style_text,
                tekst_prompt,
                modus,
                aanleiding,
                insteek,
                doelgroep,
                bedrijf,
                kanaal,
            ],
            outputs=[factuur_resultaat, download_file],
        )


        modus.input(
            fn=lambda: True,
            inputs=[],
            outputs=modus_handmatig,
        )

        style_text.input(
            fn=update_modus_from_text,
            inputs=[style_text, modus_handmatig],
            outputs=modus,
        )

        wis_button.click(
            fn=lambda: (
                None,
                "",
                "",
                "Nieuwe tekst genereren",
                "",
                "",
                "",
                None,
                "LinkedIn",
                None,
                False,
            ),
            inputs=[],
            outputs=[
                document,
                style_text,
                tekst_prompt,
                modus,
                aanleiding,
                insteek,
                doelgroep,
                bedrijf,
                kanaal,
                download_file,
                modus_handmatig,
            ],
        )

    # ==================================================
    # TAB 2 - WEEKPLANNING
    # ==================================================

    with gr.Tab("Weekplanning"):

        gr.Markdown(
            """
        # Weekplanning

        Wat moet er deze week de deur uit? Maak in één keer Word-concepten
        voor alle geplande posts, of download de planning als Excel.
        """,
            elem_id="factuur-title",
        )

        with gr.Row():
            planning_week = gr.Dropdown(
                label="Week",
                choices=[],
                scale=3,
            )
            planning_bedrijf = gr.Dropdown(
                label="Bedrijf",
                choices=[],
                scale=2,
            )
            planning_vernieuwen = gr.Button(
                "Planning vernieuwen",
                variant="secondary",
                scale=1,
            )

        planning_tabel = gr.Dataframe(
            label="Geplande posts",
            interactive=False,
            wrap=True,
        )

        planning_opnieuw = gr.Checkbox(
            label="Bestaande concepten opnieuw maken (kost extra API-aanroepen)",
            value=False,
        )

        with gr.Row():
            concepten_button = gr.Button(
                "Concepten maken voor deze week",
                variant="primary",
            )
            excel_button = gr.Button(
                "Planning downloaden (Excel)",
                variant="secondary",
            )

        planning_status = gr.Textbox(label="Status", interactive=False)

        planning_bestanden = gr.File(
            label="Concepten (Word)",
            file_count="multiple",
            interactive=False,
        )

        planning_excel = gr.File(
            label="Planning als Excel (één regel per post, met filters)",
            interactive=False,
        )

        for keuzelijst in (planning_week, planning_bedrijf):
            keuzelijst.change(
                fn=toon_planning_week,
                inputs=[planning_week, planning_bedrijf],
                outputs=planning_tabel,
            )

        planning_vernieuwen.click(
            fn=laad_planning_keuzes,
            inputs=planning_bedrijf,
            outputs=[planning_week, planning_bedrijf],
        ).then(
            fn=toon_planning_week,
            inputs=[planning_week, planning_bedrijf],
            outputs=planning_tabel,
        )

        concepten_button.click(
            fn=maak_planning_concepten,
            inputs=[planning_week, planning_bedrijf, planning_opnieuw],
            outputs=[planning_bestanden, planning_status],
        )

        excel_button.click(
            fn=download_planning_excel,
            inputs=planning_bedrijf,
            outputs=planning_excel,
        )

    demo.load(
        fn=laad_bedrijven,
        inputs=[],
        outputs=bedrijf,
    )

    demo.load(
        fn=laad_planning_keuzes,
        inputs=[],
        outputs=[planning_week, planning_bedrijf],
    ).then(
        fn=toon_planning_week,
        inputs=[planning_week, planning_bedrijf],
        outputs=planning_tabel,
    )

    # ==================================================
    # LEGACY BUTTON HANDLERS
    # ==================================================

    # Kept intentionally empty to avoid duplicate callbacks after the tab reorder.



if __name__ == "__main__":
    initialize_database()
    Thread(target=warm_up_embedding_model, daemon=True).start()

    port = int(os.environ.get("PORT", 7860))

    demo.queue().launch(
        share=True,
        server_name="0.0.0.0",
        server_port=port,
        theme=APP_THEME,
        css=APP_CSS,
        # Word-concepten en agenda staan in <project>/outputs.
        allowed_paths=[str(PROJECT_DIR / "outputs")],
    )

