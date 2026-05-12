# SmartBasket 🏀

**Agente local de highlights de basketball juvenil**

Sistema end-to-end para analizar videos de partidos, detectar jugadas candidatas y generar un reel automáticamente. Corre completamente en local usando Docker y modelos de IA locales (YOLO + Qwen2.5-VL).

---

## Requisitos

| Componente | Mínimo |
|---|---|
| GPU NVIDIA | 12 GB VRAM |
| RAM | 36 GB |
| Docker Desktop | con WSL2 backend |
| NVIDIA Container Toolkit | para GPU en Docker |
| Disco | ~30 GB libres para modelos |

### Verificar soporte GPU en Docker

```powershell
# Verificar que Docker ve la GPU
docker run --rm --runtime nvidia nvidia/cuda:12.1.1-base-ubuntu22.04 nvidia-smi
```

---

## Setup inicial

### 1. Clonar y configurar variables de entorno

```bash
cd c:\code\SmartBasket
cp .env.example .env
# Editar .env si es necesario
```

### 2. Construir las imágenes Docker

```bash
docker compose build pipeline reviewer
```

### 3. Descargar modelos (primera vez — puede tardar 30-60 min)

Esto descarga:
- `yolov8s.pt` (fallback genérico)
- `basketball.pt` (modelo custom de detección de basketball)
- `Qwen2.5-VL-3B-Instruct` (~7 GB desde HuggingFace)

```bash
docker compose --profile setup run downloader
```

Los modelos quedan persistidos en `basketball-highlight-agent/models/`.

---

## Uso

### Pipeline completo (análisis end-to-end)

```bash
# Copiar el video al directorio de input
cp ruta/al/partido.mp4 basketball-highlight-agent/videos/input/game001.mp4

# Ejecutar el pipeline completo
docker compose --profile pipeline run pipeline \
  python -m basketball_highlights.cli analyze \
  videos/input/game001.mp4
```

### Solo candidatos (sin cortar clips, sin VLM — modo rápido)

```bash
docker compose --profile pipeline run pipeline \
  python -m basketball_highlights.cli candidates \
  videos/input/game001.mp4
```

### Sin VLM (solo heurísticas YOLO + audio + motion)

```bash
docker compose --profile pipeline run pipeline \
  python -m basketball_highlights.cli analyze \
  videos/input/game001.mp4 \
  --no-vlm
```

### Clasificar con VLM sobre candidatos ya generados

```bash
docker compose --profile pipeline run pipeline \
  python -m basketball_highlights.cli label \
  data/candidates/game001_candidates.json
```

### Crear reel desde candidatos

```bash
docker compose --profile pipeline run pipeline \
  python -m basketball_highlights.cli reel \
  data/candidates/game001_candidates_labeled.json \
  --top-k 10 \
  --mode score
```

### Revisar candidatos en UI

```bash
# Levantar el reviewer
docker compose --profile reviewer up reviewer -d

# Abrir en el navegador
# http://localhost:8501
```

---

## Estructura de outputs

Después de procesar `game001.mp4`:

```
basketball-highlight-agent/
  data/
    frames/game001/           ← frames extraídos (2 fps)
    audio/game001.wav          ← audio extraído
    detections/game001_yolo.json      ← detecciones YOLO por frame
    candidates/game001_candidates.json        ← candidatos con score
    candidates/game001_candidates_labeled.json ← candidatos + VLM
    annotations/game001_annotations.json      ← anotaciones humanas
    reports/game001_report.json               ← reporte de procesamiento

  videos/
    clips/game001/            ← clips individuales recortados
    reels/game001_top10.mp4   ← reel final
```

---

## Configuración

Todos los parámetros se pueden ajustar sin modificar código:

| Archivo | Qué controla |
|---|---|
| `configs/default.yaml` | FPS, pre/post-roll, thresholds, output |
| `configs/scoring.yaml` | Pesos de scoring y penalizaciones |
| `configs/models.yaml` | Parámetros YOLO, VLM, geometría de cancha |

### Ejemplo: desactivar VLM permanentemente

```yaml
# configs/default.yaml
models:
  use_vlm: false
```

### Ejemplo: ajustar sensibilidad de detección

```yaml
# configs/scoring.yaml
weights:
  ball_near_hoop: 4.0   # más peso si el balón está cerca del aro
  audio_peak: 2.0        # más peso a reacciones del público
```

### Configurar regiones del aro manualmente

Si el modelo no detecta el aro automáticamente:

```yaml
# configs/models.yaml
court:
  manual_hoop_regions:
    enabled: true
    regions:
      - name: "left_hoop"
        x1: 100
        y1: 80
        x2: 220
        y2: 220
      - name: "right_hoop"
        x1: 1500
        y1: 80
        x2: 1650
        y2: 220
```

---

## Tests

```bash
docker compose --profile pipeline run pipeline \
  python -m pytest tests/ -v
```

---

## Modelos usados

| Modelo | Uso | VRAM |
|---|---|---|
| `yolov8s.pt` | Fallback detección personas | ~0.5 GB |
| `basketball.pt` | Detección balón/aro/jugadores | ~1 GB |
| `Qwen2.5-VL-3B-Instruct` | Clasificación VLM de clips | ~6-8 GB |

---

## Tipos de jugadas detectadas

- 🏀 Canastas (`score`)
- 🎯 Triples (`three_pointer`)
- 🛡️ Bloqueos (`block`)
- ⚡ Robos (`steal`)
- 🏃 Fast breaks (`fast_break`)
- 🤝 Asistencias (`assist`)
- 💪 Rebotes (`rebound`)
- 🚨 Faltas (`foul`)

---

## Criterios de aceptación del MVP

- [x] Procesa un `.mp4` local
- [x] Genera `candidates.json` con score + razones
- [x] Exporta clips individuales con FFmpeg
- [x] Crea reel final
- [x] UI de revisión humana
- [x] Funciona sin VLM (`--no-vlm`)
- [x] Todos los parámetros configurables desde YAML
- [x] Pipeline completo en Docker con GPU
