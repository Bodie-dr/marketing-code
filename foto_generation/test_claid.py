"""Gradio-test voor Claid.ai upscaling.

Start: python marketing-code/foto_generation/test_claid.py
Dependencies: pip install gradio requests Pillow python-dotenv
Sleutel: CLAID_API_KEY in marketing-code/.env of als omgevingsvariabele.
API-documentatie: https://docs.claid.ai/image-editing-api/upload-api-reference
Resultaten: marketing-code/outputs/claid. Geen automatische betaalde retries.
"""

import io
import json
import os
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

import gradio as gr
import requests
from dotenv import load_dotenv
from PIL import Image, UnidentifiedImageError

BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent
OUTPUT_DIR = PROJECT_DIR / "outputs" / "claid"
API_URL = "https://api.claid.ai/v1/image/edit/upload"
# Lokale limiet voor deze testinterface.
MAX_BYTES = 25_000_000
MODELS = ["smart_enhance", "smart_resize", "photo", "faces", "digital_art"]
FORMATS = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}


def upscale(image_path: str | None, scale: int, model: str = "smart_enhance"):
    """Verstuur een upload en bewaar het originele API-resultaat lokaal."""
    load_dotenv(PROJECT_DIR / ".env")
    api_key = os.getenv("CLAID_API_KEY", "").strip()
    if not image_path:
        raise gr.Error("Upload eerst een afbeelding.")
    if scale not in (2, 4):
        raise gr.Error("Kies 2x of 4x.")
    if model not in MODELS:
        raise gr.Error("Kies een geldig Claid.ai-model.")
    if not api_key:
        raise gr.Error("Vul CLAID_API_KEY in het .env-bestand in en herstart de app.")

    source = Path(image_path)
    try:
        if source.stat().st_size > MAX_BYTES:
            raise gr.Error("De afbeelding mag maximaal 25 MB zijn.")
        with Image.open(source) as original:
            width, height = original.size
            mime = FORMATS.get(original.format)
            if not mime:
                raise gr.Error("Gebruik een JPG-, PNG- of WebP-afbeelding.")
            original.verify()
    except (OSError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
        raise gr.Error("De afbeelding kan niet worden gelezen.") from exc

    payload = {
        "operations": {
            "restorations": {"upscale": model},
            "resizing": {"width": f"{int(scale) * 100}%", "height": f"{int(scale) * 100}%", "fit": "bounds"},
        },
        "output": {"format": "png"},
    }
    started = time.monotonic()
    try:
        with source.open("rb") as upload:
            response = requests.post(
                API_URL,
                headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
                files={
                    "file": (source.stem, upload, mime),
                    "data": (None, json.dumps(payload), "application/json"),
                },
                timeout=(15, 180),
            )
    except requests.Timeout as exc:
        raise gr.Error("Claid.ai reageert te langzaam. Controleer je verbruik voordat je opnieuw probeert.") from exc
    except requests.RequestException as exc:
        raise gr.Error("Geen verbinding met Claid.ai. Controleer je internetverbinding.") from exc

    errors = {
        400: "Claid.ai kan deze afbeelding niet verwerken. Controleer formaat en afmetingen.",
        401: "De Claid.ai API-sleutel is ongeldig.",
        402: "Geen Claid.ai API-credits meer beschikbaar.",
        403: "Geen toegang tot deze Claid.ai-bewerking.",
        422: "Claid.ai accepteert deze afbeelding of instellingen niet. Probeer een kleinere afbeelding.",
        429: "Te veel aanvragen. Wacht even voordat je opnieuw probeert.",
    }
    if response.status_code != 200:
        raise gr.Error(errors.get(response.status_code, f"Claid.ai-fout (HTTP {response.status_code})."))

    try:
        result_url = response.json()["data"]["output"]["tmp_url"]
        parsed = urlparse(result_url) if isinstance(result_url, str) else None
        if not parsed or parsed.scheme != "https" or not parsed.hostname:
            raise ValueError("Ongeldige resultaat-URL")
    except (ValueError, KeyError, TypeError) as exc:
        raise gr.Error("Claid.ai stuurde geen geldige downloadlink terug.") from exc

    # De tijdelijke download-URL heeft geen API-sleutel nodig.
    try:
        download_response = requests.get(result_url, timeout=(15, 120))
        download_response.raise_for_status()
    except requests.RequestException as exc:
        raise gr.Error("De bewerking is klaar, maar downloaden is mislukt. Opnieuw upscalen kan extra credits kosten.") from exc
    result_bytes = download_response.content
    try:
        with Image.open(io.BytesIO(result_bytes)) as result:
            result_size = result.size
            extension = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}.get(result.format)
            if not extension:
                raise gr.Error("Claid.ai stuurde een onverwacht afbeeldingsformaat terug.")
            result.verify()
    except (OSError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
        raise gr.Error("Claid.ai stuurde geen geldige afbeelding terug.") from exc

    try:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        output = OUTPUT_DIR / f"upscale_{int(scale)}x_{uuid.uuid4().hex}{extension}"
        output.write_bytes(result_bytes)
    except OSError as exc:
        raise gr.Error("Het resultaat kon niet worden opgeslagen in de map outputs.") from exc
    status = (
        f"Klaar: {width} x {height} → {result_size[0]} x {result_size[1]} pixels. "
        f"Verwerking: {time.monotonic() - started:.1f} seconden."
    )
    return str(output), str(output), status


def build_app():
    with gr.Blocks(title="Claid.ai Upscale Test") as demo:
        gr.Markdown("# Claid.ai Upscale\nVergroot je afbeelding met de Claid.ai API.")
        gr.Markdown(
            "Upload JPG, PNG of WebP (testlimiet: 25 MB). Kies 2x of 4x en een model. "
            "Bij klikken op **Upscale** wordt je afbeelding naar Claid.ai verstuurd en worden API-credits gebruikt."
        )
        with gr.Row():
            with gr.Column():
                upload = gr.File(label="Afbeelding uploaden", file_types=[".jpg", ".jpeg", ".png", ".webp"], type="filepath")
                original = gr.Image(label="Origineel", interactive=False)
                scale = gr.Radio(choices=[("2x", 2), ("4x", 4)], value=2, label="Vergroting")
                model = gr.Dropdown(choices=MODELS, value="smart_enhance", label="Upscale-model")
                run = gr.Button("Upscale", variant="primary")
            with gr.Column():
                result = gr.Image(label="Resultaat", interactive=False)
                download = gr.File(label="Download origineel API-resultaat", interactive=False)
                status = gr.Textbox(label="Status", interactive=False)
        upload.change(lambda path: path, inputs=upload, outputs=original, api_name=False)
        run.click(
            lambda: (None, None, "Bezig..."), outputs=[result, download, status], api_name=False
        ).then(
            upscale, inputs=[upload, scale, model], outputs=[result, download, status],
            concurrency_limit=1, api_name=False,
        ).failure(lambda: "Upscaling mislukt. Zie de foutmelding.", outputs=status, api_name=False)
    return demo


if __name__ == "__main__":
    build_app().queue().launch(server_name="127.0.0.1", inbrowser=True, share=False)
