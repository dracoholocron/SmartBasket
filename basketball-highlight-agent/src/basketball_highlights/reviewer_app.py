"""
SmartBasket — Reviewer App v2 (Streamlit)
UI completa para:
  - Lanzar el pipeline desde la interfaz
  - Marcar aros manualmente sobre un frame del video
  - Ver la consola de progreso en tiempo real
  - Revisar, aprobar o rechazar clips candidatos
"""
from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import time
from pathlib import Path

import cv2
import numpy as np
import pandas as pd
import streamlit as st
import yaml
from PIL import Image

from basketball_highlights.schemas import CandidateSegment, HumanAnnotation
from basketball_highlights.utils import seconds_to_timecode, ensure_dir, save_json

# ─── Config de página ─────────────────────────────────────────────────────────
st.set_page_config(
    page_title="SmartBasket Reviewer",
    page_icon="🏀",
    layout="wide",
    initial_sidebar_state="expanded",
)

# CSS personalizado
st.markdown("""
<style>
    .console-box {
        background-color: #0d1117;
        color: #7ee787;
        font-family: 'Courier New', monospace;
        font-size: 12px;
        padding: 12px;
        border-radius: 8px;
        border: 2px solid #58a6ff;
        height: 280px;
        overflow-y: auto;
        white-space: pre-wrap;
        word-break: break-all;
    }
    .console-empty {
        background-color: #0d1117;
        color: #484f58;
        font-family: 'Courier New', monospace;
        font-size: 13px;
        padding: 20px;
        border-radius: 8px;
        border: 2px dashed #30363d;
        height: 280px;
        display: flex;
        align-items: center;
        justify-content: center;
        text-align: center;
    }
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
    }
    .status-running { color: #f0a500; font-weight: bold; }
    .status-done    { color: #3fb950; font-weight: bold; }
</style>
""", unsafe_allow_html=True)

PLAY_TYPES = [
    "score", "three_pointer", "block", "steal",
    "assist", "rebound", "fast_break", "foul", "unknown"
]

VIDEOS_INPUT_DIR = Path("/app/videos/input")
VIDEOS_CLIPS_DIR = Path("/app/videos/clips")
VIDEOS_REELS_DIR = Path("/app/videos/reels")
CANDIDATES_DIR   = Path("/app/data/candidates")
ANNOTATIONS_DIR  = Path("/app/data/annotations")
CONFIGS_DIR      = Path("/app/configs")
DATA_DIR         = Path("/app/data")
HISTORY_DIR      = Path("/app/data/history")


# ─── Estado de sesión ─────────────────────────────────────────────────────────
if "console_log"        not in st.session_state: st.session_state.console_log = []
if "pipeline_running"   not in st.session_state: st.session_state.pipeline_running = False
if "pipeline_done"      not in st.session_state: st.session_state.pipeline_done = False
if "selected_video"     not in st.session_state: st.session_state.selected_video = None
if "hoop_coords"        not in st.session_state: st.session_state.hoop_coords = []
if "active_tab"         not in st.session_state: st.session_state.active_tab = 0

# ─── Helpers ──────────────────────────────────────────────────────────────────

def load_candidates(json_path: str) -> list[CandidateSegment]:
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return [CandidateSegment(**item) for item in data]


def load_annotations(annotation_path: str) -> dict[str, HumanAnnotation]:
    p = Path(annotation_path)
    if not p.exists():
        return {}
    with open(p, "r", encoding="utf-8") as f:
        data = json.load(f)
    return {item["candidate_id"]: HumanAnnotation(**item) for item in data}


