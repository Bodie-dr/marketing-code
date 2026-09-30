"""
Qwen-backend voor foto-analyse (stijl leren) en foto-modificatie.

Twee manieren om Qwen te draaien:

- lokaal: het gedownloade model Qwen/Qwen-Image-2.1 via diffusers. De
  tekst-encoder van dat model is een volledige Qwen3-VL-8B, die we ook
  gebruiken om foto's te analyseren. Vereist een NVIDIA-GPU (CUDA).
- cloud:  Hugging Face Inference Providers met HF_TOKEN uit .env
  (Qwen3-VL voor analyse, Qwen-Image-Edit voor bewerken).

QWEN_BACKEND in .env: "auto" (standaard: lokaal als er CUDA is, anders
cloud), "lokaal" of "cloud".
"""

import base64
import io
import json
import os
import re
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from threading import Lock

from dotenv import load_dotenv
from PIL import Image

PROJECT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_DIR / ".env")

OUTPUT_DIR = PROJECT_DIR / "outputs" / "qwen"
STIJL_DIR = OUTPUT_DIR / "stijlen"
BEWERKT_DIR = OUTPUT_DIR / "bewerkt"

LOKAAL_MODEL = "Qwen/Qwen-Image-2.1"
CLOUD_ANALYSE_MODEL = os.getenv("QWEN_ANALYSE_MODEL", "Qwen/Qwen3-VL-30B-A3B-Instruct")
CLOUD_EDIT_MODEL = os.getenv("QWEN_EDIT_MODEL", "Qwen/Qwen-Image-Edit-2511")

# Grotere foto's maken de analyse traag en duur, zonder betere stijlherkenning.
MAX_ANALYSE_ZIJDE = 1024

STIJL_VELDEN = (
    "samenvatting",
    "kleurpalet",
    "belichting",
    "compositie",
    "sfeer",
    "nabewerking",
    "stijl_prompt",
)

ANALYSE_INSTRUCTIE = """Je bent art director. Analyseer de visuele stijl die deze
referentiefoto's gemeen hebben (niet de onderwerpen zelf). Antwoord uitsluitend
met één JSON-object met deze sleutels:

- "samenvatting": 1-2 zinnen in het Nederlands over de stijl
- "kleurpalet": lijst met de belangrijkste kleuren als hex-codes
- "belichting": type licht, richting, contrast (Nederlands)
- "compositie": kadrering, camerahoek, scherptediepte (Nederlands)
- "sfeer": gevoel en toon (Nederlands)
- "nabewerking": grading, korrel, verzadiging, filters (Nederlands)
- "stijl_prompt": één Engelse zin die deze stijl beschrijft als instructie
  voor een beeldmodel, zonder onderwerpen te noemen
"""


def _cuda_beschikbaar() -> bool:
    try:
        import torch

        return torch.cuda.is_available()
    except ImportError:
        return False


def kies_backend(voorkeur: str | None = None) -> str:
    voorkeur = (voorkeur or os.getenv("QWEN_BACKEND", "auto")).strip().lower()
    if voorkeur in ("lokaal", "cloud"):
        return voorkeur
    return "lokaal" if _cuda_beschikbaar() else "cloud"


# --------------------------------------------------
# Hulpfuncties (zonder model, dus los te testen)
# --------------------------------------------------


def verklein(afbeelding: Image.Image, max_zijde: int = MAX_ANALYSE_ZIJDE) -> Image.Image:
    afbeelding = afbeelding.convert("RGB")
    afbeelding.thumbnail((max_zijde, max_zijde))
    return afbeelding


def naar_data_url(afbeelding: Image.Image) -> str:
    buffer = io.BytesIO()
    verklein(afbeelding).save(buffer, format="JPEG", quality=90)
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode()


def lees_stijl_json(tekst: str) -> dict:
    """Haal het JSON-object uit het modelantwoord (soms in ```json ... ```)."""
    match = re.search(r"\{.*\}", tekst, re.DOTALL)
    if not match:
        raise ValueError(f"Geen JSON in het antwoord van het model:\n{tekst}")
    stijl = json.loads(match.group(0))
    ontbrekend = [veld for veld in STIJL_VELDEN if veld not in stijl]
    if ontbrekend:
        raise ValueError(f"Stijlprofiel mist velden: {', '.join(ontbrekend)}")
    return stijl


