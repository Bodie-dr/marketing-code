"""Stap 1: kies 30-60 gevarieerde foto's uit een grote map voor een product-LoRA.

Wat het script doet:
  1. laat onleesbare en te kleine foto's weg (korte zijde < 768 px)
  2. laat wazige foto's weg (veel minder scherp dan de rest van de map)
  3. houdt van bijna-dubbele foto's alleen de scherpste
  4. kiest uit wat overblijft een zo gevarieerd mogelijke set (compositie,
     kleur, licht en beeldverhouding), te beginnen met de scherpste foto
  5. kopieert de keuze naar de uitvoermap en schrijft een rapport.csv met per
     foto de reden (gekozen, wazig, dubbel van ..., te klein, niet gekozen)

Het script kijkt alleen naar pixels: loop de keuze altijd even na. Zorg zelf
dat er verschillende hoeken (voor, zij, achter, boven, schuin), afstanden
(geheel en close-ups) en omgevingen tussen zitten; ruil foto's gerust om.

Gebruik:
    python fotogeneratie/lora/selecteer_fotos.py <map met productfoto's>
    python fotogeneratie/lora/selecteer_fotos.py <map> --aantal 40 --uit <map>
    python fotogeneratie/lora/selecteer_fotos.py <map> --droog     # alleen rapport, niets kopiëren
"""

import argparse
import csv
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

PROJECT_DIR = Path(__file__).resolve().parents[2]
STANDAARD_UIT = PROJECT_DIR / "outputs" / "lora_selectie"

FOTO_EXTENSIES = {".jpg", ".jpeg", ".png", ".webp"}
MIN_KORTE_ZIJDE = 768
AANTAL_MIN, AANTAL_MAX = 30, 60
# Een foto is 'wazig' als hij minder dan deze fractie van de mediane scherpte heeft.
WAZIG_FACTOR = 0.35
# Verschil in bits (van 64) waaronder twee foto's als bijna-dubbel gelden.
DUBBEL_DREMPEL = 6


@dataclass
class Foto:
    pad: Path
    breedte: int = 0
    hoogte: int = 0
    scherpte: float = 0.0
    dhash: int = 0
    kenmerken: np.ndarray = field(default_factory=lambda: np.zeros(0))
    status: str = ""
    reden: str = ""


def verzamel(bron: Path) -> list[Path]:
    return sorted(p for p in bron.rglob("*") if p.is_file() and p.suffix.lower() in FOTO_EXTENSIES)


def scherpte(grijs: np.ndarray) -> float:
    """Variantie van de Laplace-filter: hoe hoger, hoe meer scherpe randen."""
    g = grijs.astype(np.float32)
    lap = -4 * g[1:-1, 1:-1] + g[:-2, 1:-1] + g[2:, 1:-1] + g[1:-1, :-2] + g[1:-1, 2:]
    return float(lap.var())


def bereken_dhash(grijs_beeld: Image.Image) -> int:
    klein = np.asarray(grijs_beeld.resize((9, 8), Image.LANCZOS), dtype=np.int16)
    bits = (klein[:, :-1] > klein[:, 1:]).flatten()
    return int("".join("1" if b else "0" for b in bits), 2)


