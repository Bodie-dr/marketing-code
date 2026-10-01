#!/usr/bin/env bash
# Stap 4: product-LoRA trainen op RunPod met ai-toolkit (Qwen-Image).
#
# Op RunPod:
#   1. Pod met een PyTorch/CUDA-template, GPU 48 GB (A6000/L40S/A40) en een
#      network volume op /workspace (dan blijven model en checkpoints bewaard).
#   2. Upload het pakket (gemaakt met maak_pakket.py), bijv. via Jupyter of:
#        runpodctl send tvbprod_v1_pakket.zip     (lokaal)
#        runpodctl receive <code>                 (op de pod)
#   3. Start in een tmux-sessie, zodat de training doorloopt als je verbinding wegvalt:
#        tmux new -s lora
#        cd /workspace && unzip -o tvbprod_v1_pakket.zip -d pakket && bash pakket/runpod_train.sh
#      Loskoppelen: Ctrl+B, dan D.  Terugkeren: tmux attach -t lora
#
# Checkpoints en testbeelden komen in /workspace/output/<naam>/.
set -euo pipefail

PAKKET="$(cd "$(dirname "$0")" && pwd)"
WORKSPACE="${WORKSPACE:-/workspace}"
CONFIG="$PAKKET/ai_toolkit_product.yaml"

# Modellen (±40 GB) op het volume bewaren, zodat een volgende pod ze niet opnieuw downloadt.
export HF_HOME="$WORKSPACE/hf_cache"
export HF_HUB_ENABLE_HF_TRANSFER=1

echo "== Dataset naar $WORKSPACE/dataset"
mkdir -p "$WORKSPACE/dataset"
cp -f "$PAKKET"/dataset/* "$WORKSPACE/dataset/"
echo "   $(ls "$WORKSPACE/dataset" | grep -ciE '\.(jpe?g|png|webp)$') foto's, $(ls "$WORKSPACE/dataset" | grep -ci '\.txt$') captions"

if [ ! -d "$WORKSPACE/ai-toolkit" ]; then
    echo "== ai-toolkit installeren"
    git clone https://github.com/ostris/ai-toolkit.git "$WORKSPACE/ai-toolkit"
    cd "$WORKSPACE/ai-toolkit"
    git submodule update --init --recursive
    pip install --upgrade pip
    # De PyTorch-template heeft torch al; requirements vult de rest aan.
    pip install -r requirements.txt
    pip install hf_transfer
else
    echo "== ai-toolkit bijwerken"
    cd "$WORKSPACE/ai-toolkit"
    git pull --ff-only || echo "   (bijwerken mislukt, ga verder met de huidige versie)"
fi

if [ -n "${HF_TOKEN:-}" ]; then
    echo "== Inloggen bij Hugging Face"
    huggingface-cli login --token "$HF_TOKEN" >/dev/null
fi

nvidia-smi --query-gpu=name,memory.total --format=csv,noheader
GEHEUGEN_MB="$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits | head -1)"
if [ "$GEHEUGEN_MB" -lt 40000 ] && ! grep -qE '^\s*qtype: "uint3' "$CONFIG"; then
    echo "!! Deze GPU heeft minder dan 40 GB. Zet in ai_toolkit_product.yaml de 24GB-regels aan"
    echo "!! (qtype uint3 en low_vram: true), anders loopt het geheugen vol."
    exit 1
fi

cp -f "$CONFIG" config/ai_toolkit_product.yaml
echo "== Training starten"
python run.py config/ai_toolkit_product.yaml

echo
echo "Klaar. Download /workspace/output/<naam>/samples en draai lokaal:"
echo "  python fotogeneratie/lora/vergelijk_checkpoints.py <samples-map>"
