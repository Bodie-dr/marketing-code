"""Stap 4 (voorbereiding): verpak dataset + config + RunPod-script in één zip.

Controleert eerst de dataset met check_dataset.py en stopt bij fouten, zodat
je geen GPU-tijd betaalt voor een dataset die niet klopt.

Gebruik:
    python fotogeneratie/lora/maak_pakket.py <datasetmap>
    python fotogeneratie/lora/maak_pakket.py <datasetmap> --naam tvbprod_qwen_image_v2
    python fotogeneratie/lora/maak_pakket.py <datasetmap> --forceer     # ook bij fouten

Upload daarna de zip naar RunPod en volg de stappen bovenin runpod_train.sh.
"""

import argparse
import re
import subprocess
import sys
import zipfile
from pathlib import Path

LORA_DIR = Path(__file__).resolve().parent
PROJECT_DIR = LORA_DIR.parents[1]
STANDAARD_UIT = PROJECT_DIR / "outputs" / "lora_pakket"
CONFIG = LORA_DIR / "ai_toolkit_product.yaml"
RUNPOD_SCRIPT = LORA_DIR / "runpod_train.sh"
DATASET_EXTENSIES = {".jpg", ".jpeg", ".png", ".webp", ".txt"}


def config_naam(tekst: str) -> str:
    match = re.search(r'^\s*name:\s*"([^"]+)"', tekst, re.MULTILINE)
    return match.group(1) if match else "lora"


def zet_naam(tekst: str, naam: str) -> str:
    """Vervang alleen de eerste 'name:' (de trainingsrun), niet die onder meta."""
    return re.sub(r'^(\s*name:\s*)"[^"]*"', rf'\g<1>"{naam}"', tekst, count=1, flags=re.MULTILINE)


def dataset_bestanden(map_: Path) -> list[Path]:
    return sorted(p for p in map_.iterdir() if p.is_file() and p.suffix.lower() in DATASET_EXTENSIES)


def maak_zip(dataset: Path, config_tekst: str, doel: Path) -> int:
    doel.parent.mkdir(parents=True, exist_ok=True)
    bestanden = dataset_bestanden(dataset)
    with zipfile.ZipFile(doel, "w", compression=zipfile.ZIP_STORED) as archief:
        for pad in bestanden:
            archief.write(pad, f"dataset/{pad.name}")
        archief.writestr("ai_toolkit_product.yaml", config_tekst)
        # Linux-regeleinden, anders weigert bash het script op RunPod.
        archief.writestr("runpod_train.sh", RUNPOD_SCRIPT.read_text(encoding="utf-8").replace("\r\n", "\n"))
    return len(bestanden)


def main() -> None:
    parser = argparse.ArgumentParser(description="Verpak een LoRA-dataset voor RunPod.")
    parser.add_argument("dataset", type=Path, help="Map met foto's + .txt-captions.")
    parser.add_argument("--naam", help="Naam van de trainingsrun (standaard uit de config).")
    parser.add_argument("--trigger", default="tvbprod", help="Triggerwoord voor de controle.")
    parser.add_argument("--forceer", action="store_true", help="Ook verpakken als de controle fouten vindt.")
    parser.add_argument("--uit", type=Path, default=STANDAARD_UIT, help="Map voor de zip.")
    arguments = parser.parse_args()

    if not arguments.dataset.is_dir():
        sys.exit(f"Map niet gevonden: {arguments.dataset}")

    controle = subprocess.run(
        [sys.executable, str(LORA_DIR / "check_dataset.py"), str(arguments.dataset), "--trigger", arguments.trigger],
        check=False,
    )
    if controle.returncode != 0 and not arguments.forceer:
        sys.exit("\nDe dataset heeft fouten (zie hierboven). Los ze op, of gebruik --forceer.")

    config_tekst = CONFIG.read_text(encoding="utf-8")
    if arguments.naam:
        config_tekst = zet_naam(config_tekst, arguments.naam)
    naam = config_naam(config_tekst)
    doel = arguments.uit / f"{naam}_pakket.zip"
    aantal = maak_zip(arguments.dataset, config_tekst, doel)
    print(f"\nPakket klaar: {doel} ({aantal} bestanden, run '{naam}')")
    print("Volgende stap: upload naar RunPod en volg de stappen bovenin runpod_train.sh.")


if __name__ == "__main__":
    main()
