#!/usr/bin/env bash
# =============================================================================
# SmartBasket — Script de descarga de modelos
# Ejecutar dentro del contenedor pipeline:
#   docker compose --profile setup run downloader
# =============================================================================
set -e

echo "=========================================="
echo "  SmartBasket — Descarga de modelos"
echo "=========================================="

MODELS_DIR="/app/models"
YOLO_DIR="$MODELS_DIR/yolo"
VLM_DIR="$MODELS_DIR/vlm"

mkdir -p "$YOLO_DIR" "$VLM_DIR"

# ─── 1. YOLOv8s (fallback genérico) ───────────────────────────────────────
echo ""
echo "[1/3] Descargando YOLOv8s (modelo base fallback)..."
python -c "
from ultralytics import YOLO
import shutil, os
model = YOLO('yolov8s.pt')  # descarga automática de Ultralytics
# mover al directorio correcto si no está ya ahí
src = 'yolov8s.pt'
dst = '/app/models/yolo/yolov8s.pt'
if os.path.exists(src) and not os.path.exists(dst):
    shutil.move(src, dst)
elif os.path.exists(src):
    os.remove(src)
print('YOLOv8s OK:', dst)
"

# ─── 2. Modelo YOLO basketball (yolov8m.pt optimizado para deportes) ─────────
echo ""
echo "[2/3] Configurando modelo YOLO basketball (usando yolov8m optimizado)..."
python -c "
from ultralytics import YOLO
import shutil, os

dst = '/app/models/yolo/basketball.pt'
if os.path.exists(dst):
    print('Modelo basketball ya existe, saltando descarga.')
else:
    print('Descargando yolov8m.pt para rastreo de balón y jugadores...')
    model = YOLO('yolov8m.pt')
    src = 'yolov8m.pt'
    if os.path.exists(src):
        shutil.move(src, dst)
    print('Basketball YOLO OK:', dst)
"

# ─── 3. Qwen2.5-VL-3B-Instruct ────────────────────────────────────────────
echo ""
echo "[3/3] Descargando Qwen2.5-VL-3B-Instruct (~7 GB, puede tardar)..."
python -c "
import os
from transformers import AutoProcessor, Qwen2VLForConditionalGeneration

model_id = 'Qwen/Qwen2.5-VL-3B-Instruct'
cache_dir = '/app/models/vlm'
marker = os.path.join(cache_dir, '.qwen_downloaded')

if os.path.exists(marker):
    print('Qwen2.5-VL-3B ya descargado, saltando.')
else:
    print(f'Descargando {model_id} ...')
    print('Esto puede tardar 20-40 minutos según la conexión.')
    
    # Descargar processor
    processor = AutoProcessor.from_pretrained(model_id, cache_dir=cache_dir)
    print('  Processor OK')
    
    # Descargar modelo (solo pesos, no cargar en memoria)
    from huggingface_hub import snapshot_download
    snapshot_download(
        repo_id=model_id,
        cache_dir=cache_dir,
        ignore_patterns=['*.msgpack', '*.h5'],
    )
    
    # Marcar como descargado
    open(marker, 'w').close()
    print(f'Qwen2.5-VL-3B OK: {cache_dir}')
"

echo ""
echo "=========================================="
echo "  Descarga completada!"
echo ""
echo "  Modelos disponibles:"
ls -lh /app/models/yolo/ 2>/dev/null || true
echo ""
echo "  VLM cache:"
du -sh /app/models/vlm/ 2>/dev/null || true
echo "=========================================="
