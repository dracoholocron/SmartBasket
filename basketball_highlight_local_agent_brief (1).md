# Brief técnico para Claude: Agente local de highlights de basketball juvenil

## Objetivo

Construir un sistema local para analizar videos largos de partidos de basketball juvenil, detectar jugadas candidatas a highlight, recortar clips automáticamente y generar un reel con las mejores jugadas.

El sistema debe funcionar localmente en una máquina con:

- GPU NVIDIA con 12 GB de VRAM
- 36 GB de RAM
- Linux, Windows con WSL2, o macOS no prioritario
- Python 3.11 recomendado
- FFmpeg instalado

El objetivo inicial no es lograr detección perfecta, sino crear un pipeline testeable que produzca candidatos razonables y permita mejorar con revisión humana.

---

## Caso de uso principal

Dado un video largo de un partido de basketball juvenil, el sistema debe:

1. Analizar el video localmente.
2. Detectar candidatos de highlight.
3. Puntuar cada candidato.
4. Clasificar el tipo de jugada cuando sea posible.
5. Recortar clips individuales con FFmpeg.
6. Generar un reel con los mejores clips.
7. Exportar un archivo JSON/CSV con timestamps, score y razón de cada candidato.
8. Opcionalmente permitir revisión humana desde una interfaz simple.

Tipos de jugadas prioritarias:

- Canastas
- Triples
- Robos
- Bloqueos
- Fast breaks
- Asistencias claras
- Rebotes importantes
- Jugadas cerca del aro
- Celebraciones o reacciones fuertes

---

## Restricciones importantes

El video puede tener:

- Cámara fija o semi-fija.
- Gimnasios con iluminación irregular.
- Cámara lateral desde las gradas.
- Sin narrador ni diálogo útil.
- Audio con ruido de público, silbatos, banco y cancha.
- Marcador visible o no visible.
- Calidad variable.

Por eso el sistema no debe depender de transcripción de audio. Debe usar señales visuales, audio peaks y reglas deportivas.

---

## Enfoque general

No analizar todo el partido con un modelo VLM pesado. Primero generar candidatos baratos con computer vision y reglas; luego usar un modelo local de visión/lenguaje solo sobre clips candidatos.

Pipeline recomendado:

```text
Video largo
→ FFmpeg: metadata, frames, audio
→ OpenCV / PySceneDetect: movimiento, cambios de escena
→ YOLO: detección de balón, aro, jugadores
→ heurísticas deportivas: score de highlight
→ candidates.json
→ FFmpeg: recorte de clips candidatos
→ VLM local: clasificación de clips candidatos
→ ranking final
→ reel final + clips individuales + metadata
→ revisión humana opcional
```

---

## Stack técnico recomendado

### Lenguaje y runtime

- Python 3.11
- uv o Poetry para dependencias
- CUDA habilitado
- PyTorch con soporte CUDA

### Librerías principales

- `opencv-python`
- `ultralytics`
- `torch`
- `torchvision`
- `numpy`
- `pandas`
- `pydantic`
- `ffmpeg-python` o llamadas directas a `ffmpeg`
- `scenedetect`
- `librosa` o `pydub`
- `fastapi`
- `uvicorn`
- `streamlit` o `gradio`
- `transformers`
- `accelerate`
- `bitsandbytes`, si aplica
- `sentencepiece`, si aplica

### Modelos recomendados para GPU 12 GB

Usar en este orden:

1. YOLOv8n / YOLOv8s como base rápida.
2. YOLOv8m si la GPU lo permite y el rendimiento sigue siendo aceptable.
3. Modelo custom o fine-tuned para clases:
   - `player`
   - `basketball`
   - `hoop`
   - `backboard`, opcional
   - `referee`, opcional
4. VLM local solo para clips candidatos:
   - Qwen2.5-VL-3B-Instruct como primera opción.
   - Qwen2.5-VL-7B-Instruct solo si entra con cuantización o procesamiento reducido.
   - SmolVLM2 como alternativa más liviana.

