"""Maak een LoRA-trainingsset met automatische captions (formaat ai-toolkit).

Voor elke foto komt er in de uitvoermap een kopie plus een .txt met dezelfde
naam. De caption beschrijft alleen de INHOUD en begint met het triggerwoord:

    tvbstijl, an office lounge with two high-backed booth sofas around a table ...

Stijlwoorden (licht, sfeer, kleurbewerking, camera) horen er niet in: de
LoRA moet de stijl juist aan het triggerwoord koppelen. Qwen krijgt die
opdracht, en een filter haalt eventuele stijlwoorden er daarna alsnog uit.

Gebruik:
    python fotogeneratie/maak_captions.py <map met stijlfoto's> --trigger tvbstijl
    python fotogeneratie/maak_captions.py <map> --trigger tvbstijl --uit <map> --opnieuw

Bestaande captions worden overgeslagen (scheelt API-kosten); pas ze gerust
met de hand aan, en gebruik --opnieuw alleen om alles opnieuw te laten maken.
"""

import argparse
import re
from pathlib import Path

from PIL import Image

import qwen_backend as qb


CAPTION_INSTRUCTIE = """Describe this image as a caption for training an image model.

Describe ONLY the content: the type of space or scene, the objects and
furniture, any people and what they do, their positions, and the framing
(for example "wide shot from the entrance" or "close-up of a table").

Do NOT describe the photographic style: no lighting or light colour, no mood
or atmosphere, no colour grading, no film grain, sharpness, camera, lens,
depth of field or quality words.

Write one or two plain sentences in English, at most 60 words. No lists,
no quotes, no introduction such as "This image shows"."""

# Woorden en zinsdelen die stijl beschrijven in plaats van inhoud. Langste
# eerst, zodat "soft natural lighting" vóór "lighting" wordt weggehaald.
STIJLWOORDEN = sorted(
    [
        "golden hour", "blue hour", "soft natural lighting", "soft natural light",
        "natural lighting", "natural light", "soft lighting", "soft light",
        "warm lighting", "warm light", "cool lighting", "cool light",
        "ambient lighting", "ambient light", "dramatic lighting", "studio lighting",
        "diffused light", "backlit", "backlighting", "well-lit", "well lit", "brightly lit",
        "dimly lit", "high contrast", "low contrast", "shallow depth of field",
        "depth of field", "bokeh", "film grain", "grainy", "color grading",
        "colour grading", "color graded", "colour graded", "desaturated", "saturated",
        "muted tones", "muted colors", "muted colours", "warm tones", "cool tones",
        "earthy tones", "pastel tones", "moody", "cinematic", "atmospheric",
        "atmosphere", "ambience", "ambiance", "cozy", "cosy", "inviting", "serene",
        "calm", "tranquil", "vibrant", "dramatic", "aesthetic", "stunning",
        "beautiful", "photorealistic", "realistic", "high quality", "high-quality",
        "professional photograph", "professional photo", "a photograph of",
        "a photo of", "photograph of", "photo of", "this image shows", "the image shows",
        "hdr", "4k", "8k", "sharp focus", "in focus", "blurry", "blurred",
    ],
    key=lambda woord: len(woord),
    reverse=True,
)


def filter_stijlwoorden(caption: str, extra: list[str] | None = None) -> str:
    """Haal stijlwoorden weg en ruim de leestekens op die daarna overblijven."""
    alle_woorden: list[str] = [*STIJLWOORDEN, *(extra or [])]
    woorden = sorted(alle_woorden, key=len, reverse=True)
    patroon = r"\b(?:" + "|".join(re.escape(w) for w in woorden) + r")\b"
    tekst = re.sub(patroon, "", caption, flags=re.IGNORECASE)

    tekst = re.sub(r"\b(with|and|in|under|of|a|an)\s+(?=[,.;]|$)", "", tekst, flags=re.IGNORECASE)
    tekst = re.sub(r"\s+([,.;])", r"\1", tekst)        # geen spatie vóór leesteken
    tekst = re.sub(r"([,;])(\s*[,;.])+", r"\1", tekst)  # dubbele leestekens
    tekst = re.sub(r"\s{2,}", " ", tekst)
    tekst = re.sub(r"^[\s,;.]+|[\s,;]+$", "", tekst)
    tekst = re.sub(r"\b(a)\s+(?=[aeiou])", r"\1n ", tekst, flags=re.IGNORECASE)  # "a office" -> "an office"
    if tekst and caption.rstrip().endswith(".") and not tekst.endswith("."):
        tekst += "."
    return tekst[:1].lower() + tekst[1:] if tekst else tekst


