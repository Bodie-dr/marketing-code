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


def _referentie_paden(bestanden, map_upload, map_pad):
    """Alle foto's uit losse bestanden, een geüploade map en/of een lokaal mappad."""
    if map_pad and map_pad.strip() and not os.path.isdir(map_pad.strip().strip('"')):
        raise gr.Error(f"Map niet gevonden: {map_pad.strip()}")
    return qb.verzamel_fotos([*(bestanden or []), *(map_upload or []), map_pad])


def tel_referenties(bestanden, map_upload, map_pad):
    try:
        paden = _referentie_paden(bestanden, map_upload, map_pad)
    except gr.Error as fout:
        return f"⚠️ {fout.message}"
    if not paden:
        return ""
    gebruikt = len(qb.kies_verdeeld(paden))
    if gebruikt < len(paden):
        return (
            f"**{len(paden)} foto's gevonden.** Er worden er {gebruikt} gebruikt, "
            "gelijkmatig verdeeld over de map."
        )
    return f"**{len(paden)} foto's gevonden.**"


def leer_stijl(bestanden, map_upload, map_pad, naam, backend):
    paden = _referentie_paden(bestanden, map_upload, map_pad)
    if not paden:
        raise gr.Error("Upload minstens één referentiefoto, of kies een map met foto's.")
    if not (naam or "").strip():
        raise gr.Error("Geef de stijl een naam, bijvoorbeeld 'TVB zomercampagne'.")

    fotos, onleesbaar = [], 0
    for pad in qb.kies_verdeeld(paden):
        try:
            with Image.open(pad) as foto:
                # Meteen verkleinen: een map vol grote foto's past anders niet in het geheugen.
                fotos.append(qb.verklein(foto))
        except OSError:
            logger.warning("Foto overgeslagen (onleesbaar): %s", pad)
            onleesbaar += 1
    if not fotos:
        raise gr.Error("Geen van de gekozen foto's kon worden geopend.")

    try:
        stijl, gebruikt = qb.analyseer_stijl(fotos, backend)
        pad = qb.sla_stijl_op(naam, stijl, len(fotos), gebruikt)
    except Exception as fout:
        logger.exception("Stijlanalyse mislukt")
        raise gr.Error(f"Analyse mislukt: {fout}") from fout

    details = stijl.get("kleurpalet_details") or [
        {"hex": kleur, "aandeel": None, "soort": ""} for kleur in stijl.get("kleurpalet", [])
    ]
    kleuren = " ".join(
        f"<span style='display:inline-flex;flex-direction:column;align-items:center;"
        f"margin-right:6px;font-size:11px'>"
        f"<span style='width:40px;height:40px;border-radius:6px;background:{kleur['hex']};"
        f"border:1px solid #ccc' title='{kleur['hex']} ({kleur['soort']})'></span>"
        f"{kleur['hex']}"
        + (f"<br>{kleur['aandeel']:.0%}" if kleur["aandeel"] is not None else "")
        + "</span>"
        for kleur in details
    )
    overgeslagen = f", {onleesbaar} onleesbaar overgeslagen" if onleesbaar else ""
    samenvatting = (
        f"**{stijl['samenvatting']}**\n\n{kleuren}\n\n"
        f"Opgeslagen als `{pad.name}` ({len(fotos)} van {len(paden)} foto's gebruikt"
        f"{overgeslagen}, backend: {gebruikt})."
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
            "Upload foto's in de gewenste huisstijl, of kies een hele map. Qwen3-VL "
            "analyseert wat ze gemeen hebben en slaat dat op als stijlprofiel."
        )
        with gr.Row():
            with gr.Column():
                referenties = gr.File(
                    label="Referentiefoto's",
                    file_count="multiple",
                    file_types=["image"],
                    type="filepath",
                )
                map_upload = gr.File(
                    label="Of upload een hele map",
                    file_count="directory",
                    type="filepath",
                )
                map_pad = gr.Textbox(
                    label="Of plak het pad van een map op deze computer",
                    placeholder=r"C:\Users\...\OneDrive - ...\documents\TVB\licht-referenties",
                    info=f"Submappen tellen mee. Bij meer dan {qb.MAX_REFERENTIES} foto's wordt een verdeelde selectie gebruikt.",
                )
                aantal_fotos = gr.Markdown()
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

    for bron in (referenties, map_upload):
        bron.change(tel_referenties, inputs=[referenties, map_upload, map_pad], outputs=aantal_fotos)
    map_pad.blur(tel_referenties, inputs=[referenties, map_upload, map_pad], outputs=aantal_fotos)
    map_pad.submit(tel_referenties, inputs=[referenties, map_upload, map_pad], outputs=aantal_fotos)

    analyse_knop.click(
        leer_stijl,
        inputs=[referenties, map_upload, map_pad, stijl_naam_in, backend_analyse],
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