Importante: no usar el VLM sobre el video completo. Usarlo solo sobre clips de 8 a 20 segundos.

---

## Estructura de proyecto esperada

Crear un proyecto con esta estructura:

```text
basketball-highlight-agent/
  README.md
  pyproject.toml
  .env.example
  .gitignore

  configs/
    default.yaml
    scoring.yaml
    models.yaml

  videos/
    input/
    processed/
    clips/
    reels/

  data/
    frames/
    audio/
    detections/
    candidates/
    annotations/
    reports/

  models/
    yolo/
    vlm/

  src/
    basketball_highlights/
      __init__.py
      cli.py
      config.py
      video_io.py
      frame_sampler.py
      audio_peaks.py
      scene_detection.py
      yolo_detector.py
      tracking.py
      court_geometry.py
      candidate_generator.py
      scorer.py
      clipper.py
      reel_builder.py
      vlm_labeler.py
      reviewer_app.py
      schemas.py
      utils.py

  mcp_server/
    server.py
    tools.py
    README.md

  tests/
    test_scorer.py
    test_timecodes.py
    test_candidate_merge.py
```

---

## Configuración inicial

Crear un archivo `configs/default.yaml` con parámetros editables:

```yaml
video:
  sample_fps_general: 2
  sample_fps_action: 5
  pre_roll_seconds: 3
  post_roll_seconds: 5
  min_clip_seconds: 6
  max_clip_seconds: 24

models:
  yolo_model_path: "models/yolo/basketball.pt"
  fallback_yolo_model: "yolov8s.pt"
  vlm_model: "Qwen/Qwen2.5-VL-3B-Instruct"
  use_vlm: true
  vlm_max_clips: 40

thresholds:
  min_candidate_score: 5.5
  merge_gap_seconds: 4
  audio_peak_percentile: 90
  motion_peak_percentile: 88

output:
  top_k_clips: 20
  reel_top_k: 10
  export_vertical: false
  export_json: true
  export_csv: true
```

Crear `configs/scoring.yaml`:

```yaml
weights:
  ball_near_hoop: 3.0
  upward_ball_motion: 2.5
  players_near_paint: 2.0
  motion_spike: 2.0
  audio_peak: 1.5
  camera_zoom_or_scene_change: 1.0
  possible_score: 3.0
  celebration_like_motion: 1.5

penalties:
  no_ball_detected: -1.5
  no_players_detected: -2.0
  static_scene: -1.0
```

---

## Esquemas de datos

Crear modelos Pydantic para las salidas principales.

### Detection

```python
class Detection(BaseModel):
    frame_index: int
    timestamp: float
    label: str
    confidence: float
    x1: float
    y1: float
    x2: float
    y2: float
```

### CandidateSegment

```python
class CandidateSegment(BaseModel):
    id: str
    video_path: str
    start_time: float
    end_time: float
    score: float
    reasons: list[str]
    signals: dict[str, float]
    play_type: str | None = None
    confidence: float | None = None
    clip_path: str | None = None
```

### VLMLabel

```python
class VLMLabel(BaseModel):
    is_highlight: bool
    play_type: str
    confidence: float
    description: str
    best_start_offset: float | None = None
    best_end_offset: float | None = None
    reason: str
```

---

## Módulos a implementar

### 1. `video_io.py`

Responsabilidades:

- Obtener metadata del video.
- Duración.
- FPS.
- Resolución.
- Crear rutas de salida.
- Validar que FFmpeg esté instalado.

Funciones mínimas:

```python
def get_video_metadata(video_path: str) -> dict:
    ...

def ensure_output_dirs(base_dir: str) -> None:
    ...
```

---

### 2. `frame_sampler.py`

Responsabilidades:

- Extraer frames a baja frecuencia.
- Guardar timestamps.
- Permitir sampling general y sampling más denso en candidatos.

Funciones mínimas:

```python
def sample_frames(video_path: str, output_dir: str, fps: float) -> list[dict]:
    ...
```

Salida:

```json
[
  {
    "frame_path": "data/frames/game_001/frame_000123.jpg",
    "timestamp": 61.5,
    "frame_index": 123
  }
]
```

