import os
import requests

CLAID_API_KEY = os.getenv("CLAID_API_KEY")

CLAID_API_URL = "https://api.claid.ai/v1-beta1/image/edit"


def upscale_image(image_url: str) -> str:
    """
    Upscales een afbeelding met Claid.ai.

    Args:
        image_url: Publiek bereikbare URL van de afbeelding.

    Returns:
        URL van de geupscalede afbeelding.
    """

    if not CLAID_API_KEY:
        raise ValueError(
            "CLAID_API_KEY ontbreekt. Voeg deze toe aan je environment variables."
        )

    headers = {
        "Authorization": f"Bearer {CLAID_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "input": image_url,
        "operations": {
            "restorations": {
                "upscale": "smart_enhance"
            }
        },
        "output": {
            "format": "png"
        }
    }

    response = requests.post(
        CLAID_API_URL,
        headers=headers,
        json=payload,
        timeout=120
    )

    response.raise_for_status()

    data = response.json()

    print("Claid response:", data)

    # Pas dit eventueel aan op basis van de response
    output_url = data["data"]["output"]["tmp_url"]

    return output_url


if __name__ == "__main__":
    image_url = "https://example.com/mijn-afbeelding.jpg"

    try:
        result_url = upscale_image(image_url)

        print("Upscaling gelukt!")
        print("Nieuwe afbeelding:", result_url)

    except requests.exceptions.RequestException as error:
        print("Claid API-fout:", error)

    except Exception as error:
        print("Fout:", error)