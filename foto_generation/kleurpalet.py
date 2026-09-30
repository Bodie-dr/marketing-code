"""Haal het echte kleurpalet uit foto's (in plaats van het door een model te laten raden).

Gebruik:
    python foto_generation/kleurpalet.py <map of foto's> [--aantal 6] [--png palet.png]

Werkwijze: van elke foto evenveel pixels nemen (grote foto's wegen niet
zwaarder), omzetten naar de Lab-kleurruimte (afstand ≈ zichtbaar
kleurverschil) en groeperen met k-means. Elk groepsgemiddelde is een
paletkleur; het aandeel is het percentage pixels in die groep.
"""

import argparse
from collections.abc import Sequence

import numpy as np
from PIL import Image, ImageDraw

PIXELS_PER_FOTO = 20_000


# --------------------------------------------------
# Kleurruimtes (sRGB <-> CIE Lab, D65)
# --------------------------------------------------

_RGB_NAAR_XYZ = np.array([
    [0.4124564, 0.3575761, 0.1804375],
    [0.2126729, 0.7151522, 0.0721750],
    [0.0193339, 0.1191920, 0.9503041],
])
_WIT_D65 = np.array([0.95047, 1.0, 1.08883])


def rgb_naar_lab(rgb: np.ndarray) -> np.ndarray:
    """(N, 3) RGB 0-255 -> (N, 3) Lab."""
    c = rgb / 255.0
    lineair = np.where(c > 0.04045, ((c + 0.055) / 1.055) ** 2.4, c / 12.92)
    xyz = lineair @ _RGB_NAAR_XYZ.T / _WIT_D65
    f = np.where(xyz > (6 / 29) ** 3, np.cbrt(xyz), xyz / (3 * (6 / 29) ** 2) + 4 / 29)
    return np.stack([116 * f[:, 1] - 16, 500 * (f[:, 0] - f[:, 1]), 200 * (f[:, 1] - f[:, 2])], axis=1)


def lab_naar_rgb(lab: np.ndarray) -> np.ndarray:
    """(N, 3) Lab -> (N, 3) RGB 0-255 (afgerond en begrensd)."""
    fy = (lab[:, 0] + 16) / 116
    f = np.stack([fy + lab[:, 1] / 500, fy, fy - lab[:, 2] / 200], axis=1)
    xyz = np.where(f > 6 / 29, f ** 3, 3 * (6 / 29) ** 2 * (f - 4 / 29)) * _WIT_D65
    lineair = xyz @ np.linalg.inv(_RGB_NAAR_XYZ).T
    lineair = np.clip(lineair, 0, 1)
    c = np.where(lineair > 0.0031308, 1.055 * lineair ** (1 / 2.4) - 0.055, 12.92 * lineair)
    return np.clip(np.round(c * 255), 0, 255).astype(int)


# --------------------------------------------------
# Palet
# --------------------------------------------------

def _pixels(fotos: Sequence[Image.Image], rng: np.random.Generator) -> np.ndarray:
    delen = []
    for foto in fotos:
        klein = foto.convert("RGB")
        klein.thumbnail((400, 400))
        pixels = np.asarray(klein, dtype=np.float64).reshape(-1, 3)
        if len(pixels) > PIXELS_PER_FOTO:
            pixels = pixels[rng.choice(len(pixels), PIXELS_PER_FOTO, replace=False)]
        delen.append(pixels)
    return np.concatenate(delen)


def _kmeans(punten: np.ndarray, k: int, rng: np.random.Generator, iteraties: int = 30):
    # k-means++: begin met centra die ver uit elkaar liggen.
    centra = [punten[rng.integers(len(punten))]]
    for _ in range(1, k):
        afstand = np.min([((punten - c) ** 2).sum(axis=1) for c in centra], axis=0)
        if afstand.sum() == 0:
            break
        centra.append(punten[rng.choice(len(punten), p=afstand / afstand.sum())])
    centra = np.array(centra)

    for _ in range(iteraties):
        labels = ((punten[:, None, :] - centra[None, :, :]) ** 2).sum(axis=2).argmin(axis=1)
        nieuw = np.array([
            punten[labels == i].mean(axis=0) if np.any(labels == i) else centra[i]
            for i in range(len(centra))
        ])
        if np.allclose(nieuw, centra, atol=0.01):
            break
        centra = nieuw
    return centra, labels