---

### 3. `audio_peaks.py`

Responsabilidades:

- Extraer audio con FFmpeg.
- Calcular energía de audio por ventana.
- Detectar picos de audio.
- Exportar timestamps de picos.

Señales a detectar:

- Gritos del público.
- Silbatos.
- Reacción del banco.
- Golpes fuertes o rebotes intensos.

No intentar transcribir.

Funciones mínimas:

```python
def extract_audio(video_path: str, wav_path: str) -> str:
    ...

def detect_audio_peaks(wav_path: str, window_seconds: float = 1.0) -> list[dict]:
    ...
```

Salida:

```json
[
  {"timestamp": 734.0, "energy": 0.82, "is_peak": true}
]
```

---

### 4. `scene_detection.py`

Responsabilidades:

- Detectar cortes de cámara o cambios fuertes.
- Ayudar a identificar repeticiones o transiciones.
- No depender demasiado de esto, porque muchos videos juveniles usan cámara fija.

Funciones mínimas:

```python
def detect_scenes(video_path: str) -> list[dict]:
    ...
```

---

### 5. `yolo_detector.py`

Responsabilidades:

- Correr YOLO sobre frames muestreados.
- Detectar balón, aro y jugadores.
- Guardar detecciones por frame.
- Permitir usar modelo custom si existe, o fallback.

Clases deseadas:

```text
basketball
hoop
player
referee optional
backboard optional
```

Funciones mínimas:

```python
class YOLODetector:
    def __init__(self, model_path: str, device: str = "cuda"):
        ...

    def detect_frame(self, frame_path: str) -> list[Detection]:
        ...

    def detect_frames(self, frames: list[dict]) -> list[Detection]:
        ...
```

Importante:

- Si el modelo fallback `yolov8s.pt` no detecta basketball/hoop de forma específica, documentar que se necesita un modelo fine-tuned.
- Para el MVP, si no hay modelo custom, detectar `person` como jugadores y usar heurísticas visuales parciales.

---

### 6. `tracking.py`

Responsabilidades:

- Asociar detecciones de balón entre frames.
- Calcular trayectoria aproximada.
- Calcular velocidad y dirección del balón.
- Determinar si el balón se mueve hacia arriba o hacia el aro.

MVP simple:

- No implementar tracking complejo al inicio.
- Usar nearest neighbor por distancia entre centros de bounding boxes.

Funciones mínimas:

```python
def track_ball(detections: list[Detection]) -> list[dict]:
    ...

def compute_ball_motion(ball_track: list[dict]) -> list[dict]:
    ...
```

---

### 7. `court_geometry.py`

Responsabilidades:

- Estimar zona del aro.
- Estimar zona de pintura de forma aproximada.
- Calcular distancias entre balón, aro y jugadores.

MVP:

- Si se detecta el aro, usar su bounding box como referencia.
- Si no se detecta aro, permitir al usuario marcar manualmente la zona del aro al inicio.

Debe incluir una opción de configuración manual:

```yaml
manual_hoop_regions:
  enabled: false
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

Funciones mínimas:

```python
def ball_near_hoop(ball_box: dict, hoop_boxes: list[dict], threshold_px: float) -> bool:
    ...

def players_near_hoop(player_boxes: list[dict], hoop_boxes: list[dict]) -> int:
    ...
```

---

### 8. `candidate_generator.py`

Responsabilidades:

- Convertir señales por timestamp en segmentos candidatos.
- Combinar señales visuales y de audio.
- Crear ventanas de tiempo alrededor de eventos.
- Fusionar candidatos cercanos.

Señales iniciales:

- Balón cerca del aro.
- Balón con trayectoria ascendente o descendente cerca del aro.
- Varios jugadores cerca de la zona del aro.
- Pico de movimiento.
- Pico de audio.
- Cambio de escena cercano.

Funciones mínimas:

```python
def generate_candidates(
    detections: list[Detection],
    audio_peaks: list[dict],
    scenes: list[dict],
    config: dict,
) -> list[CandidateSegment]:
    ...
