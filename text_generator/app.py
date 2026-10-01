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
from web_reader import lees_webpagina


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


def update_modus_from_bron(style_text, bron_url, handmatig_gekozen=False):
    """Een geplakte tekst of link betekent bijna altijd: herschrijven."""
    return update_modus_from_text(
        f"{style_text or ''}{bron_url or ''}", handmatig_gekozen
    )


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
    bron_url="",
):
    opdracht = "\n".join(
        waarde
        for waarde in [aanleiding, insteek, doelgroep, bedrijf]
        if waarde and waarde.strip()
    )

    if modus == "Tekst herschrijven" and not (
        document or style_text or (bron_url and bron_url.strip())
    ):
        raise gr.Error(
            "Plak de tekst of een link, of upload het bestand dat je wilt herschrijven."
        )

    if bron_url and bron_url.strip():
        try:
            webtekst = lees_webpagina(bron_url)
        except ValueError as fout:
            raise gr.Error(str(fout)) from fout
        gr.Info(f"Tekst van de webpagina opgehaald ({len(webtekst.split())} woorden).")
        style_text = f"{style_text or ''}\n\n{webtekst}".strip()

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
            "De tekst kon niet worden gegenereerd. "
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

    /* Rollen: deze wisselen tussen licht en donker */
    --tvb-bg: #F5F7FA;
    --tvb-vlak: #FFFFFF;
    --tvb-tekst: #222D4F;
    --tvb-rand: #DDE3EB;
    --tvb-rand-sterk: #B8C4D2;
    --tvb-muted: #5B6782;
    --tvb-placeholder: #7A8499;
    --tvb-kop: #222D4F;
    --tvb-keuze: #E3F4F2;
}

/* Donkere modus: Gradio zet de klasse "dark" op body (systeeminstelling of de knop) */
body.dark {
    --tvb-bg: #141C31;
    --tvb-vlak: #1C2640;
    --tvb-tekst: #E6EBF2;
    --tvb-rand: #2F3B5E;
    --tvb-rand-sterk: #4A5880;
    --tvb-muted: #A3AEC4;
    --tvb-placeholder: #7F8AA3;
    --tvb-kop: #0F1627;
    --tvb-keuze: rgba(56, 181, 168, 0.18);
}

/* Effen lichte achtergrond over de hele pagina (ook bij scrollen) */
html,
body,
gradio-app,
.gradio-container,
main {
    background: var(--tvb-bg) !important;
    margin: 0 !important;
}

/* html staat boven body en ziet de donkere variabelen dus niet */
html:has(body.dark) {
    background: #141C31 !important;
}

/* Laat de blauwe kopbalk buiten de container doorlopen; horizontaal scrollen voorkomen */
html,
body {
    overflow-x: clip !important;
}

.gradio-container,
.gradio-container .main,
.gradio-container .wrap,
.gradio-container main.contain {
    overflow: visible !important;
}

.gradio-container {
    max-width: 1280px !important;
    margin: 0 auto !important;
    padding: 0 24px 48px !important;
    color: var(--tvb-tekst);
}

.gradio-container label span,
.gradio-container .prose,
.gradio-container .prose p {
    color: var(--tvb-tekst) !important;
}

.gradio-container .info {
    color: var(--tvb-muted) !important;
}

/* Kop bovenaan: donkerblauwe balk die over de volle breedte doorloopt achter de tabs.
   De schaduw + clip-path maakt hem breder dan de container zonder de layout te verschuiven. */
#app-kop {
    background: var(--tvb-kop);
    box-shadow: 0 0 0 100vmax var(--tvb-kop);
    clip-path: inset(-100vmax -100vmax 0);
    padding: 14px 0 0 !important;
    margin-bottom: calc(-1 * var(--layout-gap, 16px)) !important;
    align-items: center !important;
    border: none !important;
    gap: 16px !important;
}

#app-kop .app-naam,
#app-kop .app-naam * {
    color: #FFFFFF !important;
    font-size: 1.25rem;
    line-height: 1.3;
    padding: 0 !important;
    background: transparent !important;
    border: none !important;
}

