import tempfile
from pathlib import Path

import gradio as gr

from foto_model import edit_photo
from importlib import import_module
from database import create_connection
from document_repository import get_project_names


genereer_factuurtekst = import_module("text_generator").genereer_factuurtekst


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


def validate_and_edit(
    input_image,
    prompt,
    logo,
    opacity,
    logo_position,
):
    if input_image is None:
        raise gr.Error("Upload eerst een foto.")

    try:
        return edit_photo(
            input_image,
            prompt,
            logo,
            opacity,
            logo_position,
        )
    except FileNotFoundError as error:
        if "Checkpoint bestaat niet" not in str(error):
            raise

        raise gr.Error(
            "Het fotomodel is nog niet getraind. "
            "Train eerst een model met: python foto_model.py train"
        ) from error


def save_generated_text(text):
    if not text or not text.strip():
        return None

    output_dir = Path(__file__).resolve().parent / "outputs"
    output_dir.mkdir(exist_ok=True)

    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        suffix=".txt",
        dir=output_dir,
        delete=False,
    ) as bestand:
        bestand.write(text.strip())
        return bestand.name


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
    opdracht,
):
    if not opdracht or not opdracht.strip():
        raise gr.Error("Beschrijf eerst de uitgevoerde werkzaamheden.")

    try:
        resultaat = genereer_factuurtekst(
            opdracht.strip(),
            document=document,
            style_text=style_text or "",
            prompt=prompt or "",
            modus=modus or "Tekst herschrijven",
            aanleiding=aanleiding or "",
            insteek=insteek or "",
            doelgroep=doelgroep or "",
            bedrijf=bedrijf or "",
            kanaal=kanaal or "LinkedIn",
        )
        return resultaat, save_generated_text(resultaat)
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
# Factuurgenerator & Fotomodel

Gebruik de tabs hieronder om foto's te bewerken of automatisch factuurteksten te genereren.
"""
    )

    # ==================================================
    # TAB 1 - FACTUURGENERATOR
    # ==================================================

    with gr.Tab("Factuurgenerator"):

        gr.Markdown(
            """
### Tekst maken in de stijl van de trainingsteksten

Kies of je bestaande tekst wilt herschrijven of een nieuwe tekst wilt laten maken.
"""
        )

        modus = gr.Radio(
            choices=["Tekst herschrijven", "Nieuwe tekst genereren"],
            value="Tekst herschrijven",
            label="Wat wil je doen?",
        )

        document = gr.File(
            label="Orignele tekst om te herschrijven of stijlregels voor de AI (optioneel)",
            file_types=[".txt", ".md", ".csv", ".pdf", ".docx"],
            type="filepath",
        )

        style_text = gr.Textbox(
            label="Orignele tekst om te herschrijven of stijlregels voor de AI (optioneel)",
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

        opdracht = gr.Textbox(
            label="Brontekst of opdracht",
            lines=10,
            max_lines=16,
            placeholder="""
Voorbeeld:

Omschrijf hier de Factuurtekst en de speficaties van de content in de vacature zoals de hoeveel jaren ervarng

""",
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
            label="Download gegenereerde tekst",
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
                opdracht,
            ],
            outputs=[factuur_resultaat, download_file],
        )

        wis_button.click(
            fn=lambda: (None, "", "", "", "", "", None, "LinkedIn", "", None),
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
                opdracht,
                download_file,
            ],
        )

    # ==================================================
    # TAB 2 - FOTO BEWERKING
    # ==================================================

    with gr.Tab("Foto Bewerking"):

        with gr.Row():

            with gr.Column(scale=5, elem_classes="panel"):

                photo = gr.Image(
                    type="filepath",
                    label="Originele foto",
                    sources=["upload"],
                )

                prompt = gr.Textbox(
                    label="Fotobewerking",
                    lines=4,
                    placeholder=(
                        "Bijvoorbeeld: maak de foto zwart-wit "
                        "of geef de foto een zachte gloed"
                    ),
                )

                logo = gr.Checkbox(
                    label="Logo toevoegen",
                    value=False,
                )

                opacity = gr.Slider(
                    minimum=0,
                    maximum=100,
                    value=50,
                    step=5,
                    label="Logo transparantie (%)",
                )

                logo_position = gr.Dropdown(
                    choices=[
                        "Midden",
                        "Linksboven",
                        "Rechtsboven",
                        "Linksonder",
                        "Rechtsonder",
                    ],
                    value="Midden",
                    label="Logo positie",
                )

                edit_button = gr.Button(
                    "Foto aanpassen",
                    variant="primary",
                )

            with gr.Column(scale=6, elem_classes="panel"):

                result = gr.Image(
                    label="Resultaat",
                    format="png",
                )

                status = gr.Markdown(
                    "Upload een foto en klik op 'Foto aanpassen'."
                )

        edit_button.click(
            fn=validate_and_edit,
            inputs=[
                photo,
                prompt,
                logo,
                opacity,
                logo_position,
            ],
            outputs=[
                result,
                status,
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
    demo.launch()
