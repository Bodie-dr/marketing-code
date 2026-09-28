import os
from pathlib import Path

import requests
from dotenv import load_dotenv

# ============================================================
# .ENV LADEN
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parent.parent

ENV_PATH = PROJECT_ROOT / ".env"

load_dotenv(ENV_PATH)

# ============================================================
# PIXELCUT CONFIGURATIE
# ============================================================

PIXELCUT_API_KEY = os.getenv("PIXELCUT_API_KEY")

PIXELCUT_ENDPOINT = (
    "https://api.developer.pixelcut.ai/v1/upscale"
)

# ============================================================
# CONTROLE
# ============================================================

def check_configuration():

    if not PIXELCUT_API_KEY:
        raise ValueError(
            "PIXELCUT_API_KEY ontbreekt.\n"
            f"Gezochte .env locatie: {ENV_PATH}"
        )

# ============================================================
# IMAGE UPSCALEN
# ============================================================

def upscale_image_url(
    image_url,
    scale=2
):
    """
    Upscale een publiek bereikbare afbeelding
    met Pixelcut.

    scale:
        2 = 2x
        4 = 4x
    """

    check_configuration()

    if not image_url:
        raise ValueError(
            "Geen image URL opgegeven."
        )

    if scale not in (2, 4):
        raise ValueError(
            "Scale moet 2 of 4 zijn."
        )

    headers = {
        "X-API-KEY": PIXELCUT_API_KEY,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    payload = {
        "image_url": image_url,
        "scale": scale,
    }

    try:

        response = requests.post(
            PIXELCUT_ENDPOINT,
            headers=headers,
            json=payload,
            timeout=120,
        )

        # Probeer foutmelding netjes uit te lezen
        if not response.ok:

            try:
                error_data = response.json()

            except ValueError:
                error_data = response.text

            raise RuntimeError(
                f"Pixelcut API fout "
                f"({response.status_code}): "
                f"{error_data}"
            )

        data = response.json()

        result_url = data.get(
            "result_url"
        )

        if not result_url:
            raise RuntimeError(
                "Pixelcut gaf geen result_url terug."
            )

        return result_url

    except requests.RequestException as error:

        raise RuntimeError(
            "Verbindingsfout met Pixelcut: "
            f"{error}"
        ) from error

# ============================================================
# TEST
# ============================================================

if __name__ == "__main__":

    print(
        f".env locatie: {ENV_PATH}"
    )

    print(
        f"API-key geladen: "
        f"{bool(PIXELCUT_API_KEY)}"
    )

    test_url = (
        "https://api.claid.ai/v1/image/edit/upload"
    )

    result = upscale_image_url(
        test_url,
        scale=2
    )

    print(
        f"Resultaat: {result}"
    )