def maak_caption(ruw: str, trigger: str, extra: list[str] | None = None) -> str:
    tekst = " ".join(ruw.strip().strip('"').split())
    return f"{trigger}, {filter_stijlwoorden(tekst, extra)}"


def doelnamen(paden: list[Path]) -> dict[Path, str]:
    """Unieke bestandsnaam per foto, ook als submappen dezelfde namen bevatten."""
    gebruikt: set[str] = set()
    namen = {}
    for pad in paden:
        naam, teller = pad.stem, 2
        while naam.casefold() in gebruikt:
            naam, teller = f"{pad.stem}_{teller}", teller + 1
        gebruikt.add(naam.casefold())
        namen[pad] = naam
    return namen


def verwerk(
    bron: list[str],
    trigger: str,
    uitmap: Path,
    backend: str | None = None,
    max_zijde: int = 2048,
    opnieuw: bool = False,
    extra_stijlwoorden: list[str] | None = None,
) -> dict[str, int]:
    paden = qb.verzamel_fotos(bron)
    if not paden:
        raise ValueError("Geen foto's gevonden.")
    uitmap.mkdir(parents=True, exist_ok=True)
    gekozen = qb.kies_backend(backend)
    analyseer = qb._analyseer_lokaal if gekozen == "lokaal" else qb._analyseer_cloud
    telling = {"gemaakt": 0, "overgeslagen": 0, "mislukt": 0}

    print(f"{len(paden)} foto's -> {uitmap} (backend: {gekozen}, trigger: '{trigger}')")
    for nummer, (pad, naam) in enumerate(doelnamen(paden).items(), start=1):
        foto_uit = uitmap / f"{naam}.jpg"
        caption_uit = uitmap / f"{naam}.txt"
        if caption_uit.exists() and not opnieuw:
            telling["overgeslagen"] += 1
            print(f"[{nummer}/{len(paden)}] bestaat al: {caption_uit.name}")
            continue
        try:
            with Image.open(pad) as foto:
                # Trainen gebeurt op ±1024 px; grotere kopieën kosten alleen schijfruimte.
                klein = qb.verklein(foto, max_zijde)
            caption = maak_caption(analyseer([klein], CAPTION_INSTRUCTIE), trigger, extra_stijlwoorden)
            klein.save(foto_uit, format="JPEG", quality=95)
            caption_uit.write_text(caption + "\n", encoding="utf-8")
            telling["gemaakt"] += 1
            print(f"[{nummer}/{len(paden)}] {foto_uit.name}: {caption}")
        except Exception as fout:
            telling["mislukt"] += 1
            print(f"[{nummer}/{len(paden)}] MISLUKT {pad.name}: {fout}")
    return telling


def main() -> None:
    parser = argparse.ArgumentParser(description="Maak automatisch captions voor LoRA-training.")
    parser.add_argument("bron", nargs="+", help="Map(pen) en/of foto's met de stijlfoto's.")
    parser.add_argument("--trigger", required=True, help="Triggerwoord, bijv. 'tvbstijl' (uniek, geen bestaand woord).")
    parser.add_argument("--uit", type=Path, help="Uitvoermap (standaard outputs/lora_dataset/<trigger>).")
    parser.add_argument("--backend", choices=["auto", "cloud", "lokaal"], default=None)
    parser.add_argument("--max-zijde", type=int, default=2048, help="Langste zijde van de kopieën.")
    parser.add_argument("--opnieuw", action="store_true", help="Bestaande captions overschrijven.")
    parser.add_argument("--extra-stijlwoord", action="append", default=[], help="Extra woord om weg te filteren (herhaalbaar).")
    arguments = parser.parse_args()

    uitmap = arguments.uit or qb.OUTPUT_DIR.parent / "lora_dataset" / arguments.trigger
    telling = verwerk(
        arguments.bron,
        arguments.trigger.strip(),
        uitmap,
        backend=arguments.backend,
        max_zijde=arguments.max_zijde,
        opnieuw=arguments.opnieuw,
        extra_stijlwoorden=arguments.extra_stijlwoord,
    )
    print(
        f"\nKlaar: {telling['gemaakt']} gemaakt, {telling['overgeslagen']} overgeslagen, "
        f"{telling['mislukt']} mislukt. Loop de .txt-bestanden even na vóór het trainen."
    )


if __name__ == "__main__":
    main()
