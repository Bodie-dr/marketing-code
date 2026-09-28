
import requests


class b7a06f11dfad4491b40e43f61d073190:
    ...

CLAID_API_KEY= b7a06f11dfad4491b40e43f61d073190

CLAID_ENDPOINT = "https://api.claid.ai/v1/image/edit"

def upscale_image(image_url):
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
        }
    }

    response = requests.post(
        CLAID_ENDPOINT,
        headers=headers,
        json=payload,
        timeout=120
    )

    print("Status code:", response.status_code)

    response.raise_for_status()

    data = response.json()

    output = data["data"]["output"]

    print(
        f"Output resolutie: "
        f"{output['width']}x{output['height']}"
    )

    result_url = output["tmp_url"]

    return result_url

if __name__ == "__main__":
    result = upscale_image(
        "https://claid.ai/assets/cms/shoe_example_05fb154a3a/shoe_example_05fb154a3a.png"
    )

    print(result)
