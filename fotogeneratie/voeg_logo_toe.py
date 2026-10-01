"""Stap 8: zet het TVB-logo op gegenereerde beelden (standaard rechtsonder).

Losstaand van de LoRA: werkt op elke foto. Het logo wordt NIET door het model
gegenereerd (dat gaat vaak mis), maar er na afloop netjes op gezet.

Twee stijlen:
  badge        logo op zijn eigen donkerblauwe vlak; altijd leesbaar (standaard)
  transparant  alleen het beeldmerk en de letters; mooi op donkere/rustige
               plekken, maar witte letters vallen weg op een lichte achtergrond

Gebruik:
    python fotogeneratie/voeg_logo_toe.py <foto of map> [...]
    python fotogeneratie/voeg_logo_toe.py <map> --stijl transparant --breedte 0.12
    python fotogeneratie/voeg_logo_toe.py <map> --positie linksonder --uit <map>

Een eigen logo (bij voorkeur een PNG met transparantie in hoge resolutie):
    python fotogeneratie/voeg_logo_toe.py <map> --logo pad/naar/logo.png
"""

import argparse
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageOps

FOTO_DIR = Path(__file__).resolve().parent
PROJECT_DIR = FOTO_DIR.parent
STANDAARD_LOGO = FOTO_DIR / "assets" / "tvb_logo.jpg"
STANDAARD_UIT = PROJECT_DIR / "outputs" / "met_logo"
FOTO_EXTENSIES = {".jpg", ".jpeg", ".png", ".webp"}
POSITIES = ("rechtsonder", "linksonder", "rechtsboven", "linksboven")


def achtergrondkleur(logo: Image.Image) -> tuple[int, int, int]:
    """De kleur van de hoeken: bij een logo op een effen vlak is dat het vlak."""
    rgb = logo.convert("RGB")
    b, h = rgb.size
    hoeken = [rgb.getpixel(p) for p in ((0, 0), (b - 1, 0), (0, h - 1), (b - 1, h - 1))]
    return tuple(int(np.median([k[i] for k in hoeken])) for i in range(3))


def heeft_transparantie(logo: Image.Image) -> bool:
    return logo.mode in ("RGBA", "LA") and logo.getchannel("A").getextrema()[0] < 255


def maak_transparant(logo: Image.Image, drempel: float = 60.0) -> Image.Image:
    """Haal een effen achtergrond weg, met zachte randen (geen gekartelde pixels)."""
    if heeft_transparantie(logo):
        return logo.convert("RGBA")
    rgb = np.asarray(logo.convert("RGB"), dtype=np.float32)
    achtergrond = np.array(achtergrondkleur(logo), dtype=np.float32)
    afstand = np.linalg.norm(rgb - achtergrond, axis=2)
    alpha = np.clip(afstand / drempel, 0, 1)
    # Kleur 'ontmengen': haal het aandeel achtergrond uit de randpixels.
    veilig = np.maximum(alpha, 1e-3)[..., None]
    kleur = np.clip((rgb - (1 - alpha[..., None]) * achtergrond) / veilig, 0, 255)
    rgba = np.dstack([kleur, alpha * 255]).astype(np.uint8)
    return bijsnijden(Image.fromarray(rgba, "RGBA"))


def bijsnijden(logo: Image.Image) -> Image.Image:
    vak = logo.getchannel("A").point(lambda a: 255 if a > 8 else 0).getbbox()
    return logo.crop(vak) if vak else logo


def maak_badge(logo: Image.Image, rand: float = 0.22) -> Image.Image:
    """Logo op zijn eigen achtergrondvlak met afgeronde hoeken."""
    kleur = achtergrondkleur(logo) if not heeft_transparantie(logo) else (35, 45, 80)
    los = maak_transparant(logo)
    marge = int(min(los.size) * rand)
    b, h = los.width + 2 * marge, los.height + 2 * marge
    badge = Image.new("RGBA", (b, h), (0, 0, 0, 0))
    ImageDraw.Draw(badge).rounded_rectangle((0, 0, b - 1, h - 1), radius=marge, fill=(*kleur, 255))
    badge.alpha_composite(los, (marge, marge))
    return badge