def save_annotations(annotations: dict[str, HumanAnnotation], annotation_path: str):
    ensure_dir(Path(annotation_path).parent)
    data = [ann.model_dump() for ann in annotations.values()]
    with open(annotation_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def get_latest_candidates_file() -> str | None:
    if CANDIDATES_DIR.exists():
        files = list(CANDIDATES_DIR.glob("*_candidates.json"))
        if files:
            return max(files, key=lambda p: p.stat().st_mtime).as_posix()
    return None


def extract_video_frame(video_path: str, timestamp_s: float = 5.0) -> np.ndarray | None:
    """Extrae un frame del video en el segundo indicado."""
    try:
        cap = cv2.VideoCapture(video_path)
        cap.set(cv2.CAP_PROP_POS_MSEC, timestamp_s * 1000)
        ret, frame = cap.read()
        cap.release()
        if ret:
            return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    except Exception:
        pass
    return None


def archive_current_run(game_id: str):
    """Mueve los resultados actuales a la carpeta de historial antes de una nueva corrida."""
    import shutil
    from datetime import datetime
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_path = HISTORY_DIR / game_id / timestamp
    ensure_dir(archive_path)
    
    # 1. Mover JSON de candidatos
    json_file = CANDIDATES_DIR / f"{game_id}_candidates.json"
    if json_file.exists():
        shutil.copy(str(json_file), str(archive_path / f"{game_id}_candidates.json"))
        
    # 2. Copiar Clips
    clips_folder = VIDEOS_CLIPS_DIR / game_id
    if clips_folder.exists() and any(clips_folder.iterdir()):
        archive_clips = archive_path / "clips"
        shutil.copytree(str(clips_folder), str(archive_clips), dirs_exist_ok=True)
        
    print(f"📦 Run anterior archivado en: {archive_path}")
    return timestamp


def save_hoop_coords_to_config(coords: list[dict]):
    """Guarda las coordenadas de los aros en models.yaml."""
    config_path = CONFIGS_DIR / "models.yaml"
    if not config_path.exists():
        return
    with open(config_path, "r") as f:
        cfg = yaml.safe_load(f)

    regions = []
    for i, c in enumerate(coords):
        margin = 80
        regions.append({
            "name": f"hoop_{i+1}",
            "x1": max(0, int(c["x"]) - margin),
            "y1": max(0, int(c["y"]) - margin),
            "x2": int(c["x"]) + margin,
            "y2": int(c["y"]) + margin,
        })

    if "court" not in cfg:
        cfg["court"] = {}
    cfg["court"]["manual_hoop_regions"] = {
        "enabled": True,
        "regions": regions,
    }

    with open(config_path, "w") as f:
        yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True)


def run_pipeline_thread(video_filename: str, log_queue: queue.Queue):
    """Ejecuta el pipeline en un hilo separado y manda output a la queue."""
    # Usar rutas del host Windows para los volúmenes (Docker Desktop en Windows)
    # HOST_PROJECT_DIR viene del docker-compose como ${PWD} → C:\code\SmartBasket
    host_dir = os.environ.get("HOST_PROJECT_DIR", "C:\\code\\SmartBasket")
    # Docker en Windows acepta tanto barras normales como invertidas en volúmenes
    host_dir_fwd = host_dir.replace("\\", "/")

    cmd = [
        "docker", "run", "--rm",
        "--runtime", "nvidia",
        "-e", "NVIDIA_VISIBLE_DEVICES=all",
        "-e", "NVIDIA_DRIVER_CAPABILITIES=compute,utility,video",
        "-e", "PYTHONPATH=/app/src",
        "-e", "PYTORCH_CUDA_ALLOC_CONF=max_split_size_mb:512",
        "-v", f"{host_dir_fwd}/basketball-highlight-agent/videos:/app/videos",
        "-v", f"{host_dir_fwd}/basketball-highlight-agent/data:/app/data",
        "-v", f"{host_dir_fwd}/basketball-highlight-agent/models:/app/models",
        "-v", f"{host_dir_fwd}/basketball-highlight-agent/configs:/app/configs",
        "-v", f"{host_dir_fwd}/basketball-highlight-agent/src:/app/src",
        "-w", "/app",
        "--network", "smartbasket-net",
        "smartbasket-pipeline:latest",
        "python", "-m", "basketball_highlights.cli",
        "analyze", f"videos/input/{video_filename}",
    ]
    # Archivo de log persistente para no perder el progreso al refrescar
    log_file_path = DATA_DIR / "reports" / f"{video_filename}_pipeline.log"
    ensure_dir(log_file_path.parent)

    log_queue.put(f"🚀 Iniciando análisis de: {video_filename}\n")
    log_queue.put(f"▶ Ejecutando: {' '.join(cmd)}\n{'─'*60}\n")
    
    try:
        with open(log_file_path, "w", encoding="utf-8") as f_log:
            header = f"SmartBasket Pipeline Log - {video_filename}\n{'='*60}\n"
            f_log.write(header)
            
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True,
            )

            for line in proc.stdout:
                log_queue.put(line)
                f_log.write(line)
                f_log.flush()

            proc.wait()
            finish_msg = f"\n{'─'*60}\n✅ Pipeline terminó con código {proc.returncode}.\n"
            log_queue.put(finish_msg)
            f_log.write(finish_msg)
    except Exception as e:
        error_msg = f"\n❌ Error lanzando pipeline: {e}\n"
        log_queue.put(error_msg)
        with open(log_file_path, "a", encoding="utf-8") as f_log:
            f_log.write(error_msg)
    finally:
        log_queue.put("__DONE__")


