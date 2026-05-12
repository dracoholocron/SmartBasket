"""
SmartBasket — Frame Sampler
Extrae frames del video a distintas frecuencias usando FFmpeg.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from loguru import logger
from tqdm import tqdm

from basketball_highlights.schemas import FrameInfo


def sample_frames(
    video_path: str | Path,
    output_dir: str | Path,
    fps: float,
    start_time: float = 0.0,
    end_time: float | None = None,
) -> list[FrameInfo]:
    """
    Extrae frames del video a la frecuencia indicada usando FFmpeg.
    
    Args:
        video_path: Ruta al video de entrada.
        output_dir: Directorio de salida para los frames.
        fps: Frames por segundo a extraer.
        start_time: Timestamp de inicio (segundos).
        end_time: Timestamp de fin (segundos). None = hasta el final.
    
    Returns:
        Lista de FrameInfo con ruta, timestamp e índice de cada frame.
    """
    video_path = Path(video_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Construir comando FFmpeg
    cmd = ["ffmpeg", "-y", "-loglevel", "error"]
    if start_time > 0:
        cmd += ["-ss", str(start_time)]
    cmd += ["-i", str(video_path)]
    if end_time is not None:
        cmd += ["-t", str(end_time - start_time)]
    cmd += [
        "-vf", f"fps={fps}",
        "-q:v", "2",          # calidad JPEG alta
        str(output_dir / "frame_%06d.jpg"),
    ]

    logger.info(f"Extrayendo frames a {fps} fps desde {video_path.name}...")
    subprocess.run(cmd, check=True)

    # Recolectar frames generados y calcular timestamps
    frame_files = sorted(output_dir.glob("frame_*.jpg"))
    frames = []
    interval = 1.0 / fps

    for i, frame_path in enumerate(frame_files):
        ts = start_time + i * interval
        frames.append(FrameInfo(
            frame_path=str(frame_path),
            timestamp=round(ts, 3),
            frame_index=i,
        ))

    logger.info(f"  → {len(frames)} frames extraídos en {output_dir}")
    return frames


def compute_motion_scores(frames: list[FrameInfo]) -> list[dict]:
    """
    Calcula un score de movimiento entre frames consecutivos usando OpenCV.
    
    Compara diferencia absoluta entre frames consecutivos. Alto valor = mucho movimiento.
    
    Returns:
        Lista de dicts con: timestamp, motion_score, frame_path.
    """
    import cv2
    import numpy as np

    results = []
    prev_gray = None

    logger.info(f"Calculando motion scores en {len(frames)} frames...")

    for frame_info in tqdm(frames, desc="Motion", unit="frame"):
        img = cv2.imread(frame_info.frame_path)
        if img is None:
            logger.warning(f"No se pudo leer: {frame_info.frame_path}")
            results.append({
                "timestamp": frame_info.timestamp,
                "motion_score": 0.0,
                "frame_path": frame_info.frame_path,
            })
            continue

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        gray = cv2.resize(gray, (320, 240))  # reducir para velocidad

        if prev_gray is not None:
            diff = cv2.absdiff(gray, prev_gray)
            motion_score = float(np.mean(diff)) / 255.0
        else:
            motion_score = 0.0

        results.append({
            "timestamp": frame_info.timestamp,
            "motion_score": round(motion_score, 4),
            "frame_path": frame_info.frame_path,
        })
        prev_gray = gray

    return results