def plaats_logo(
    foto: Image.Image,
    logo: Image.Image,
    positie: str = "rechtsonder",
    breedte: float = 0.15,
    marge: float = 0.03,
    dekking: float = 1.0,
) -> tuple[Image.Image, float]:
    """Zet het logo op de foto. Geeft de foto en de vergrotingsfactor van het logo terug."""
    if positie not in POSITIES:
        raise ValueError(f"Onbekende positie '{positie}'. Kies uit: {', '.join(POSITIES)}")
    doel_b = max(1, round(foto.width * breedte))
    factor = doel_b / logo.width
    doel_h = max(1, round(logo.height * factor))
    geschaald = logo.resize((doel_b, doel_h), Image.LANCZOS)
    if dekking < 1:
        alpha = geschaald.getchannel("A").point(lambda a: round(a * dekking))
        geschaald.putalpha(alpha)

    m = round(min(foto.size) * marge)
    x = foto.width - doel_b - m if positie.startswith("rechts") else m
    y = foto.height - doel_h - m if positie.endswith("onder") else m

    resultaat = foto.convert("RGBA")
    resultaat.alpha_composite(geschaald, (x, y))
    return resultaat, factor


def verzamel(bronnen: list[str]) -> list[Path]:
    paden: list[Path] = []
    for bron in map(Path, bronnen):
        if bron.is_dir():
            paden += sorted(p for p in bron.rglob("*") if p.suffix.lower() in FOTO_EXTENSIES)
        elif bron.suffix.lower() in FOTO_EXTENSIES:
            paden.append(bron)
    return paden


def main() -> None:
    parser = argparse.ArgumentParser(description="Zet het TVB-logo op foto's.")
    parser.add_argument("bron", nargs="+", help="Foto's en/of mappen.")
    parser.add_argument("--logo", type=Path, default=STANDAARD_LOGO, help="Logo-bestand (PNG met transparantie het best).")
    parser.add_argument("--stijl", choices=["badge", "transparant"], default="badge")
    parser.add_argument("--positie", choices=POSITIES, default="rechtsonder")
    parser.add_argument("--breedte", type=float, default=0.15, help="Logobreedte als deel van de fotobreedte (0.15 = 15%%).")
    parser.add_argument("--marge", type=float, default=0.03, help="Afstand tot de rand als deel van de korte zijde.")
    parser.add_argument("--dekking", type=float, default=1.0, help="0-1; lager = doorzichtiger.")
    parser.add_argument("--uit", type=Path, default=STANDAARD_UIT, help="Uitvoermap (standaard outputs/met_logo).")
    arguments = parser.parse_args()

    paden = verzamel(arguments.bron)
    if not paden:
        sys.exit("Geen foto's gevonden.")
    with Image.open(arguments.logo) as bestand:
        bron_logo = bestand.convert("RGBA") if heeft_transparantie(bestand) else bestand.convert("RGB")
    logo = maak_badge(bron_logo) if arguments.stijl == "badge" else maak_transparant(bron_logo)

    arguments.uit.mkdir(parents=True, exist_ok=True)
    grootste_factor = 0.0
    for pad in paden:
        with Image.open(pad) as origineel:
            foto = ImageOps.exif_transpose(origineel)
            resultaat, factor = plaats_logo(
                foto, logo, arguments.positie, arguments.breedte, arguments.marge, arguments.dekking
            )
        grootste_factor = max(grootste_factor, factor)
        doel = arguments.uit / f"{pad.stem}_logo.jpg"
        resultaat.convert("RGB").save(doel, quality=95)
        print(f"{pad.name} -> {doel}")

    if grootste_factor > 1.5:
        print(
            f"\n! Het logo is tot {grootste_factor:.1f}x vergroot en kan wazig ogen. "
            "Gebruik een logo in hoge resolutie (PNG of SVG van marketing) met --logo."
        )


if __name__ == "__main__":
    main()