```

---

### 9. `scorer.py`

Responsabilidades:

- Asignar score a cada candidato.
- Guardar razones interpretables.
- Ordenar candidatos por score.

Scoring inicial:

```python
score = 0
score += 3.0 if ball_near_hoop else 0
score += 2.5 if upward_ball_motion else 0
score += 2.0 if players_near_paint else 0
score += 2.0 if motion_spike else 0
score += 1.5 if audio_peak else 0
score += 1.0 if scene_change else 0
score += 3.0 if possible_score else 0
```

Debe generar razones como:

```text
ball near hoop
audio peak
high motion
multiple players near basket
possible shot attempt
```

Funciones mínimas:

```python
def score_candidate(candidate: CandidateSegment, weights: dict) -> CandidateSegment:
    ...

def rank_candidates(candidates: list[CandidateSegment]) -> list[CandidateSegment]:
    ...
```

---

### 10. `clipper.py`

Responsabilidades:

- Recortar clips con FFmpeg.
- Agregar pre-roll y post-roll.
- Evitar tiempos negativos.
- Evitar clips demasiado largos.
- Exportar clips individuales.

Funciones mínimas:

```python
def cut_clip(
    video_path: str,
    start_time: float,
    end_time: float,
    output_path: str,
    reencode: bool = False,
) -> str:
    ...

def cut_candidate_clips(candidates: list[CandidateSegment], output_dir: str) -> list[CandidateSegment]:
    ...
```

Comando FFmpeg sugerido para corte rápido:

```bash
ffmpeg -y -ss START -to END -i input.mp4 -c copy output.mp4
```

Si hay problemas con keyframes, usar re-encode:

```bash
ffmpeg -y -ss START -to END -i input.mp4 -c:v libx264 -preset veryfast -crf 20 -c:a aac output.mp4
```

---

### 11. `vlm_labeler.py`

Responsabilidades:

- Tomar solo los clips candidatos top N.
- Pasarlos a un modelo VLM local.
- Pedir salida JSON estricta.
- Ajustar score final según la clasificación.

Prompt para el VLM:

```text
You are analyzing a youth basketball clip.

Return only valid JSON with this schema:
{
  "is_highlight": true,
  "play_type": "score | three_pointer | block | steal | assist | rebound | fast_break | foul | unknown",
  "confidence": 0.0,
  "description": "short description",
  "best_start_offset": 0.0,
  "best_end_offset": 0.0,
  "reason": "why this is or is not a highlight"
}

Prioritize clear basketball highlights: made baskets, three-pointers, blocks, steals, fast breaks, strong assists, and important rebounds.
Reject clips where nothing important happens.
```

Recomendaciones para GPU 12 GB:

- Empezar con Qwen2.5-VL-3B-Instruct.
- Procesar máximo 20-40 clips candidatos por corrida.
- Usar frames representativos del clip en vez de video completo si el consumo de VRAM es alto.
- Usar cuantización si es necesario.

Funciones mínimas:

```python
def label_clip_with_vlm(clip_path: str) -> VLMLabel:
    ...

def label_candidates(candidates: list[CandidateSegment], max_clips: int) -> list[CandidateSegment]:
    ...
```

---

### 12. `reel_builder.py`

Responsabilidades:

- Tomar top K clips.
- Crear reel cronológico o por score.
- Concatenar con FFmpeg.
- Exportar archivo final.

Funciones mínimas:

```python
def build_reel(clips: list[str], output_path: str, mode: str = "score") -> str:
    ...
