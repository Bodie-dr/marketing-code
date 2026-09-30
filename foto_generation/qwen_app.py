"""
Qwen test-app: stijl leren uit referentiefoto's en foto's daarmee bewerken.

Starten:  python foto_generation/qwen_app.py
"""

import logging
import os

import gradio as gr
from gradio.themes import Base
from PIL import Image

import qwen_backend as qb

logger = logging.getLogger(__name__)

BACKEND_KEUZES = ["auto", "cloud", "lokaal"]

APP_CSS = """
.gradio-container {
    background: linear-gradient(135deg, #222D4F 0%, #2A3763 35%, #F5F7FA 100%) !important;
}
.gradio-container .prose h1,
.gradio-container .prose h2,
.gradio-container .prose p {
    color: #FFFFFF !important;
}
button.primary {
    background: #38B5A8 !important;
    border: none !important;
}
button.primary:hover {
    background: #2D9A8E !important;
}
"""


def backend_uitleg() -> str:
    actief = qb.kies_backend()
    if actief == "lokaal":
        return "Backend **auto** gebruikt nu **lokaal** (CUDA-GPU gevonden, model Qwen-Image-2.1)."
    return (
        "Backend **auto** gebruikt nu **cloud** (geen CUDA-GPU gevonden). "
        f"Analyse: `{qb.CLOUD_ANALYSE_MODEL}`, bewerken: `{qb.CLOUD_EDIT_MODEL}`."
    )


def leer_stijl(bestanden, naam, backend):
    if not bestanden:
        raise gr.Error("Upload minstens één referentiefoto.")
    if not (naam or "").strip():
        raise gr.Error("Geef de stijl een naam, bijvoorbeeld 'TVB zomercampagne'.")
    try:
        fotos = [Image.open(pad) for pad in bestanden]
        stijl, gebruikt = qb.analyseer_stijl(fotos, backend)
        pad = qb.sla_stijl_op(naam, stijl, len(fotos), gebruikt)
    except Exception as fout:
        logger.exception("Stijlanalyse mislukt")
        raise gr.Error(f"Analyse mislukt: {fout}") from fout

    kleuren = " ".join(
        f"<span style='display:inline-block;width:28px;height:28px;border-radius:6px;"
        f"background:{kleur};border:1px solid #ccc' title='{kleur}'></span>"
        for kleur in stijl.get("kleurpalet", [])
    )
    samenvatting = (
        f"**{stijl['samenvatting']}**\n\n{kleuren}\n\n"
        f"Opgeslagen als `{pad.name}` ({len(fotos)} foto's, backend: {gebruikt})."
    )
    namen = qb.stijl_namen()
    return (
        samenvatting,
        stijl,
        gr.update(choices=["(geen)"] + namen, value=qb.veilige_naam(naam)),
    )


def toon_stijl(naam):
    if not naam or naam == "(geen)":
        return None
    return qb.laad_stijl(naam)


def pas_foto_aan(foto, instructie, stijl_naam, stappen, seed, backend):
    stijl = None if not stijl_naam or stijl_naam == "(geen)" else qb.laad_stijl(stijl_naam)
    try:
        resultaat, pad, prompt = qb.bewerk_foto(foto, instructie, stijl, stappen, seed, backend)
    except ValueError as fout:
        raise gr.Error(str(fout)) from fout
    except Exception as fout:
        logger.exception("Bewerken mislukt")
        raise gr.Error(f"Bewerken mislukt: {fout}") from fout
    return resultaat, f"Prompt naar Qwen:\n{prompt}\n\nOpgeslagen: {pad}"


def ververs_stijlen():
    return gr.update(choices=["(geen)"] + qb.stijl_namen())


with gr.Blocks(title="Qwen foto-test") as demo:
    gr.Markdown("# Qwen foto-test")
    gr.Markdown(backend_uitleg())

    with gr.Tab("1. Stijl leren"):
        gr.Markdown(
            "Upload een paar foto's in de gewenste huisstijl. Qwen3-VL analyseert "
            "wat ze gemeen hebben en slaat dat op als stijlprofiel."
        )
        with gr.Row():
            with gr.Column():
                referenties = gr.File(
                    label="Referentiefoto's",
                    file_count="multiple",
                    file_types=["image"],
                    type="filepath",
                )
                stijl_naam_in = gr.Textbox(label="Naam van de stijl", placeholder="TVB zomercampagne")
                backend_analyse = gr.Dropdown(BACKEND_KEUZES, value="auto", label="Backend")
                analyse_knop = gr.Button("Analyseer stijl", variant="primary")
            with gr.Column():
                stijl_samenvatting = gr.Markdown()
                stijl_json = gr.JSON(label="Stijlprofiel")

    with gr.Tab("2. Foto bewerken"):
        gr.Markdown(
            "Pas een foto aan met een instructie, een geleerde stijl, of allebei. "
            "Zonder instructie wordt alleen de stijl toegepast."
        )
        with gr.Row():
            with gr.Column():
                foto_in = gr.Image(label="Originele foto", type="pil")
                instructie = gr.Textbox(
                    label="Instructie (optioneel)",
                    placeholder="Vervang de achtergrond door een zonnig kantoor",
                    lines=2,
                )
                with gr.Row():
                    stijl_keuze = gr.Dropdown(
                        ["(geen)"] + qb.stijl_namen(), value="(geen)", label="Stijl"
                    )
                    ververs_knop = gr.Button("↻", scale=0, min_width=40)
                with gr.Accordion("Instellingen", open=False):
                    stappen = gr.Slider(10, 50, value=30, step=1, label="Stappen")
                    seed = gr.Number(value=42, precision=0, label="Seed")
                    backend_edit = gr.Dropdown(BACKEND_KEUZES, value="auto", label="Backend")
                bewerk_knop = gr.Button("Bewerk foto", variant="primary")
            with gr.Column():
                foto_uit = gr.Image(label="Resultaat", type="pil", format="png")
                info = gr.Textbox(label="Details", lines=5, interactive=False)
                gekozen_stijl = gr.JSON(label="Gekozen stijl")

    analyse_knop.click(
        leer_stijl,
        inputs=[referenties, stijl_naam_in, backend_analyse],
        outputs=[stijl_samenvatting, stijl_json, stijl_keuze],
    )
    stijl_keuze.change(toon_stijl, inputs=stijl_keuze, outputs=gekozen_stijl)
    ververs_knop.click(ververs_stijlen, outputs=stijl_keuze)
    bewerk_knop.click(
        pas_foto_aan,
        inputs=[foto_in, instructie, stijl_keuze, stappen, seed, backend_edit],
        outputs=[foto_uit, info],
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    demo.queue().launch(
        server_name="127.0.0.1",
        server_port=int(os.environ.get("QWEN_PORT", 7861)),
        theme=Base(primary_hue="cyan", secondary_hue="blue", neutral_hue="slate"),
        css=APP_CSS,
    )