def _groepeer(lab: np.ndarray, aantal: int, totaal: int, soort: str, rng) -> list[dict]:
    if aantal <= 0 or len(lab) == 0:
        return []
    centra, labels = _kmeans(lab, min(aantal, len(lab)), rng)
    aandelen = np.bincount(labels, minlength=len(centra)) / totaal
    palet = [
        {
            "hex": "#{:02X}{:02X}{:02X}".format(*kleur),
            "aandeel": round(float(aandeel), 3),
            "soort": soort,
        }
        for kleur, aandeel in zip(lab_naar_rgb(centra), aandelen)
        if aandeel > 0
    ]
    return sorted(palet, key=lambda kleur: kleur["aandeel"], reverse=True)


# Pixels met minstens deze kleurverzadiging (chroma in Lab) tellen als "gekleurd".
MIN_ACCENT_CHROMA = 16
# Accenten die samen minder dan dit deel van de pixels zijn, zijn ruis.
MIN_ACCENT_AANDEEL = 0.005


def extraheer_palet(
    fotos: Sequence[Image.Image],
    aantal: int = 5,
    accenten: int = 3,
    seed: int = 0,
) -> list[dict]:
    """Hoofdkleuren (grootste vlakken) plus accentkleuren (duidelijk gekleurd).

    Grote grijze vlakken zoals muren en vloeren overheersen anders het palet,
    terwijl juist kleinere verzadigde kleuren (meubels, logo's, planten) de
    huisstijl bepalen. Accenten worden daarom apart gezocht onder alleen de
    gekleurde pixels.

    Geeft [{'hex': '#RRGGBB', 'aandeel': 0.31, 'soort': 'hoofd'|'accent'}, ...];
    'aandeel' is steeds het deel van álle pixels.
    """
    if not fotos:
        raise ValueError("Geen foto's om kleuren uit te halen.")
    rng = np.random.default_rng(seed)
    lab = rgb_naar_lab(_pixels(fotos, rng))

    hoofd = _groepeer(lab, aantal, len(lab), "hoofd", rng)

    chroma = np.hypot(lab[:, 1], lab[:, 2])
    gekleurd = lab[chroma >= MIN_ACCENT_CHROMA]
    accent = []
    if len(gekleurd) / len(lab) >= MIN_ACCENT_AANDEEL:
        accent = [
            kleur for kleur in _groepeer(gekleurd, accenten, len(lab), "accent", rng)
            if kleur["aandeel"] >= MIN_ACCENT_AANDEEL / 2
        ]
    return hoofd + accent


def palet_afbeelding(palet: list[dict], breedte: int = 900, hoogte: int = 140) -> Image.Image:
    """Een strook met blokken, breedte naar aandeel, met de hexcode erin."""
    strook = Image.new("RGB", (breedte, hoogte), "white")
    teken = ImageDraw.Draw(strook)
    x = 0.0
    for kleur in palet:
        w = breedte * kleur["aandeel"] / sum(k["aandeel"] for k in palet)
        teken.rectangle([int(x), 0, int(x + w), hoogte], fill=kleur["hex"])
        r, g, b = (int(kleur["hex"][i:i + 2], 16) for i in (1, 3, 5))
        tekstkleur = "black" if (0.299 * r + 0.587 * g + 0.114 * b) > 140 else "white"
        teken.text((int(x) + 6, hoogte - 34), f"{kleur['hex']}\n{kleur['aandeel']:.0%}", fill=tekstkleur)
        x += w
    return strook


def main() -> None:
    from qwen_backend import verzamel_fotos

    parser = argparse.ArgumentParser(description="Haal het echte kleurpalet uit foto's.")
    parser.add_argument("paden", nargs="+", help="Foto's en/of mappen (submappen tellen mee).")
    parser.add_argument("--aantal", type=int, default=5, help="Aantal hoofdkleuren (standaard 5).")
    parser.add_argument("--accenten", type=int, default=3, help="Aantal accentkleuren (standaard 3).")
    parser.add_argument("--png", help="Sla het palet ook op als afbeelding.")
    arguments = parser.parse_args()

    paden = verzamel_fotos(arguments.paden)
    if not paden:
        parser.error("Geen foto's gevonden.")

    fotos = []
    for pad in paden:
        with Image.open(pad) as foto:
            foto = foto.convert("RGB")
            foto.thumbnail((400, 400))
            fotos.append(foto)

    palet = extraheer_palet(fotos, arguments.aantal, arguments.accenten)
    print(f"Kleurpalet uit {len(fotos)} foto's (percentage = deel van alle pixels):")
    for soort, titel in [("hoofd", "Hoofdkleuren"), ("accent", "Accentkleuren")]:
        print(f"\n  {titel}:")
        for kleur in (k for k in palet if k["soort"] == soort):
            print(f"    {kleur['hex']}  {kleur['aandeel']:6.1%}")

    if arguments.png:
        palet_afbeelding(palet).save(arguments.png)
        print(f"Afbeelding opgeslagen: {arguments.png}")


if __name__ == "__main__":
    main()