```

Debe soportar:

- Reel ordenado por score.
- Reel ordenado cronológicamente.

---

### 13. `reviewer_app.py`

Crear una UI simple en Streamlit o Gradio.

Funcionalidades:

- Ver cada clip candidato.
- Mostrar score, razones y tipo de jugada.
- Botones:
  - Aprobar
  - Rechazar
  - Cambiar tipo de jugada
  - Ajustar inicio/fin
- Guardar anotaciones en `data/annotations/`.

Campos de anotación:

```json
{
  "candidate_id": "game001_0001",
  "approved": true,
  "corrected_play_type": "block",
  "corrected_start_time": 123.5,
  "corrected_end_time": 139.0,
  "notes": "clear block and fast break"
}
```

---

## CLI esperada

Crear comandos con Typer o argparse.

Ejemplo:

```bash
python -m basketball_highlights.cli analyze videos/input/game001.mp4
```

Debe ejecutar:

1. Metadata.
2. Frame sampling.
3. Audio peaks.
4. Scene detection.
5. YOLO detections.
6. Candidate generation.
7. Scoring.
8. Clip cutting.
9. Optional VLM labeling.
10. Reel building.

Comandos deseados:

```bash
# Pipeline completo
python -m basketball_highlights.cli analyze videos/input/game001.mp4 --config configs/default.yaml

# Solo detectar candidatos
python -m basketball_highlights.cli candidates videos/input/game001.mp4

# Cortar clips desde JSON
python -m basketball_highlights.cli cut videos/input/game001.mp4 data/candidates/game001_candidates.json

# Clasificar clips con VLM local
python -m basketball_highlights.cli label data/candidates/game001_candidates.json

# Crear reel
python -m basketball_highlights.cli reel data/candidates/game001_candidates_labeled.json

