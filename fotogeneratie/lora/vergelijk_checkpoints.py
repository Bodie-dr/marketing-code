"""Stap 5: zet de testbeelden van alle checkpoints naast elkaar om de beste te kiezen.

ai-toolkit maakt elke 'sample_every' stappen testbeelden in
output/<naam>/samples/, met namen als 1727780000_000000250_3.jpg
(tijd _ stap _ promptnummer). Dit script maakt daar één raster van:
één rij per testprompt, één kolom per stap. Zo zie je in één oogopslag waar
vorm, verhoudingen, kleuren en details het best kloppen, en waar het model
gaat overfitten (elk beeld lijkt op een trainingsfoto, of prompt 9 zonder
triggerwoord toont toch het product).

Gebruik (na het downloaden van de samples-map van RunPod):
    python fotogeneratie/lora/vergelijk_checkpoints.py <samples-map>
    python fotogeneratie/lora/vergelijk_checkpoints.py <samples-map> --vanaf 1000 --tegel 320
"""

import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

SAMPLE_PATROON = re.compile(r"(\d+)_(\d+)\.(?:jpg|jpeg|png|webp)$", re.IGNORECASE)


def lees_samples(map_: Path) -> dict[int, dict[int, Path]]:
    """{promptnummer: {stap: pad}}; bij dubbele stap telt het nieuwste bestand."""
    samples: dict[int, dict[int, Path]] = defaultdict(dict)
    for pad in sorted(map_.iterdir()):
        match = SAMPLE_PATROON.search(pad.name)
        if match:
            stap, prompt = int(match.group(1)), int(match.group(2))
            samples[prompt][stap] = pad
    return dict(samples)


def _lettertype(grootte: int):
    try:
        return ImageFont.truetype("arial.ttf", grootte)
    except OSError:
        return ImageFont.load_default()


def maak_raster(
    samples: dict[int, dict[int, Path]],
    tegel: int = 256,
    vanaf: int = 0,
    tot: int | None = None,
) -> Image.Image:
    stappen = sorted({s for per_prompt in samples.values() for s in per_prompt if s >= vanaf and (tot is None or s <= tot)})
    prompts = sorted(samples)
    if not stappen or not prompts:
        raise ValueError("Geen testbeelden gevonden in dit bereik.")
    kop, label = 36, 60
    raster = Image.new("RGB", (label + len(stappen) * tegel, kop + len(prompts) * tegel), "white")
    teken = ImageDraw.Draw(raster)
    letter = _lettertype(18)

    for kolom, stap in enumerate(stappen):
        teken.text((label + kolom * tegel + 8, 8), f"stap {stap}", fill="black", font=letter)
    for rij, prompt in enumerate(prompts):
        y = kop + rij * tegel
        teken.text((8, y + tegel // 2 - 10), f"#{prompt + 1}", fill="black", font=letter)
        for kolom, stap in enumerate(stappen):
            pad = samples[prompt].get(stap)
            if not pad:
                continue
            with Image.open(pad) as beeld:
                klein = beeld.convert("RGB")
                klein.thumbnail((tegel - 4, tegel - 4))
            x = label + kolom * tegel + (tegel - klein.width) // 2
            raster.paste(klein, (x, y + (tegel - klein.height) // 2))
    return raster


def main() -> None:
    parser = argparse.ArgumentParser(description="Raster van ai-toolkit-testbeelden per checkpoint.")
    parser.add_argument("samples", type=Path, help="De map output/<naam>/samples van ai-toolkit.")
    parser.add_argument("--tegel", type=int, default=256, help="Grootte van elk beeld in het raster (px).")
    parser.add_argument("--vanaf", type=int, default=0, help="Alleen stappen vanaf dit nummer.")
    parser.add_argument("--tot", type=int, help="Alleen stappen tot en met dit nummer.")
    parser.add_argument("--uit", type=Path, help="Bestandsnaam (standaard <samples>/../vergelijking.jpg).")
    arguments = parser.parse_args()

    if not arguments.samples.is_dir():
        sys.exit(f"Map niet gevonden: {arguments.samples}")
    samples = lees_samples(arguments.samples)
    raster = maak_raster(samples, arguments.tegel, arguments.vanaf, arguments.tot)
    uit = arguments.uit or arguments.samples.parent / "vergelijking.jpg"
    raster.save(uit, quality=90)
    print(f"{len(samples)} prompts x {raster.width // arguments.tegel} stappen -> {uit}")
    print(
        "Kijk per kolom naar vorm, verhoudingen, kleuren, knoppen en naden. Kies de vroegste\n"
        "stap waar het product klopt; de laatste rij (zonder triggerwoord) mag het product NIET tonen."
    )


if __name__ == "__main__":
    main()