#app-kop .app-naam strong {
    font-weight: 700;
}

#app-kop .app-naam span {
    color: var(--tvb-secondary) !important;
}

/* Wisselknop licht/donker rechts in de kopbalk */
#app-kop button.thema-knop {
    background: transparent !important;
    color: #FFFFFF !important;
    border: 1.5px solid rgba(255, 255, 255, 0.35) !important;
    box-shadow: none !important;
    font-weight: 500 !important;
}

#app-kop button.thema-knop:hover {
    border-color: #FFFFFF !important;
}

/* Tabs in de blauwe balk */
.tab-wrapper {
    background: var(--tvb-kop);
    box-shadow: 0 0 0 100vmax var(--tvb-kop);
    clip-path: inset(0 -100vmax);
    margin-bottom: 28px !important;
    border: none !important;
}

.tab-wrapper button[role="tab"] {
    color: rgba(255, 255, 255, 0.72) !important;
    background: transparent !important;
    border: none !important;
    font-size: 1rem !important;
    font-weight: 600 !important;
    padding: 14px 18px 12px !important;
}

.tab-wrapper button[role="tab"]:hover {
    color: #FFFFFF !important;
}

.tab-wrapper button[role="tab"].selected,
.tab-wrapper button[role="tab"][aria-selected="true"] {
    color: #FFFFFF !important;
    box-shadow: inset 0 -3px 0 var(--tvb-green) !important;
}

.tab-wrapper button[role="tab"].selected::after {
    display: none !important;
}

/* Korte uitleg bovenaan elke tab */
.pagina-intro p {
    max-width: 68ch;
    margin: 0 0 20px !important;
    font-size: 1.05rem !important;
    line-height: 1.55 !important;
}

/* Panelen (wit in licht, donkerblauw in donker) */
.paneel {
    background: var(--tvb-vlak) !important;
    border: 1px solid var(--tvb-rand) !important;
    border-radius: 14px !important;
    padding: 20px !important;
    gap: 16px !important;
}

/* Binnen een paneel geen extra grijze vakken en randen rond de velden */
.paneel .form,
.paneel .block {
    background: transparent !important;
    border: none !important;
    box-shadow: none !important;
}

.paneel .block {
    padding: 0 !important;
}

.paneel .form {
    gap: 16px !important;
}

/* Velden naast elkaar onderaan uitlijnen, ook als de uitleg erboven verschilt */
.rij-onder,
.rij-onder > .form {
    align-items: flex-end !important;
}

/* Dropdowns: één witte rand zoals de andere velden, geen grijs vak eromheen */
.paneel .container > .wrap {
    background: var(--tvb-vlak) !important;
    border: 1.5px solid var(--tvb-rand) !important;
    border-radius: 10px !important;
    box-shadow: none !important;
}

.paneel .container > .wrap input[role="combobox"] {
    background: transparent !important;
    border: none !important;
    box-shadow: none !important;
}

.paneel .container > .wrap:focus-within {
    border-color: var(--tvb-green) !important;
    box-shadow: 0 0 0 3px rgba(56, 181, 168, 0.2) !important;
}

/* Primaire knop: TVB-groen met donkerblauwe tekst (wit op groen is te weinig contrast) */
button.primary {
    background: var(--tvb-green) !important;
    color: var(--tvb-blue) !important;
    border: none !important;
    border-radius: 10px !important;
    font-weight: 700 !important;
    font-size: 1.05rem !important;
}

button.primary:hover {
    background: var(--tvb-green-dark) !important;
    color: #FFFFFF !important;
}

/* Secundaire knop: wit met rand */
button.secondary {
    background: var(--tvb-vlak) !important;
    color: var(--tvb-tekst) !important;
    border: 1.5px solid var(--tvb-rand-sterk) !important;
    border-radius: 10px !important;
    font-weight: 600 !important;
}

button.secondary:hover {
    border-color: var(--tvb-tekst) !important;
}