# ─── Sidebar ──────────────────────────────────────────────────────────────────
st.sidebar.image("https://img.icons8.com/emoji/96/basketball-emoji.png", width=60)
st.sidebar.title("SmartBasket")
st.sidebar.caption("Agente local de highlights de basketball")
st.sidebar.divider()

# Estado del pipeline
if st.session_state.pipeline_running:
    st.sidebar.markdown('<p class="status-running">⏳ Pipeline en ejecución...</p>', unsafe_allow_html=True)
elif st.session_state.pipeline_done:
    st.sidebar.markdown('<p class="status-done">✅ Último análisis completado</p>', unsafe_allow_html=True)
else:
    st.sidebar.markdown("**Estado:** Inactivo")

st.sidebar.divider()
st.sidebar.caption("© SmartBasket — Pipeline local")

# ─── Tabs principales ─────────────────────────────────────────────────────────
tab_analisis, tab_revision = st.tabs(["🚀 Análisis & Pipeline", "🎬 Revisión de Highlights"])



# ══════════════════════════════════════════════════════════════════════════════
# TAB 1: ANÁLISIS & PIPELINE
# ══════════════════════════════════════════════════════════════════════════════
with tab_analisis:
    st.title("🚀 Análisis de Video")

    # ─── Sección: Selección de video ──────────────────────────────────────────
    st.subheader("📂 Seleccionar Video de Entrada")

    available_videos = sorted(VIDEOS_INPUT_DIR.glob("*.mp4")) if VIDEOS_INPUT_DIR.exists() else []
    video_names = [v.name for v in available_videos]

    if not video_names:
        st.warning("⚠️ No se encontraron videos en `/app/videos/input/`. Copia tu video `.mp4` a esa carpeta.")
        selected_video_name = None
    else:
        col_sel, col_btn = st.columns([3, 1])
        with col_sel:
            selected_video_name = st.selectbox(
                "Video a analizar:",
                options=video_names,
                index=0,
                key="video_selector",
            )
            st.session_state.selected_video = selected_video_name
            
            # Cargar log persistente si existe para este video
            log_file = DATA_DIR / "reports" / f"{selected_video_name}_pipeline.log"
            if log_file.exists() and not st.session_state.console_log:
                with open(log_file, "r", encoding="utf-8") as f:
                    st.session_state.console_log = f.readlines()

        with col_btn:
            st.write("")
            st.write("")
            launch_btn = st.button(
                "🎯 Get Highlights",
                disabled=st.session_state.pipeline_running,
                use_container_width=True,
                type="primary",
            )

    # ─── Sección: Marcador de Aros ────────────────────────────────────────────
    st.divider()
    st.subheader("🏀 Marcador Manual de Aros")
    st.caption("Selecciona un frame del video y haz clic para marcar la posición de cada aro. "
               "Estos datos se usarán para mejorar la detección de canastas.")

    if selected_video_name:
        video_full_path = str(VIDEOS_INPUT_DIR / selected_video_name)

        col_ts, col_load = st.columns([2, 1])
        with col_ts:
            frame_ts = st.slider("Segundo del frame a mostrar", 0, 300, 10, key="frame_ts")
        with col_load:
            st.write("")
            load_frame_btn = st.button("📷 Cargar Frame", use_container_width=True)

        if load_frame_btn or "hoop_frame" not in st.session_state:
            with st.spinner("Extrayendo frame..."):
                frame = extract_video_frame(video_full_path, float(frame_ts))
                if frame is not None:
                    st.session_state.hoop_frame = frame
                    st.session_state.hoop_frame_shape = (frame.shape[1], frame.shape[0])  # (w, h)
                else:
                    st.session_state.hoop_frame = None

        if st.session_state.get("hoop_frame") is not None:
            frame = st.session_state.hoop_frame
            orig_w, orig_h = frame.shape[1], frame.shape[0]
            display_w = 720
            scale = display_w / orig_w
            display_h = int(orig_h * scale)
            frame_resized = cv2.resize(frame, (display_w, display_h))

            try:
                from streamlit_drawable_canvas import st_canvas
                st.markdown("**Haz clic sobre los aros en la imagen** (máximo 2 puntos):")
                canvas_result = st_canvas(
                    fill_color="rgba(255, 0, 0, 0.3)",
                    stroke_width=3,
                    stroke_color="#FF4500",
                    background_image=Image.fromarray(frame_resized),
                    update_streamlit=True,
                    height=display_h,
                    width=display_w,
                    drawing_mode="point",
                    point_display_radius=12,
                    key="hoop_canvas",
                )

                if canvas_result.json_data is not None:
                    objects = canvas_result.json_data.get("objects", [])
                    coords_scaled = [
                        {"x": int(o["left"] / scale), "y": int(o["top"] / scale)}
                        for o in objects if o.get("type") == "circle"
                    ]
                    if coords_scaled:
                        st.info(f"📍 {len(coords_scaled)} aro(s) marcado(s): "
                                + " | ".join([f"({c['x']}, {c['y']})" for c in coords_scaled]))
                        if st.button("💾 Guardar Posición de Aros", type="primary"):
                            save_hoop_coords_to_config(coords_scaled)
                            st.success("✅ Posición de aros guardada en `configs/models.yaml`. "
                                       "El próximo análisis usará estas coordenadas.")
            except ImportError:
                st.info("📍 El marcador de aros estará disponible tras reconstruir el contenedor con las nuevas dependencias.")
                # Fallback: inputs manuales
                st.markdown("**Por ahora, ingresa las coordenadas manualmente:**")
                col1, col2, col3, col4 = st.columns(4)
                x1 = col1.number_input("Aro 1 — X", 0, orig_w, orig_w // 4)
                y1 = col2.number_input("Aro 1 — Y", 0, orig_h, orig_h // 3)
                x2 = col3.number_input("Aro 2 — X", 0, orig_w, 3 * orig_w // 4)
                y2 = col4.number_input("Aro 2 — Y", 0, orig_h, orig_h // 3)
                st.image(frame_resized, caption="Frame actual (usa las coordenadas de arriba)")
                if st.button("💾 Guardar Coordenadas de Aros", type="primary"):
                    save_hoop_coords_to_config([{"x": x1, "y": y1}, {"x": x2, "y": y2}])
                    st.success("✅ Coordenadas de aros guardadas en `configs/models.yaml`.")
        else:
            st.info("👆 Haz clic en 'Cargar Frame' para extraer un fotograma del video.")
    else:
        st.info("Selecciona un video arriba para poder marcar los aros.")

    # ─── Sección: Consola de Pipeline ─────────────────────────────────────────
    st.divider()
    st.subheader("🖥️ Consola de Pipeline")

    # Lanzar pipeline si se presionó el botón
    if launch_btn and selected_video_name and not st.session_state.pipeline_running:
        # Archivar run actual antes de empezar uno nuevo
        game_id_to_run = selected_video_name.replace(".mp4", "")
        archive_current_run(game_id_to_run)
        
        st.session_state.pipeline_running = True
        st.session_state.pipeline_done = False
        st.session_state.console_log = [f"🚀 Iniciando análisis de: {selected_video_name}\n"]
        log_q = queue.Queue()
        st.session_state._log_queue = log_q
        thread = threading.Thread(
            target=run_pipeline_thread,
            args=(selected_video_name, log_q),
            daemon=True,
        )
        thread.start()
        st.rerun()

    # Leer logs de la queue si el pipeline está corriendo
    if st.session_state.pipeline_running:
        log_q = st.session_state.get("_log_queue")
        if log_q:
            lines_read = 0
            while lines_read < 50:
                try:
                    line = log_q.get_nowait()
                    if line == "__DONE__":
                        st.session_state.pipeline_running = False
                        st.session_state.pipeline_done = True
                        break
                    st.session_state.console_log.append(line)
                    lines_read += 1
                except queue.Empty:
                    break
            time.sleep(0.5)
            st.rerun()

    # Mostrar consola con componente nativo de Streamlit
    if st.session_state.console_log:
        console_text = "".join(st.session_state.console_log[-200:])
        st.code(console_text, language=None)
    else:
        st.info("⏳ Esperando inicio del pipeline... Selecciona un video y presiona **🎯 Get Highlights**")

    col_clear, col_refresh = st.columns([1, 1])
    with col_clear:
        if st.button("🗑️ Limpiar consola"):
            st.session_state.console_log = []
            st.rerun()
    with col_refresh:
        if st.session_state.pipeline_running:
            if st.button("🔄 Actualizar progreso"):
                st.rerun()
        else:
            st.caption("Pipeline detenido")



# ══════════════════════════════════════════════════════════════════════════════
# TAB 2: REVISIÓN DE HIGHLIGHTS
# ══════════════════════════════════════════════════════════════════════════════
with tab_revision:
    st.title("🎬 Revisión de Highlights")

    # ─── Selector de partida a revisar ────────────────────────────────────────
    all_json = list(CANDIDATES_DIR.glob("*_candidates.json")) if CANDIDATES_DIR.exists() else []
    games_with_results = sorted(list(set([f.name.replace("_candidates.json", "") for f in all_json])), reverse=True)
    
    if not games_with_results:
        st.warning("⚠️ No hay candidatos generados todavía. Ve a la pestaña **🚀 Análisis** y lanza el pipeline primero.")
        st.stop()
        
    col_g, col_v = st.columns(2)
    with col_g:
        selected_game = st.selectbox("📁 Seleccionar partido:", options=games_with_results)
    
    # Buscar versiones en el historial
    history_versions = []
    game_history = HISTORY_DIR / selected_game
    if game_history.exists():
        history_versions = sorted([d.name for d in game_history.iterdir() if d.is_dir()], reverse=True)
    
    with col_v:
        version_options = ["Actual (última extracción)"] + history_versions
        selected_version = st.selectbox("⏳ Versión de extracción:", options=version_options)

    # Determinar rutas según la versión seleccionada
    is_latest = selected_version == version_options[0]
    if is_latest:
        json_path = CANDIDATES_DIR / f"{selected_game}_candidates.json"
        clips_base_url = f"http://localhost:8082/clips/{selected_game}"
        clips_base_path = VIDEOS_CLIPS_DIR / selected_game
    else:
        json_path = HISTORY_DIR / selected_game / selected_version / f"{selected_game}_candidates.json"
        clips_base_url = f"http://localhost:8082/history/{selected_game}/{selected_version}/clips"
        clips_base_path = HISTORY_DIR / selected_game / selected_version / "clips"
    candidates_file = str(json_path)
    annotations_file = (ANNOTATIONS_DIR / f"{selected_game}_annotations.json").as_posix()

    col_filter1, col_filter2 = st.columns([2, 1])
    with col_filter1:
        min_score = st.slider("Score mínimo a mostrar", 0.0, 15.0, 1.0, 0.25)
    with col_filter2:
        show_vlm_only = st.checkbox("Solo clips revisados por VLM", value=False)

    # ─── Carga de datos ───────────────────────────────────────────────────────
    try:
        candidates = load_candidates(candidates_file)
    except Exception as e:
        st.error(f"Error cargando candidatos: {e}")
        st.stop()

    annotations = load_annotations(annotations_file)

    filtered = [c for c in candidates if c.score >= min_score]
    if show_vlm_only:
        filtered = [c for c in filtered if c.vlm_reviewed]

    # ─── Estadísticas ─────────────────────────────────────────────────────────
    col1, col2, col3, col4 = st.columns(4)
    approved_count  = sum(1 for a in annotations.values() if a.approved)
    rejected_count  = sum(1 for a in annotations.values() if not a.approved)
    pending_count   = max(0, len(filtered) - len(annotations))

    col1.metric("Total candidatos", len(filtered))
    col2.metric("Aprobados ✅", approved_count)
    col3.metric("Rechazados ❌", rejected_count)
    col4.metric("Pendientes ⏳", pending_count)

    # ─── Reel path ────────────────────────────────────────────────────────────
    reel_file = VIDEOS_REELS_DIR / f"{selected_game}_top10.mp4"
    if reel_file.exists():
        with st.expander("🎞️ Ver Reel Completo", expanded=False):
            if st.session_state.get("show_reel"):
                st.video(str(reel_file))
                if st.button("⏹️ Cerrar Reel"):
                    st.session_state.show_reel = False
                    st.rerun()
            else:
                if st.button("▶️ Cargar y reproducir Reel Completo", type="primary"):
                    st.session_state.show_reel = True
                    st.rerun()
            st.caption(f"Reel generado: `{reel_file}`")

    # ─── Tabla resumen ────────────────────────────────────────────────────────
    with st.expander("📊 Tabla de candidatos", expanded=False):
        if filtered:
            df = pd.DataFrame([{
                "ID":       c.id,
                "Inicio":   seconds_to_timecode(c.start_time),
                "Fin":      seconds_to_timecode(c.end_time),
                "Duración": f"{c.duration:.1f}s",
                "Score":    c.score,
                "Tipo":     c.play_type or "—",
                "VLM":      "✓" if c.vlm_reviewed else "",
                "Estado": (
                    "✅" if annotations.get(c.id) and annotations[c.id].approved
                    else "❌" if annotations.get(c.id)
                    else "⏳"
                ),
                "Razones":  ", ".join(c.reasons[:3]),
            } for c in filtered])
            st.dataframe(df, use_container_width=True, hide_index=True)
        else:
            st.info("No hay candidatos que cumplan con el filtro de score mínimo.")

    st.divider()

    # ─── Revisión individual de clips ─────────────────────────────────────────
    st.divider()
    st.subheader("🎬 Revisión de clips")

    if not filtered:
        st.info("Ajusta el slider de score mínimo para ver los candidatos disponibles.")

    for candidate in filtered:
        ann = annotations.get(candidate.id)
        status_icon = "✅" if (ann and ann.approved) else "❌" if ann else "⏳"

        with st.expander(
            f"{status_icon} [{candidate.id}] Score: {candidate.score:.1f} | "
            f"{seconds_to_timecode(candidate.start_time)} → {seconds_to_timecode(candidate.end_time)} "
            f"({candidate.duration:.1f}s) | {candidate.play_type or 'sin clasificar'}",
            expanded=False,  # Colapsados por defecto para no cargar todos los videos a la vez
        ):
            col_video, col_info = st.columns([2, 1])

            with col_video:
                # Usar la ruta física directa con carga bajo demanda para máxima protección de memoria RAM
                video_file = clips_base_path / f"{candidate.id}.mp4"
                if video_file.exists():
                    is_active = st.session_state.get("active_video_id") == candidate.id
                    if is_active:
                        video_url = f"{clips_base_url}/{candidate.id}.mp4"
                        st.markdown(
                            f'<video controls autoplay style="width:100%;border-radius:8px;" '
                            f'preload="metadata"><source src="{video_url}" type="video/mp4"></video>',
                            unsafe_allow_html=True,
                        )
                        if st.button("⏹️ Cerrar reproductor", key=f"close_{candidate.id}"):
                            st.session_state.active_video_id = None
                            st.rerun()
                    else:
                        if st.button("▶️ Cargar y reproducir video", key=f"play_{candidate.id}", type="primary"):
                            st.session_state.active_video_id = candidate.id
                            st.rerun()
                else:
                    st.info(f"📁 Clip no encontrado en esta versión: `{video_file.name}`")




            with col_info:
                st.markdown(f"**Score:** `{candidate.score:.2f}`")
                st.markdown(f"**Tipo (VLM):** `{candidate.play_type or 'sin clasificar'}`")
                if candidate.confidence is not None:
                    st.markdown(f"**Confianza:** `{candidate.confidence:.0%}`")
                st.markdown(f"**VLM revisado:** {'✓' if candidate.vlm_reviewed else 'No'}")

                st.markdown("**Razones:**")
                for r in candidate.reasons:
                    st.markdown(f"  - `{r}`")

                st.markdown("**Señales:**")
                for k, v in candidate.signals.items():
                    st.markdown(f"  - `{k}`: {v:.2f}")

            # ─── Controles de anotación ───────────────────────────────────────
            st.markdown("---")
            with st.form(key=f"form_{candidate.id}"):
                form_col1, form_col2 = st.columns(2)
                with form_col1:
                    approved = st.radio(
                        "Decisión",
                        options=["Aprobar ✅", "Rechazar ❌"],
                        index=0 if (not ann or ann.approved) else 1,
                        horizontal=True,
                    )
                    corrected_type = st.selectbox(
                        "Tipo de jugada",
                        options=["(no cambiar)"] + PLAY_TYPES,
                        index=0,
                    )

                with form_col2:
                    start_offset = st.number_input(
                        "Ajustar inicio (segundos)",
                        value=candidate.start_time,
                        step=0.5,
                    )
                    end_offset = st.number_input(
                        "Ajustar fin (segundos)",
                        value=candidate.end_time,
                        step=0.5,
                    )

                notes = st.text_input("Notas", value=ann.notes if ann else "")

                submitted = st.form_submit_button("💾 Guardar anotación", use_container_width=True)
                if submitted:
                    annotations[candidate.id] = HumanAnnotation(
                        candidate_id=candidate.id,
                        approved="Aprobar" in approved,
                        corrected_play_type=corrected_type if corrected_type != "(no cambiar)" else candidate.play_type,
                        corrected_start_time=start_offset,
                        corrected_end_time=end_offset,
                        notes=notes,
                    )
                    save_annotations(annotations, annotations_file)
                    st.success(f"✅ Anotación guardada: {candidate.id}")
                    st.rerun()

    # ─── Footer ───────────────────────────────────────────────────────────────
    st.divider()
    if st.button("💾 Exportar candidatos aprobados"):
        approved_ids = [cid for cid, ann in annotations.items() if ann.approved]
        approved_candidates = [c for c in candidates if c.id in approved_ids]
        out_path = ANNOTATIONS_DIR / f"{selected_game}_approved.json"
        ensure_dir(out_path.parent)
        save_json([c.model_dump() for c in approved_candidates], out_path)
        st.success(f"✅ {len(approved_candidates)} candidatos aprobados exportados → `{out_path}`")
