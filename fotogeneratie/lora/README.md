# Product-LoRA trainen (Qwen-Image, ai-toolkit op RunPod)

Alle commando's start je vanuit de projectmap. Triggerwoord in dit voorbeeld:
`tvbprod`. Kies voor een ander product een ander uniek woord en pas het aan
in de captions, `ai_toolkit_product.yaml` en `--trigger`.

| Stap | Waar | Commando / bestand |
|---|---|---|
| 1. Foto's kiezen | laptop | `selecteer_fotos.py` |
| 2. Achtergronden | laptop | nalopen in `rapport.csv` |
| 3. Captions | laptop | `maak_captions.py --soort product`, `check_dataset.py` |
| 4. Trainen | RunPod | `maak_pakket.py` → `runpod_train.sh` |
| 5. Beste checkpoint | laptop | `vergelijk_checkpoints.py` |
| 6. Genereren | ComfyUI / fal.ai / Replicate | `prompt_voorbeelden.md` |
| 7. Huisstijl | laptop | `fotogeneratie/pas_lut_toe.py` |
| 8. Logo | laptop | `fotogeneratie/voeg_logo_toe.py` |

## 1. Selecteer 30–60 foto's

```powershell
python fotogeneratie/lora/selecteer_fotos.py "<map met de 100 productfoto's>" --aantal 45
```

Laat wazige, te kleine en bijna-dubbele foto's weg en kiest de meest
gevarieerde set. Resultaat: `outputs/lora_selectie/<map>/` plus `rapport.csv`
met de reden per foto. Het script kijkt alleen naar pixels: controleer zelf
dat er voor, zij, achter, boven, schuin, geheel én close-ups tussen zitten, en
ruil foto's om waar nodig.

## 2. Let op de achtergronden

Staan (bijna) alle foto's op wit, voeg dan foto's van het product in gebruik of
in een omgeving toe. Lukt dat niet, noem de achtergrond dan altijd in de
caption (`on a plain white background`), zodat het model wit niet aan het
product koppelt.

## 3. Captions

```powershell
python fotogeneratie/maak_captions.py outputs/lora_selectie/<map> --trigger tvbprod --soort product --product "<wat het product is>" --uit outputs/lora_dataset/tvbprod
```

Qwen3-VL beschrijft alles **behalve** het product: wat er gebeurt, omgeving,
hoek en afstand, licht. Dat kan via de cloud (`HF_TOKEN` in `.env`), dus zonder GPU.
Loop daarna elke `.txt` na volgens `caption_sjabloon.txt` en controleer:

```powershell
python fotogeneratie/lora/check_dataset.py outputs/lora_dataset/tvbprod
```

Vul eerst `verboden_woorden.txt` aan met de kleur, materialen, merknaam en
onderdelen van jullie product; het script waarschuwt als die in een caption staan.

## 4. Trainen op RunPod

```powershell
python fotogeneratie/lora/maak_pakket.py outputs/lora_dataset/tvbprod
```

Dit controleert de dataset nog een keer en maakt
`outputs/lora_pakket/tvbprod_qwen_image_v1_pakket.zip` (dataset + config +
script). Upload die naar een RunPod-pod (48 GB GPU, network volume op
`/workspace`) en volg de stappen bovenin `runpod_train.sh`.

Startwaarden in `ai_toolkit_product.yaml`: rank 32, learning rate 1e-4,
3000 stappen, elke 250 stappen een checkpoint met testbeelden. Hoog bij een
nieuwe poging de versie in `name` op (of gebruik `--naam`).

## 5. Kies het beste checkpoint

Download `/workspace/output/<naam>/samples` en draai:

```powershell
python fotogeneratie/lora/vergelijk_checkpoints.py <samples-map>
```

Dat geeft `vergelijking.jpg`: één rij per testprompt, één kolom per stap.
Kijk naar vorm, verhoudingen, kleuren, knoppen en naden. Kies de vroegste stap
waar alles klopt. De laatste rij (zonder triggerwoord) mag het product niet
tonen; doet hij dat wel, dan is de LoRA overgetraind. Download daarna alleen
dat ene `.safetensors`-bestand.

## 6. Genereren en controleren

Laad de `.safetensors` in ComfyUI (Qwen-Image + LoRA Loader) of upload hem
naar fal.ai of Replicate voor gebruik door het team. Prompts:
`prompt_voorbeelden.md`. Controleer elk beeld op productdetails; logo's en
tekst gaan het vaakst mis.

## 7. Huisstijl met een vaste LUT

Exporteer de TVB-look als 3D-LUT (`.cube`) uit Lightroom, Photoshop of
DaVinci Resolve en pas hem toe:

```powershell
python fotogeneratie/pas_lut_toe.py <map> --lut tvb_stijl.cube --sterkte 0.8
```

## 8. TVB-logo erop

```powershell
python fotogeneratie/voeg_logo_toe.py <map>                         # badge rechtsonder
python fotogeneratie/voeg_logo_toe.py <map> --stijl transparant --breedte 0.12
```

Het meegeleverde logo (`fotogeneratie/assets/tvb_logo.jpg`) is 200×200 px:
vraag marketing om een PNG met transparantie in hoge resolutie en gebruik die
met `--logo`.
