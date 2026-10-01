#!/usr/bin/env python3
"""
check_dataset.py - controleert een LoRA-dataset voordat je betaalt voor GPU-tijd.

Controleert:
  - aantal foto's (advies 30-60)
  - beschadigde / onleesbare bestanden
  - resolutie (korte zijde minimaal 1024 px advies, onder 768 px fout)
  - extreme beeldverhoudingen
  - ontbrekende, lege of losse (weesbestand) captions
  - triggerwoord vooraan in elke caption
  - verboden woorden in captions (productkenmerken, stijlwoorden)
  - exacte en bijna-dubbele foto's

Gebruik:
  python check_dataset.py dataset/
  python check_dataset.py dataset/ --trigger tvbprod --verboden verboden_woorden.txt
  python check_dataset.py dataset/ --maak-captions      # maakt lege sjabloon-captions voor foto's zonder .txt
  python check_dataset.py dataset/ --rapport rapport.csv

Vereist alleen Pillow:  pip install pillow
"""

import argparse
import csv
import hashlib
import re
import sys
from pathlib import Path

try:
    from PIL import Image, ImageOps,
except ImportError:
    sys.exit("Pillow ontbreekt. Installeer met:  pip install pillow")

BEELD_EXT = {".jpg", ".jpeg", ".png", ".webp"}
MIN_ADVIES = 1024      # korte zijde: hieronder een waarschuwing
MIN_HARD = 768         # korte zijde: hieronder een fout
MAX_VERHOUDING = 2.5   # langer dan 2.5:1 -> waarschuwing
AANTAL_MIN, AANTAL_MAX = 30, 60
BIJNA_DUBBEL_DREMPEL = 5  # verschil in bits (van 64) waaronder foto's als bijna-dubbel gelden

SJABLOON = "{trigger}, [wat er gebeurt], [omgeving], [hoek en afstand], [licht]"


def lees_verboden(pad):
    if not pad:
        return []
    p = Path(pad)
    if not p.exists():
        print(f"! Bestand met verboden woorden niet gevonden: {pad}")
        return []
    woorden = []
    for regel in p.read_text(encoding="utf-8").splitlines():
        regel = regel.strip()
        if regel and not regel.startswith("#"):
            woorden.append(regel.lower())
    return woorden


def bestand_hash(pad):
    h = hashlib.md5()
    with open(pad, "rb") as f:
        for blok in iter(lambda: f.read(1 << 20), b""):
            h.update(blok)
    return h.hexdigest()


def beeld_hash(img):
    """'Difference hash' (64 bits) om bijna-dubbele foto's te vinden."""
    klein = img.convert("L").resize((9, 8), Image.LANCZOS)
    px = klein.tobytes()
    waarde = 0
    for rij in range(8):
        for kol in range(8):
            links = px[rij * 9 + kol]
            rechts = px[rij * 9 + kol + 1]
            waarde = (waarde << 1) | (1 if links > rechts else 0)
    return waarde


def bits_verschil(a, b):
    return bin(a ^ b).count("1")


def bevat_woord(tekst, woord):
    # hele woorden/frasen, niet-hoofdlettergevoelig ("red" matcht niet in "covered")
    return re.search(r"(?<![a-z0-9])" + re.escape(woord) + r"(?![a-z0-9])", tekst) is not None