def bouw_edit_prompt(instructie: str, stijl: dict | None) -> str:
    instructie = (instructie or "").strip().rstrip(".")
    if not instructie and not stijl:
        raise ValueError("Geef een instructie, een stijl of allebei.")
    if not stijl:
        return instructie
    stijl_deel = (
        f"Apply this visual style: {stijl['stijl_prompt'].strip().rstrip('.')}. "
        f"Color palette: {', '.join(stijl.get('kleurpalet', []))}."
    )
    if not instructie:
        return (
            "Restyle this photo while keeping the subject, layout and "
            f"identity unchanged. {stijl_deel}"
        )
    return f"{instructie}. {stijl_deel}"


def veilige_naam(naam: str) -> str:
    naam = re.sub(r"[^\w\- ]", "", naam).strip().replace(" ", "_")
    return naam or "stijl"


# --------------------------------------------------
# Stijlprofielen opslaan en laden
# --------------------------------------------------


def sla_stijl_op(naam: str, stijl: dict, aantal_fotos: int, backend: str) -> Path:
    STIJL_DIR.mkdir(parents=True, exist_ok=True)
    pad = STIJL_DIR / f"{veilige_naam(naam)}.json"
    data = {
        **stijl,
        "_meta": {
            "naam": naam,
            "aantal_fotos": aantal_fotos,
            "backend": backend,
            "gemaakt": datetime.now().isoformat(timespec="seconds"),
        },
    }
    pad.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return pad


def stijl_namen() -> list[str]:
    if not STIJL_DIR.is_dir():
        return []
    return sorted(pad.stem for pad in STIJL_DIR.glob("*.json"))


def laad_stijl(naam: str) -> dict:
    return json.loads((STIJL_DIR / f"{naam}.json").read_text(encoding="utf-8"))


# --------------------------------------------------
# Cloud (Hugging Face Inference Providers)
# --------------------------------------------------


def _hf_client():
    from huggingface_hub import InferenceClient

    token = os.getenv("HF_TOKEN")
    if not token:
        raise ValueError("HF_TOKEN ontbreekt in .env (nodig voor de cloud-backend).")
    return InferenceClient(provider="auto", api_key=token, timeout=300)


def _vertaal_hf_fout(fout: Exception) -> Exception:
    tekst = str(fout)
    if "401" in tekst:
        return PermissionError(
            "Hugging Face weigert je HF_TOKEN (ongeldig, verlopen of ingetrokken). "
            "Maak op huggingface.co/settings/tokens een nieuwe token met de permissie "
            "'Make calls to Inference Providers', zet die in .env als HF_TOKEN "
            "en herstart de app."
        )
    if "403" in tekst and "Inference Providers" in tekst:
        return PermissionError(
            "Je HF_TOKEN mag geen Inference Providers aanroepen. Maak op "
            "huggingface.co/settings/tokens een token met de permissie "
            "'Make calls to Inference Providers' en zet die in .env als HF_TOKEN."
        )
    if "402" in tekst:
        return PermissionError("Je Hugging Face-tegoed voor Inference Providers is op.")
    return fout


def _analyseer_cloud(fotos: Sequence[Image.Image]) -> str:
    inhoud = [{"type": "image_url", "image_url": {"url": naar_data_url(f)}} for f in fotos]
    inhoud.append({"type": "text", "text": ANALYSE_INSTRUCTIE})
    try:
        antwoord = _hf_client().chat_completion(
            model=CLOUD_ANALYSE_MODEL,
            messages=[{"role": "user", "content": inhoud}],
            max_tokens=800,
            temperature=0.2,
        )
    except Exception as fout:
        raise _vertaal_hf_fout(fout) from fout
    return antwoord.choices[0].message.content


def _bewerk_cloud(foto: Image.Image, prompt: str, stappen: int, seed: int) -> Image.Image:
    buffer = io.BytesIO()
    foto.convert("RGB").save(buffer, format="PNG")
    try:
        return _hf_client().image_to_image(
            buffer.getvalue(),
            prompt=prompt,
            model=CLOUD_EDIT_MODEL,
            num_inference_steps=stappen,
            seed=seed,
        )
    except Exception as fout:
        raise _vertaal_hf_fout(fout) from fout


# --------------------------------------------------
# Lokaal (diffusers + het gedownloade Qwen-Image-2.1)
# --------------------------------------------------