def bits_verschil(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def kenmerken(beeld: Image.Image) -> np.ndarray:
    """Kleine vector voor 'hoe verschillend zijn twee foto's': compositie, kleur, licht, vorm."""
    compositie = np.asarray(beeld.convert("L").resize((8, 8), Image.BILINEAR), dtype=np.float32).flatten() / 255
    hsv = np.asarray(beeld.convert("RGB").resize((64, 64)).convert("HSV"), dtype=np.float32) / 255
    kleur = np.concatenate([
        np.histogram(hsv[..., 0], bins=8, range=(0, 1), weights=hsv[..., 1])[0],
        np.histogram(hsv[..., 2], bins=8, range=(0, 1))[0],
    ]).astype(np.float32)
    kleur /= max(float(kleur.sum()), 1e-6)
    verhouding = np.array([np.log(beeld.width / beeld.height)], dtype=np.float32)
    return np.concatenate([compositie, kleur * 4, verhouding])


def analyseer(pad: Path) -> Foto:
    foto = Foto(pad)
    try:
        with Image.open(pad) as origineel:
            beeld = ImageOps.exif_transpose(origineel).convert("RGB")
    except Exception as fout:
        foto.status, foto.reden = "afgekeurd", f"onleesbaar ({fout})"
        return foto
    foto.breedte, foto.hoogte = beeld.size
    if min(beeld.size) < MIN_KORTE_ZIJDE:
        foto.status, foto.reden = "afgekeurd", f"te klein ({foto.breedte}x{foto.hoogte})"
        return foto
    # Scherpte op een vaste maat meten, zodat grote en kleine foto's vergelijkbaar zijn.
    werk = beeld.copy()
    werk.thumbnail((1024, 1024))
    grijs = werk.convert("L")
    foto.scherpte = scherpte(np.asarray(grijs))
    foto.dhash = bereken_dhash(grijs)
    foto.kenmerken = kenmerken(werk)
    return foto


def kies_gevarieerd(kandidaten: list[Foto], aantal: int) -> list[Foto]:
    """Farthest-point sampling: steeds de foto die het meest verschilt van wat al gekozen is."""
    if len(kandidaten) <= aantal:
        return list(kandidaten)
    matrix = np.stack([f.kenmerken for f in kandidaten])
    start = int(np.argmax([f.scherpte for f in kandidaten]))
    gekozen = [start]
    afstand = np.linalg.norm(matrix - matrix[start], axis=1)
    while len(gekozen) < aantal:
        volgende = int(np.argmax(afstand))
        gekozen.append(volgende)
        afstand = np.minimum(afstand, np.linalg.norm(matrix - matrix[volgende], axis=1))
    return [kandidaten[i] for i in gekozen]


def selecteer(fotos: list[Foto], aantal: int) -> list[Foto]:
    bruikbaar = [f for f in fotos if not f.status]
    if bruikbaar:
        mediaan = float(np.median([f.scherpte for f in bruikbaar]))
        for f in bruikbaar:
            if f.scherpte < WAZIG_FACTOR * mediaan:
                f.status, f.reden = "afgekeurd", f"wazig (scherpte {f.scherpte:.0f}, mediaan {mediaan:.0f})"

    # Bijna-dubbelen: de scherpste van elke groep blijft.
    uniek: list[Foto] = []
    for f in sorted((f for f in bruikbaar if not f.status), key=lambda f: -f.scherpte):
        dubbel_van = next((u for u in uniek if bits_verschil(u.dhash, f.dhash) <= DUBBEL_DREMPEL), None)
        if dubbel_van:
            f.status, f.reden = "afgekeurd", f"bijna-dubbel van {dubbel_van.pad.name}"
        else:
            uniek.append(f)

    gekozen = kies_gevarieerd(uniek, aantal)
    gekozen_ids = {id(f) for f in gekozen}
    for f in uniek:
        if id(f) in gekozen_ids:
            f.status, f.reden = "gekozen", ""
        else:
            f.status, f.reden = "niet gekozen", "lijkt op een gekozen foto"
    return gekozen


def kopieer(gekozen: list[Foto], uitmap: Path) -> None:
    uitmap.mkdir(parents=True, exist_ok=True)
    gebruikt: set[str] = set()
    for f in gekozen:
        naam, teller = f.pad.name, 2
        while naam.casefold() in gebruikt or (uitmap / naam).exists():
            naam, teller = f"{f.pad.stem}_{teller}{f.pad.suffix}", teller + 1
        gebruikt.add(naam.casefold())
        shutil.copy2(f.pad, uitmap / naam)


def schrijf_rapport(fotos: list[Foto], pad: Path) -> None:
    pad.parent.mkdir(parents=True, exist_ok=True)
    volgorde = {"gekozen": 0, "niet gekozen": 1, "afgekeurd": 2}
    with pad.open("w", newline="", encoding="utf-8") as bestand:
        schrijver = csv.writer(bestand, delimiter=";")
        schrijver.writerow(["bestand", "status", "reden", "breedte", "hoogte", "scherpte"])
        for f in sorted(fotos, key=lambda f: (volgorde.get(f.status, 3), f.pad.name)):
            schrijver.writerow([f.pad.name, f.status, f.reden, f.breedte, f.hoogte, f"{f.scherpte:.0f}"])


def main() -> None:
    parser = argparse.ArgumentParser(description="Kies gevarieerde, scherpe foto's voor een product-LoRA.")
    parser.add_argument("bron", type=Path, help="Map met alle productfoto's (submappen tellen mee).")
    parser.add_argument("--aantal", type=int, default=45, help=f"Hoeveel foto's ({AANTAL_MIN}-{AANTAL_MAX}, standaard 45).")
    parser.add_argument("--uit", type=Path, help="Uitvoermap (standaard outputs/lora_selectie/<bronmap>).")
    parser.add_argument("--droog", action="store_true", help="Alleen het rapport maken, niets kopiëren.")
    arguments = parser.parse_args()

    if not arguments.bron.is_dir():
        sys.exit(f"Map niet gevonden: {arguments.bron}")
    if not AANTAL_MIN <= arguments.aantal <= AANTAL_MAX:
        print(f"! Advies is {AANTAL_MIN}-{AANTAL_MAX} foto's; je vroeg er {arguments.aantal}.")

    paden = verzamel(arguments.bron)
    if not paden:
        sys.exit("Geen foto's gevonden (.jpg, .jpeg, .png, .webp).")
    print(f"{len(paden)} foto's analyseren...")
    fotos = [analyseer(p) for p in paden]
    gekozen = selecteer(fotos, arguments.aantal)

    uitmap = arguments.uit or STANDAARD_UIT / arguments.bron.name
    if not arguments.droog:
        kopieer(gekozen, uitmap)
    schrijf_rapport(fotos, uitmap / "rapport.csv")

    telling = {s: sum(f.status == s for f in fotos) for s in ("gekozen", "niet gekozen", "afgekeurd")}
    print(f"\n{telling['gekozen']} gekozen, {telling['niet gekozen']} niet gekozen, {telling['afgekeurd']} afgekeurd.")
    for f in fotos:
        if f.status == "afgekeurd":
            print(f"  x {f.pad.name}: {f.reden}")
    if len(gekozen) < AANTAL_MIN:
        print(f"\n! Maar {len(gekozen)} bruikbare foto's; advies is minimaal {AANTAL_MIN}.")
    wat = "Rapport" if arguments.droog else "Foto's en rapport"
    print(f"\n{wat}: {uitmap}")
    print("Volgende stap: loop de keuze na en maak captions (zie fotogeneratie/lora/README.md, stap 3).")


if __name__ == "__main__":
    main()