/* Wissen: bewust onopvallend, het is geen hoofdactie */
button.secondary.knop-stil {
    background: transparent !important;
    border: none !important;
    box-shadow: none !important;
    flex-grow: 0 !important;
    color: var(--tvb-muted) !important;
    font-weight: 500 !important;
    text-decoration: underline;
    text-underline-offset: 3px;
}

button.secondary.knop-stil:hover {
    color: var(--tvb-tekst) !important;
}

button:focus-visible {
    outline: 3px solid var(--tvb-green) !important;
    outline-offset: 2px !important;
}

/* Radio buttons: de gekozen optie duidelijk markeren */
input[type="radio"] {
    accent-color: var(--tvb-green) !important;
}

.gradio-container label:has(> input[type="radio"]) {
    background: var(--tvb-bg) !important;
    border: 1.5px solid var(--tvb-rand) !important;
    border-radius: 10px !important;
    padding: 8px 14px !important;
    cursor: pointer !important;
}

.gradio-container label:has(> input[type="radio"]:checked),
.gradio-container label.selected:has(> input[type="radio"]) {
    background: var(--tvb-keuze) !important;
    border-color: var(--tvb-green) !important;
}

.gradio-container label:has(> input[type="radio"]:checked) span {
    font-weight: 700 !important;
}

/* Upload component */
[data-testid="file-upload"] {
    border: 1.5px dashed var(--tvb-rand-sterk) !important;
    border-radius: 12px !important;
}

/* Invoervelden (niet de rondjes van radio buttons, anders verdwijnt de selectie) */
input:not([type="radio"]):not([type="checkbox"]),
textarea,
select {
    color: var(--tvb-tekst) !important;
    border: 1.5px solid var(--tvb-rand) !important;
    border-radius: 10px !important;
    background: var(--tvb-vlak) !important;
}

input::placeholder,
textarea::placeholder {
    color: var(--tvb-placeholder) !important;
}

input:focus,
textarea:focus,
select:focus {
    border-color: var(--tvb-green) !important;
    box-shadow: 0 0 0 3px rgba(56, 181, 168, 0.2) !important;
}

/* Leeg Word-vak klein houden zolang er nog geen document is */
#word-download .empty {
    min-height: 64px !important;
    height: 64px !important;
}