_lokaal_lock = Lock()
_vl_model = None
_vl_processor = None
_pipeline = None


def _controleer_gpu() -> None:
    if not _cuda_beschikbaar():
        raise RuntimeError(
            "Lokaal draaien vereist een NVIDIA-GPU met CUDA en de CUDA-versie van "
            "torch. Op deze computer is die er niet: kies 'cloud' als backend."
        )


def _laad_vl():
    global _vl_model, _vl_processor
    if _vl_model is None:
        import torch
        from transformers import AutoProcessor, Qwen3VLForConditionalGeneration

        _vl_model = Qwen3VLForConditionalGeneration.from_pretrained(
            LOKAAL_MODEL, subfolder="text_encoder", torch_dtype=torch.bfloat16
        ).to("cuda")
        _vl_processor = AutoProcessor.from_pretrained(LOKAAL_MODEL, subfolder="processor")
    return _vl_model, _vl_processor


def _analyseer_lokaal(fotos: Sequence[Image.Image]) -> str:
    _controleer_gpu()
    with _lokaal_lock:
        model, processor = _laad_vl()
        berichten = [
            {
                "role": "user",
                "content": [{"type": "image", "image": verklein(f)} for f in fotos]
                + [{"type": "text", "text": ANALYSE_INSTRUCTIE}],
            }
        ]
        invoer = processor.apply_chat_template(
            berichten,
            tokenize=True,
            add_generation_prompt=True,
            return_dict=True,
            return_tensors="pt",
        ).to(model.device)
        uitvoer = model.generate(**invoer, max_new_tokens=800, do_sample=False)
        nieuw = uitvoer[:, invoer["input_ids"].shape[1]:]
        return processor.batch_decode(nieuw, skip_special_tokens=True)[0]


def _laad_pipeline():
    global _pipeline
    if _pipeline is None:
        import torch
        from diffusers import QwenImage21Pipeline

        extra = {}
        if _vl_model is not None:
            # Dezelfde Qwen3-VL niet twee keer in het geheugen laden.
            extra = {"text_encoder": _vl_model, "processor": _vl_processor}
        _pipeline = QwenImage21Pipeline.from_pretrained(
            LOKAAL_MODEL, torch_dtype=torch.bfloat16, **extra
        )
        # ±31 GB aan gewichten: alleen het actieve deel op de GPU houden.
        _pipeline.enable_model_cpu_offload()
    return _pipeline


def _bewerk_lokaal(foto: Image.Image, prompt: str, stappen: int, seed: int) -> Image.Image:
    _controleer_gpu()
    import torch

    with _lokaal_lock:
        pipe = _laad_pipeline()
        return pipe(
            prompt=prompt,
            image=foto.convert("RGB"),
            num_inference_steps=stappen,
            generator=torch.Generator("cuda").manual_seed(seed),
        ).images[0]


# --------------------------------------------------
# Publieke functies voor de app
# --------------------------------------------------


def analyseer_stijl(fotos: Sequence[Image.Image], backend: str | None = None) -> tuple[dict, str]:
    """Leer de gemeenschappelijke stijl van één of meer referentiefoto's."""
    if not fotos:
        raise ValueError("Upload minstens één referentiefoto.")
    gekozen = kies_backend(backend)
    ruw = _analyseer_lokaal(fotos) if gekozen == "lokaal" else _analyseer_cloud(fotos)
    return lees_stijl_json(ruw), gekozen


def bewerk_foto(
    foto: Image.Image,
    instructie: str,
    stijl: dict | None = None,
    stappen: int = 30,
    seed: int = 42,
    backend: str | None = None,
) -> tuple[Image.Image, Path, str]:
    """Pas de foto aan volgens de instructie en/of een geleerd stijlprofiel."""
    if foto is None:
        raise ValueError("Upload eerst een foto.")
    prompt = bouw_edit_prompt(instructie, stijl)
    gekozen = kies_backend(backend)
    bewerk = _bewerk_lokaal if gekozen == "lokaal" else _bewerk_cloud
    resultaat = bewerk(foto, prompt, int(stappen), int(seed))

    BEWERKT_DIR.mkdir(parents=True, exist_ok=True)
    pad = BEWERKT_DIR / f"{datetime.now():%Y%m%d-%H%M%S}.png"
    resultaat.save(pad)
    return resultaat, pad, prompt