# Abrir UI de revisión
python -m basketball_highlights.cli review data/candidates/game001_candidates_labeled.json
```

---

## MCP server local

Crear un MCP server opcional para que Claude Desktop o Claude Code pueda invocar el pipeline.

Herramientas MCP deseadas:

### `analyze_video`

Input:

```json
{
  "video_path": "videos/input/game001.mp4",
  "top_k": 20,
  "use_vlm": true
}
```

Output:

```json
{
  "candidates_path": "data/candidates/game001_candidates_labeled.json",
  "clips_dir": "videos/clips/game001/",
  "reel_path": "videos/reels/game001_top10.mp4",
  "summary": "Detected 27 candidates, exported top 20 clips, created top 10 reel."
}
```

### `detect_candidates`

Solo genera candidatos sin cortar clips.

### `cut_highlights`

Corta clips desde un JSON de candidatos.

### `build_reel`

Concatena clips aprobados o top K.

### `get_candidate_summary`

Devuelve lista compacta para revisión en Claude.

---

## Prompt operativo para Claude usando el MCP

Una vez construido el MCP, el usuario debería poder pedir:

```text
Analiza el partido videos/input/game001.mp4.
Encuentra las 20 mejores jugadas candidatas.
Prioriza canastas, bloqueos, robos y fast breaks.
Corta clips con 3 segundos antes y 5 segundos después.
Crea un reel con las mejores 10 jugadas.
Devuélveme un resumen con timestamps, tipo de jugada y razón.
```

---

## Estrategia para modelos locales con 12 GB VRAM

### YOLO

Usar primero:

```text
yolov8s.pt
```

Luego entrenar o integrar un modelo custom para basketball.

Parámetros iniciales:

```python
imgsz=640
conf=0.25
device="cuda"
```

Si va lento:

```python
imgsz=416
conf=0.30
```

### VLM

Primera opción:

```text
Qwen/Qwen2.5-VL-3B-Instruct
```

Segunda opción:

```text
SmolVLM2
```

Solo usar el VLM para los mejores candidatos. No más de 40 clips por corrida inicial.

Si hay problemas de VRAM:

- Reducir resolución de clips.
- Extraer 8-16 frames representativos por clip.
- Preguntar al VLM sobre frames, no sobre video completo.
- Usar cuantización.
- Procesar de a un clip.

---

## Modo fallback sin VLM

El sistema debe funcionar aunque `use_vlm=false`.

En ese modo:

- Generar candidatos.
- Rankear por score heurístico.
- Cortar clips.
- Crear reel.
- Permitir revisión humana.

Esto es importante para poder testear rápido sin pelearse con modelos grandes.

---

## Métricas de evaluación

Crear un reporte por video:

```json
{
  "video": "game001.mp4",
  "duration_seconds": 3720,
  "num_candidates": 32,
  "num_clips_exported": 20,
  "num_vlm_highlights": 12,
  "average_score": 6.7,
  "reel_path": "videos/reels/game001_top10.mp4"
}
```

Cuando haya anotaciones humanas, calcular:

- Precision@10
- Precision@20
- Porcentaje de clips aprobados
- Tipos de jugada más detectados
- Falsos positivos frecuentes

Para MVP, priorizar Precision@10. Es preferible sugerir 10 clips buenos y perder algunos highlights que generar 40 clips malos.

---

## Criterios de aceptación del MVP

El MVP se considera funcional si:

1. Puede procesar un video local `.mp4`.
2. Genera `candidates.json`.
3. Exporta al menos 10 clips candidatos.
4. Crea un reel final.
5. Cada candidato tiene:
   - start_time
   - end_time
   - score
   - reasons
   - clip_path
6. La UI de revisión permite aprobar/rechazar clips.
7. El pipeline corre aunque el VLM esté desactivado.
8. El código está organizado y documentado.
9. Los parámetros de scoring se pueden cambiar desde YAML.

---

## Primera implementación sugerida

Implementar en este orden:

### Fase 1: infraestructura

- Crear estructura de carpetas.
- Crear config.
- Crear schemas.
- Crear metadata y FFmpeg helpers.
- Crear CLI mínima.

### Fase 2: señales baratas

- Frame sampling.
- Audio peaks.
- Motion score con OpenCV.
- Scene detection.

### Fase 3: YOLO

- Detección de personas con fallback YOLO.
- Integrar modelo custom si está disponible.
- Detección de balón/aro si el modelo lo soporta.

### Fase 4: candidatos

- Generar segmentos.
- Scorear.
- Fusionar segmentos cercanos.
- Exportar JSON/CSV.

### Fase 5: cortes

- Cortar clips.
- Crear reel.

### Fase 6: revisión humana

- Streamlit o Gradio.
- Guardar anotaciones.

### Fase 7: VLM local

- Clasificar solo top candidatos.
- Ajustar ranking final.

### Fase 8: MCP

- Exponer herramientas principales para Claude.

---

## Ejemplo de salida final esperada

```json
[
  {
    "id": "game001_0001",
    "video_path": "videos/input/game001.mp4",
    "start_time": 734.2,
    "end_time": 752.8,
    "score": 8.9,
    "reasons": [
      "ball near hoop",
      "high motion",
      "audio peak",
      "multiple players near basket"
    ],
    "signals": {
      "ball_near_hoop": 1.0,
      "motion_spike": 0.87,
      "audio_peak": 0.91,
      "players_near_paint": 4
    },
    "play_type": "score",
    "confidence": 0.76,
    "clip_path": "videos/clips/game001/game001_0001.mp4"
  }
]
```

---

## Notas de diseño importantes

1. Diseñar el sistema como laboratorio experimental, no como producto cerrado.
2. Todo debe poder correr localmente.
3. Todo timestamp debe ser auditable.
4. Cada candidato debe explicar por qué fue elegido.
5. La UI de revisión es esencial para mejorar el sistema.
6. El VLM debe ser opcional.
7. La detección perfecta de highlights no es realista al inicio.
8. El objetivo inicial es encontrar buenos candidatos, no reemplazar al editor humano.
9. El sistema debe permitir cambiar pesos y thresholds sin modificar código.
10. Guardar outputs intermedios para depurar.

---

## Tareas concretas para Claude

Construye este proyecto completo en Python siguiendo la arquitectura anterior.

Prioriza que el MVP corra de punta a punta con heurísticas aunque los modelos específicos de basketball todavía no estén fine-tuned.

Entrega:

1. Código fuente.
2. README con instalación.
3. Configs YAML.
4. CLI funcional.
5. Pipeline local end-to-end.
6. UI simple de revisión.
7. MCP server opcional si el MVP base ya funciona.
8. Tests básicos.

No bloquees la implementación por falta de un modelo custom de basketball. Implementa fallback con YOLO genérico, audio peaks y motion detection.

