"""Lokale Gradio-testapp voor de Pixelcut Upscale API."""

import io
import os
import time
import uuid
from pathlib import Path

import gradio as gr
import requests
from dotenv import load_dotenv
from PIL import Image, UnidentifiedImageError

BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent
OUTPUT_DIR = PROJECT_DIR / "outputs" / "pixelcut"
API_URL = "https://api.developer.pixelcut.ai/v1/upscale"
MAX_BYTES = 25_000_000
FORMATS = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}


def upscale(image_path: str | None, scale: int):
    """Verstuur een upload en bewaar het originele API-resultaat lokaal."""
    load_dotenv(PROJECT_DIR / ".env")
    api_key = os.getenv("PIXELCUT_API_KEY", "").strip()
    if not image_path:
        raise gr.Error("Upload eerst een afbeelding.")
    if scale not in (2, 4):
        raise gr.Error("Kies 2x of 4x.")
    if not api_key:
        raise gr.Error("Vul PIXELCUT_API_KEY in het .env-bestand in en herstart de app.")

    source = Path(image_path)
    try:
        if source.stat().st_size > MAX_BYTES:
            raise gr.Error("De afbeelding mag maximaal 25 MB zijn.")
        with Image.open(source) as original:
            width, height = original.size
            mime = FORMATS.get(original.format)
            if not mime:
                raise gr.Error("Gebruik een JPG-, PNG- of WebP-afbeelding.")
            if min(width, height) < 64 or max(width, height) > 6000:
                raise gr.Error("De invoer moet tussen 64 en 6000 pixels per zijde zijn.")
            original.verify()
    except (OSError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
        raise gr.Error("De afbeelding kan niet worden gelezen.") from exc

    started = time.monotonic()
    try:
        with source.open("rb") as upload:
            response = requests.post(
                API_URL,
                headers={"X-API-KEY": api_key, "Accept": "image/*"},
                files={"image": (source.name, upload, mime)},
                data={"scale": str(int(scale))},
                timeout=(15, 180),
            )
    except requests.Timeout as exc:
        raise gr.Error("Pixelcut reageert te langzaam. Controleer je verbruik voordat je opnieuw probeert.") from exc
    except requests.RequestException as exc:
        raise gr.Error("Geen verbinding met Pixelcut. Controleer je internetverbinding.") from exc

    errors = {
        400: "Pixelcut kan deze afbeelding niet verwerken. Controleer formaat en afmetingen.",
        401: "De Pixelcut API-sleutel is ongeldig.",
        403: "Onvoldoende Pixelcut API-credits of geen toegang.",
        429: "Te veel aanvragen. Wacht even voordat je opnieuw probeert.",
    }
    if response.status_code != 200:
        raise gr.Error(errors.get(response.status_code, f"Pixelcut-fout (HTTP {response.status_code})."))

    try:
        with Image.open(io.BytesIO(response.content)) as result:
            result_size = result.size
            extension = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}.get(result.format)
            if not extension:
                raise gr.Error("Pixelcut stuurde een onverwacht afbeeldingsformaat terug.")
            result.verify()
    except (OSError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
        raise gr.Error("Pixelcut stuurde geen geldige afbeelding terug.") from exc

    try:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        output = OUTPUT_DIR / f"upscale_{int(scale)}x_{uuid.uuid4().hex}{extension}"
        output.write_bytes(response.content)
    except OSError as exc:
        raise gr.Error("Het resultaat kon niet worden opgeslagen in de map outputs.") from exc
    status = (
        f"Klaar: {width} x {height} → {result_size[0]} x {result_size[1]} pixels. "
        f"Verwerking: {time.monotonic() - started:.1f} seconden."
    )
    return str(output), str(output), status


def build_app():
    with gr.Blocks(title="Pixelcut Upscale Test") as demo:
        gr.Markdown("# Pixelcut Upscale\nVergroot je afbeelding met de Pixelcut API.")
        gr.Markdown(
            "Upload JPG, PNG of WebP (max. 25 MB). Kies 2x of 4x. "
            "Pixelcut beperkt de uitvoer tot 6000 x 6000 pixels. "
            "Bij klikken op **Upscale** wordt je afbeelding naar Pixelcut verstuurd en worden API-credits gebruikt."
        )
        with gr.Row():
            with gr.Column():
                upload = gr.File(label="Afbeelding uploaden", file_types=[".jpg", ".jpeg", ".png", ".webp"], type="filepath")
                original = gr.Image(label="Origineel", interactive=False)
                scale = gr.Radio(choices=[("2x", 2), ("4x", 4)], value=2, label="Vergroting")
                run = gr.Button("Upscale", variant="primary")
            with gr.Column():
                result = gr.Image(label="Resultaat", interactive=False)
                download = gr.File(label="Download origineel API-resultaat", interactive=False)
                status = gr.Textbox(label="Status", interactive=False)
        upload.change(lambda path: path, inputs=upload, outputs=original, api_name=False)
        run.click(
            lambda: (None, None, "Bezig..."), outputs=[result, download, status], api_name=False
        ).then(
            upscale, inputs=[upload, scale], outputs=[result, download, status],
            concurrency_limit=1, api_name=False,
        ).failure(lambda: "Upscaling mislukt. Zie de foutmelding.", outputs=status, api_name=False)
    return demo


if __name__ == "__main__":
    build_app().queue().launch(server_name="127.0.0.1", inbrowser=True, share=False)
