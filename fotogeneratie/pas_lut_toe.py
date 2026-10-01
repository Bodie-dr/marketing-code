"""Stap 7: geef gegenereerde beelden de vaste TVB-kleurstijl met een 3D-LUT (.cube).

Een LUT is de eenvoudigste manier om product-LoRA en huisstijl te combineren:
de LoRA zorgt voor het juiste product, de LUT voor de vaste kleurbewerking.
Een .cube-bestand exporteer je uit Lightroom, Photoshop, DaVinci Resolve of
Capture One (een 'look' of 'preset' als 3D LUT, bijvoorbeeld 33x33x33).

Gebruik:
    python fotogeneratie/pas_lut_toe.py <foto of map> [...] --lut tvb_stijl.cube
    python fotogeneratie/pas_lut_toe.py <map> --lut tvb_stijl.cube --sterkte 0.7

--sterkte mengt met het origineel: 1 = volledige LUT, 0.5 = half.
Resultaten komen standaard in outputs/lut/.
"""

import argparse
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

PROJECT_DIR = Path(__file__).resolve().parent.parent
STANDAARD_UIT = PROJECT_DIR / "outputs" / "lut"
FOTO_EXTENSIES = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff"}


def lees_cube(pad: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Lees een 3D .cube-LUT. Geeft (tabel[b, g, r, 3], domein_min, domein_max)."""
    grootte = None
    domein_min = np.zeros(3, dtype=np.float32)
    domein_max = np.ones(3, dtype=np.float32)
    waarden: list[list[float]] = []
    for regel in pad.read_text(encoding="utf-8", errors="replace").splitlines():
        regel = regel.strip()
        if not regel or regel.startswith("#"):
            continue
        sleutel, *rest = regel.split()
        sleutel = sleutel.upper()
        if sleutel == "LUT_3D_SIZE":
            grootte = int(rest[0])
        elif sleutel == "LUT_1D_SIZE":
            raise ValueError("Dit is een 1D-LUT; exporteer een 3D-LUT (.cube).")
        elif sleutel == "DOMAIN_MIN":
            domein_min = np.array(rest[:3], dtype=np.float32)
        elif sleutel == "DOMAIN_MAX":
            domein_max = np.array(rest[:3], dtype=np.float32)
        elif sleutel == "TITLE":
            continue
        else:
            try:
                waarden.append([float(v) for v in regel.split()[:3]])
            except ValueError:
                continue  # onbekend sleutelwoord: overslaan
    if not grootte:
        raise ValueError(f"{pad.name}: LUT_3D_SIZE ontbreekt.")
    if len(waarden) != grootte**3:
        raise ValueError(f"{pad.name}: {len(waarden)} waarden, verwacht {grootte**3}.")
    # In .cube loopt rood het snelst, dan groen, dan blauw.
    tabel = np.array(waarden, dtype=np.float32).reshape(grootte, grootte, grootte, 3)
    return tabel, domein_min, domein_max


def pas_toe(foto: Image.Image, tabel: np.ndarray, domein_min, domein_max, sterkte: float = 1.0) -> Image.Image:
    """Trilineaire interpolatie in de LUT, per pixel."""
    rgb = np.asarray(foto.convert("RGB"), dtype=np.float32) / 255
    n = tabel.shape[0]
    genormaliseerd = (rgb - domein_min) / np.maximum(domein_max - domein_min, 1e-6)
    pos = np.clip(genormaliseerd, 0, 1) * (n - 1)
    laag = np.floor(pos).astype(np.int32)
    hoog = np.minimum(laag + 1, n - 1)
    f = pos - laag

    r0, g0, b0 = laag[..., 0], laag[..., 1], laag[..., 2]
    r1, g1, b1 = hoog[..., 0], hoog[..., 1], hoog[..., 2]
    fr, fg, fb = f[..., 0:1], f[..., 1:2], f[..., 2:3]

    def t(b, g, r):
        return tabel[b, g, r]

    c00 = t(b0, g0, r0) * (1 - fr) + t(b0, g0, r1) * fr
    c01 = t(b0, g1, r0) * (1 - fr) + t(b0, g1, r1) * fr
    c10 = t(b1, g0, r0) * (1 - fr) + t(b1, g0, r1) * fr
    c11 = t(b1, g1, r0) * (1 - fr) + t(b1, g1, r1) * fr
    c0 = c00 * (1 - fg) + c01 * fg
    c1 = c10 * (1 - fg) + c11 * fg
    uit = c0 * (1 - fb) + c1 * fb

    uit = rgb * (1 - sterkte) + uit * sterkte
    return Image.fromarray((np.clip(uit, 0, 1) * 255 + 0.5).astype(np.uint8), "RGB")


def verzamel(bronnen: list[str]) -> list[Path]:
    paden: list[Path] = []
    for bron in map(Path, bronnen):
        if bron.is_dir():
            paden += sorted(p for p in bron.rglob("*") if p.suffix.lower() in FOTO_EXTENSIES)
        elif bron.suffix.lower() in FOTO_EXTENSIES:
            paden.append(bron)
    return paden


def main() -> None:
    parser = argparse.ArgumentParser(description="Pas een 3D-LUT (.cube) toe op foto's.")
    parser.add_argument("bron", nargs="+", help="Foto's en/of mappen.")
    parser.add_argument("--lut", type=Path, required=True, help="Het .cube-bestand met de TVB-stijl.")
    parser.add_argument("--sterkte", type=float, default=1.0, help="0-1, mengt met het origineel.")
    parser.add_argument("--uit", type=Path, default=STANDAARD_UIT, help="Uitvoermap (standaard outputs/lut).")
    arguments = parser.parse_args()

    paden = verzamel(arguments.bron)
    if not paden:
        sys.exit("Geen foto's gevonden.")
    tabel, domein_min, domein_max = lees_cube(arguments.lut)
    arguments.uit.mkdir(parents=True, exist_ok=True)
    for pad in paden:
        with Image.open(pad) as origineel:
            resultaat = pas_toe(ImageOps.exif_transpose(origineel), tabel, domein_min, domein_max, arguments.sterkte)
        doel = arguments.uit / f"{pad.stem}_{arguments.lut.stem}.jpg"
        resultaat.save(doel, quality=95)
        print(f"{pad.name} -> {doel}")


if __name__ == "__main__":
    main()
