"""
SmartBasket — Video I/O
Metadata de video, validación de FFmpeg, creación de directorios de salida.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from loguru import logger


def get_video_metadata(video_path: str | Path) -> dict:
    """
    Obtiene metadata del video usando ffprobe.
    Retorna dict con: duration, fps, width, height, codec, size_bytes.
    """
    p = Path(video_path)
    if not p.exists():
        raise FileNotFoundError(f"Video no encontrado: {p}")

    cmd = [
        "ffprobe",
        "-v", "quiet",
        "-print_format", "json",
        "-show_streams",
        "-show_format",
        str(p),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    probe = json.loads(result.stdout)

    # Buscar el stream de video
    video_stream = next(
        (s for s in probe.get("streams", []) if s.get("codec_type") == "video"),
        None,
    )
    if not video_stream:
        raise ValueError(f"No se encontró stream de video en: {p}")

    # Calcular FPS desde r_frame_rate (e.g., "30000/1001" o "30/1")
    fps_raw = video_stream.get("r_frame_rate", "30/1")
    num, den = map(int, fps_raw.split("/"))
    fps = num / den if den != 0 else 30.0

    # Duración (priorizar stream, luego format)
    duration = float(
        video_stream.get("duration")
        or probe.get("format", {}).get("duration", 0)
    )

    metadata = {
        "path": str(p.resolve()),
        "duration": duration,
        "fps": round(fps, 3),
        "width": int(video_stream.get("width", 0)),
        "height": int(video_stream.get("height", 0)),
        "codec": video_stream.get("codec_name", "unknown"),
        "size_bytes": int(probe.get("format", {}).get("size", 0)),
        "nb_frames": int(video_stream.get("nb_frames", 0) or 0),
    }

    logger.info(
        f"Video: {p.name} | "
        f"{metadata['width']}x{metadata['height']} | "
        f"{metadata['fps']} fps | "
        f"{metadata['duration']:.1f}s | "
        f"{metadata['codec']}"
    )
    return metadata


def validate_ffmpeg() -> str:
    """Verifica que FFmpeg esté disponible. Retorna la versión."""
    try:
        result = subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True, text=True, check=True,
        )
        version_line = result.stdout.split("\n")[0]
        logger.info(f"FFmpeg disponible: {version_line}")
        return version_line
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        raise RuntimeError("FFmpeg no está instalado o no está en el PATH") from e


def ensure_output_dirs(base_dir: str | Path, game_id: str) -> dict[str, Path]:
    """
    Crea todos los directorios de salida para un partido.
    Retorna dict con las rutas.
    """
    base = Path(base_dir)
    dirs = {
        "frames": base / "data" / "frames" / game_id,
        "audio": base / "data" / "audio",
        "detections": base / "data" / "detections",
        "candidates": base / "data" / "candidates",
        "annotations": base / "data" / "annotations",
        "reports": base / "data" / "reports",
        "clips": base / "videos" / "clips" / game_id,
        "reels": base / "videos" / "reels",
    }
    for name, path in dirs.items():
        path.mkdir(parents=True, exist_ok=True)
        logger.debug(f"Dir creado: {name} → {path}")
    return dirs