/* Resultaat: iets rustiger leesbaar */
#tekst-resultaat textarea {
    font-size: 1rem !important;
    line-height: 1.6 !important;
}
"""

MODUS_NIEUW = "Nieuwe tekst genereren"
MODUS_HERSCHRIJVEN = "Tekst herschrijven"


# Licht/donker wisselen gebeurt in de browser; de keuze blijft per browser bewaard.
THEMA_WISSELEN_JS = """
() => {
    const donker = document.body.classList.toggle("dark");
    try { localStorage.setItem("tvb-thema", donker ? "dark" : "light"); } catch (e) {}
}
"""

THEMA_HERSTELLEN_JS = """
() => {
    let thema = null;
    try { thema = localStorage.getItem("tvb-thema"); } catch (e) {}
    if (thema === "dark") document.body.classList.add("dark");
    if (thema === "light") document.body.classList.remove("dark");
}
"""


def open_brontekst_bij_herschrijven(modus):
    """Bij herschrijven is de bestaande tekst verplicht, dus klap die open."""
    if modus == MODUS_HERSCHRIJVEN:
        return gr.Accordion(open=True)
    return gr.update()


with gr.Blocks(
    title="AI in marketing",
) as demo:

    with gr.Row(elem_id="app-kop", equal_height=True):
        gr.HTML("<strong>TVB</strong> <span>Marketing-AI</span>", elem_classes="app-naam")
        thema_knop = gr.Button(
            "Licht of donker",
            variant="secondary",
            size="sm",
            scale=0,
            min_width=130,
            elem_classes="thema-knop",
        )

    thema_knop.click(fn=None, js=THEMA_WISSELEN_JS)
    demo.load(fn=None, js=THEMA_HERSTELLEN_JS)

    # ==================================================
    # TAB 1 - TEKST MAKEN
    # ==================================================

    with gr.Tab("Tekst maken"):

        gr.Markdown(
            "Schrijf een marketingtekst in de tone of voice van een van onze "
            "bedrijven. Kopieer hem direct of download hem als Word-document.",
            elem_classes="pagina-intro",
        )

        with gr.Row(equal_height=False):
            with gr.Column(scale=3, elem_classes="paneel"):

                with gr.Row(elem_classes="rij-onder"):
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
                        info="De AI gebruikt voorbeeldteksten van dit kanaal.",
                    )

                modus = gr.Radio(
                    choices=[MODUS_NIEUW, MODUS_HERSCHRIJVEN],
                    value=MODUS_NIEUW,
                    label="Wat wil je doen?",
                )

                # Onthoudt of de gebruiker zelf een functie heeft aangeklikt.
                modus_handmatig = gr.State(False)

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

                doelgroep = gr.Textbox(
                    label="Doelgroep",
                    lines=2,
                    placeholder="Voor wie is deze tekst bedoeld?",
                )

                tekst_prompt = gr.Textbox(
                    label="Extra instructies (optioneel)",
                    lines=3,
                    placeholder=(
                        "Bijvoorbeeld: schrijf kort en gebruik maximaal 5 opsommingstekens."
                    ),
                )

                with gr.Accordion("Bestaande tekst of webpagina (optioneel)", open=False) as brontekst:
                    style_text = gr.Textbox(
                        label="Plak een tekst",
                        lines=6,
                        info=(
                            "Bij een nieuwe tekst gebruikt de AI dit als stijlvoorbeeld. "
                            "Bij herschrijven is dit de tekst die herschreven wordt."
                        ),
                        placeholder=(
                            "Plak hier een voorbeeldtekst of stijlregels, bijv.: korte zinnen, "
                            "formele toon, veel concrete termen."
                        ),
                    )

                    bron_url = gr.Textbox(
                        label="Of plak een link naar een webpagina",
                        placeholder="https://www.voorbeeld.nl/nieuws/artikel",
                        info="De app haalt de tekst van de pagina op en gebruikt die als bestaande tekst.",
                        max_lines=1,
                    )

                    document = gr.File(
                        label="Of upload een bestand",
                        file_types=[".txt", ".md", ".csv", ".pdf", ".docx"],
                        type="filepath",
                    )

                with gr.Row():
                    genereer_button = gr.Button(
                        "Tekst maken",
                        variant="primary",
                        scale=3,
                    )

                    wis_button = gr.Button(
                        "Formulier wissen",
                        variant="secondary",
                        elem_classes="knop-stil",
                        scale=1,
                    )

            with gr.Column(scale=2, elem_classes="paneel"):

                tekst_resultaat = gr.Textbox(
                    label="Jouw tekst",
                    lines=20,
                    placeholder="Vul links het formulier in en klik op Tekst maken.",
                    buttons=["copy"],
                    elem_id="tekst-resultaat",
                )

                download_file = gr.File(
                    label="Word-document",
                    type="filepath",
                    elem_id="word-download",
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
                bron_url,
            ],
            outputs=[tekst_resultaat, download_file],
        )


        modus.input(
            fn=lambda: True,
            inputs=[],
            outputs=modus_handmatig,
        )

        modus.change(
            fn=open_brontekst_bij_herschrijven,
            inputs=modus,
            outputs=brontekst,
        )

        for bronveld in (style_text, bron_url):
            bronveld.input(
                fn=update_modus_from_bron,
                inputs=[style_text, bron_url, modus_handmatig],
                outputs=modus,
            )

        wis_button.click(
            fn=lambda: (
                None,
                "",
                "",
                MODUS_NIEUW,
                "",
                "",
                "",
                None,
                "LinkedIn",
                None,
                False,
                "",
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
                bron_url,
            ],
        )

    # ==================================================
    # TAB 2 - WEEKPLANNING
    # ==================================================

    with gr.Tab("Weekplanning"):

        gr.Markdown(
            "Wat moet er deze week de deur uit? Maak in één keer Word-concepten "
            "voor alle geplande posts, of download de planning als Excel.",
            elem_classes="pagina-intro",
        )

        with gr.Column(elem_classes="paneel"):
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
        css=APP_CSS
    )