def main():
    ap = argparse.ArgumentParser(description="Controleer een LoRA-dataset.")
    ap.add_argument("map", help="map met foto's en .txt-captions")
    ap.add_argument("--trigger", default="tvbprod", help="triggerwoord (standaard: tvbprod)")
    ap.add_argument("--verboden", default="verboden_woorden.txt", help="bestand met verboden woorden")
    ap.add_argument("--maak-captions", action="store_true",
                    help="maak een sjabloon-caption voor elke foto zonder .txt (overschrijft niets)")
    ap.add_argument("--rapport", help="schrijf een CSV-rapport naar dit bestand")
    args = ap.parse_args()

    map_ = Path(args.map)
    if not map_.is_dir():
        sys.exit(f"Map niet gevonden: {map_}")

    trigger = args.trigger.strip().lower()
    verboden = lees_verboden(args.verboden)

    beelden = sorted(p for p in map_.iterdir() if p.suffix.lower() in BEELD_EXT)
    captions = sorted(p for p in map_.iterdir() if p.suffix.lower() == ".txt")

    fouten, waarschuwingen = [], []
    rijen = []
    hashes_exact = {}
    hashes_beeld = []
    gemaakt = 0

    print(f"\nDataset: {map_.resolve()}")
    print(f"Triggerwoord: {trigger}")
    print(f"Verboden woorden geladen: {len(verboden)}\n")

    # --- Per foto ---
    for pad in beelden:
        rij = {"bestand": pad.name, "breedte": "", "hoogte": "", "status": "ok", "opmerkingen": []}

        # leesbaar + afmetingen
        try:
            with Image.open(pad) as img:
                img.verify()
            with Image.open(pad) as img:
                img = ImageOps.exif_transpose(img)
                b, h = img.size
                ahash = beeld_hash(img)
        except Exception as e:
            fouten.append(f"{pad.name}: kan niet worden geopend ({e})")
            rij["status"] = "FOUT"
            rij["opmerkingen"].append("onleesbaar")
            rijen.append(rij)
            continue

        rij["breedte"], rij["hoogte"] = b, h
        kort = min(b, h)
        if kort < MIN_HARD:
            fouten.append(f"{pad.name}: te klein ({b}x{h}), korte zijde < {MIN_HARD} px")
            rij["status"] = "FOUT"
            rij["opmerkingen"].append("te klein")
        elif kort < MIN_ADVIES:
            waarschuwingen.append(f"{pad.name}: aan de kleine kant ({b}x{h}), advies korte zijde >= {MIN_ADVIES} px")
            rij["opmerkingen"].append("klein")

        verhouding = max(b, h) / kort
        if verhouding > MAX_VERHOUDING:
            waarschuwingen.append(f"{pad.name}: extreme beeldverhouding ({verhouding:.1f}:1)")
            rij["opmerkingen"].append("extreme verhouding")

        # dubbelen
        hx = bestand_hash(pad)
        if hx in hashes_exact:
            fouten.append(f"{pad.name}: exact dezelfde foto als {hashes_exact[hx]}")
            rij["status"] = "FOUT"
            rij["opmerkingen"].append(f"dubbel van {hashes_exact[hx]}")
        else:
            hashes_exact[hx] = pad.name
            hashes_beeld.append((pad.name, ahash))

        # caption
        cap = pad.with_suffix(".txt")
        if not cap.exists():
            if args.maak_captions:
                cap.write_text(SJABLOON.format(trigger=args.trigger.strip()) + "\n", encoding="utf-8")
                gemaakt += 1
                waarschuwingen.append(f"{pad.name}: sjabloon-caption aangemaakt, nog invullen")
                rij["opmerkingen"].append("sjabloon aangemaakt")
            else:
                fouten.append(f"{pad.name}: caption ontbreekt ({cap.name})")
                rij["status"] = "FOUT"
                rij["opmerkingen"].append("geen caption")
        else:
            tekst = cap.read_text(encoding="utf-8").strip()
            laag = tekst.lower()
            if not tekst:
                fouten.append(f"{cap.name}: caption is leeg")
                rij["status"] = "FOUT"
                rij["opmerkingen"].append("lege caption")
            else:
                if "[" in tekst and "]" in tekst:
                    fouten.append(f"{cap.name}: sjabloon nog niet ingevuld")
                    rij["status"] = "FOUT"
                    rij["opmerkingen"].append("sjabloon niet ingevuld")
                if not laag.startswith(trigger):
                    fouten.append(f"{cap.name}: begint niet met triggerwoord '{trigger}'")
                    rij["status"] = "FOUT"
                    rij["opmerkingen"].append("triggerwoord ontbreekt vooraan")
                elif laag.count(trigger) > 1:
                    waarschuwingen.append(f"{cap.name}: triggerwoord staat er meerdere keren in")
                    rij["opmerkingen"].append("triggerwoord dubbel")
                gevonden = [w for w in verboden if bevat_woord(laag, w)]
                if gevonden:
                    waarschuwingen.append(f"{cap.name}: bevat verboden woord(en): {', '.join(gevonden)}")
                    rij["opmerkingen"].append("verboden: " + ", ".join(gevonden))
                if len(tekst.split()) < 6:
                    waarschuwingen.append(f"{cap.name}: erg korte caption, beschrijf omgeving/hoek/licht")
                    rij["opmerkingen"].append("korte caption")

        if rij["status"] == "ok" and rij["opmerkingen"]:
            rij["status"] = "let op"
        rijen.append(rij)

    # --- Losse captions zonder foto ---
    beeld_stammen = {p.stem for p in beelden}
    for cap in captions:
        if cap.stem not in beeld_stammen:
            waarschuwingen.append(f"{cap.name}: caption zonder bijbehorende foto")

    # --- Bijna-dubbelen ---
    bijna = []
    for i in range(len(hashes_beeld)):
        for j in range(i + 1, len(hashes_beeld)):
            n1, h1 = hashes_beeld[i]
            n2, h2 = hashes_beeld[j]
            if bits_verschil(h1, h2) <= BIJNA_DUBBEL_DREMPEL:
                bijna.append((n1, n2))
    for n1, n2 in bijna:
        waarschuwingen.append(f"{n1} en {n2} lijken sterk op elkaar (bijna-dubbel?). "
                              f"Uitsneden van dezelfde foto zijn ok, anders er één weghalen.")

    # --- Aantal ---
    n = len(beelden)
    if n == 0:
        fouten.append("Geen foto's gevonden (.jpg, .jpeg, .png, .webp)")
    elif n < AANTAL_MIN:
        waarschuwingen.append(f"Slechts {n} foto's. Advies: {AANTAL_MIN}-{AANTAL_MAX}.")
    elif n > AANTAL_MAX:
        waarschuwingen.append(f"{n} foto's. Meer dan {AANTAL_MAX} mag, maar selecteer liever op kwaliteit en variatie.")

    # --- Uitvoer ---
    print("=" * 70)
    print(f"Foto's: {n}   Captions: {len(captions) + gemaakt}   "
          f"Fouten: {len(fouten)}   Waarschuwingen: {len(waarschuwingen)}")
    print("=" * 70)

    if fouten:
        print("\nFOUTEN (eerst oplossen):")
        for f in fouten:
            print(f"  x {f}")
    if waarschuwingen:
        print("\nWAARSCHUWINGEN (nalopen):")
        for w in waarschuwingen:
            print(f"  ! {w}")
    if gemaakt:
        print(f"\n{gemaakt} sjabloon-captions aangemaakt. Vul ze in en draai het script opnieuw.")

    if args.rapport:
        with open(args.rapport, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["bestand", "breedte", "hoogte", "status", "opmerkingen"])
            for r in rijen:
                w.writerow([r["bestand"], r["breedte"], r["hoogte"], r["status"], "; ".join(r["opmerkingen"])])
        print(f"\nRapport opgeslagen: {args.rapport}")

    if not fouten:
        print("\nGeen fouten: de dataset is klaar om te trainen."
              + (" Loop de waarschuwingen nog even na." if waarschuwingen else ""))
        sys.exit(0)
    sys.exit(1)


if __name__ == "__main__":
    main()
