import tempfile
import os
from pathlib import Path

import gradio as gr
from docx import Document

from database.database import create_connection, create_schema
from database.document_repository import get_project_names

from Tekst_gen.tekst_model import generate_text


def initialize_database() -> None:
    connection = create_connection()
    try:
        create_schema(connection)
    finally:
        connection.close()


def laad_bedrijven():
    connection = None

    try:
        connection = create_connection()
        bedrijven = get_project_names(connection)
    except Exception:
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

    output_dir = Path(__file__).resolve().parent / "outputs"
    output_dir.mkdir(exist_ok=True)

    with tempfile.NamedTemporaryFile(
        suffix=".docx",
        dir=output_dir,
        delete=False,
    ) as bestand:
        bestand_path = Path(bestand.name)

    document = Document()
    for regel in text.strip().splitlines():
        document.add_paragraph(regel)
    document.save(bestand_path)
    return str(bestand_path)


def validate_and_generate(
    document,
    style_text,
    prompt,
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

    if not opdracht:
        raise gr.Error(
            "Vul minimaal de aanleiding, insteek, doelgroep of het bedrijf in."
        )

    try:
        resultaat = generate_text(
            opdracht.strip(),
            document=document,
            style_text=style_text or "",
            prompt=prompt or "",
            modus="Nieuwe tekst genereren",
            aanleiding=aanleiding or "",
            insteek=insteek or "",
            doelgroep=doelgroep or "",
            bedrijf=bedrijf or "",
            kanaal=kanaal or "LinkedIn",
        )
        return resultaat, save_generated_word(resultaat)
    except Exception as error:
        raise gr.Error(
            "De factuurtekst kon niet worden gegenereerd. "
            "Controleer je API-configuratie en probeer opnieuw."
        ) from error


with gr.Blocks(
    title="FotoModel & Factuurgenerator",
    theme=gr.themes.Base(
    primary_hue="cyan",
    secondary_hue="blue",
    neutral_hue="slate",
),
    css = """
:root {
    --tvb-blue: #1E2B4F;
    --tvb-blue-dark: #172544;
    --tvb-green: #2BA7A2;
    --tvb-green-dark: #228C8A;
    --tvb-light: #EEF2F5;
    --tvb-secondary: #C3CCD8;
}

.gradio-container {
    background: linear-gradient(
        135deg,
        #EEF2F5 0%,
        #FFFFFF 100%
    ) !important;
}

h1 {
    color: var(--tvb-blue) !important;
    font-size: 3.2rem !important;
    font-weight: 900 !important;
}

h2,h3,h4,h5,h6 {
    color: var(--tvb-blue) !important;
}

/* Kaarten */
.panel {
    background: white !important;
    border: 2px solid var(--tvb-blue) !important;
    border-radius: 18px !important;
    padding: 18px !important;
    box-shadow: 0 10px 25px rgba(30,43,79,.12) !important;
}

/* Tabs */
button.selected {
    background: var(--tvb-blue) !important;
    color: white !important;
    border-color: var(--tvb-blue) !important;
}

/* Primaire knoppen */
button.primary,
button[variant="primary"] {
    background: var(--tvb-blue) !important;
    color: white !important;
    border: none !important;
    font-weight: 700 !important;
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
}

button.secondary:hover,
button[variant="secondary"]:hover {
    background: var(--tvb-green-dark) !important;
}

/* Radio buttons */
input[type="radio"] {
    accent-color: var(--tvb-green) !important;
}

/* Upload component */
[data-testid="file-upload"] {
    border: 2px dashed var(--tvb-green) !important;
    border-radius: 12px !important;
}

/* Inputs */
input,
textarea,
select {
    border-radius: 10px !important;
    border: 1px solid var(--tvb-secondary) !important;
}
""",
) as demo:

    gr.Markdown(
        """
# Factuurgenerator

Genereer automatisch marketingteksten en download ze als Word-document.
"""
    )

    # ==================================================
    # TAB 1 - FACTUURGENERATOR
    # ==================================================

    with gr.Tab("Factuurgenerator"):

        gr.Markdown(
            """
### Originele tekst maken in de stijl van de trainingsteksten
"""
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
                aanleiding,
                insteek,
                doelgroep,
                bedrijf,
                kanaal,
            ],
            outputs=[factuur_resultaat, download_file],
        )

        wis_button.click(
            fn=lambda: (None, "", "", "", "", "", None, "LinkedIn", None),
            inputs=[],
            outputs=[
                document,
                style_text,
                tekst_prompt,
                aanleiding,
                insteek,
                doelgroep,
                bedrijf,
                kanaal,
                download_file,
            ],
        )

    demo.load(
        fn=laad_bedrijven,
        inputs=[],
        outputs=bedrijf,
    )

    # ==================================================
    # LEGACY BUTTON HANDLERS
    # ==================================================

    # Kept intentionally empty to avoid duplicate callbacks after the tab reorder.

if __name__ == "__main__":
    initialize_database()
    demo.launch(
    )
