"""
SmartBasket — Utils
Helpers de logging, paths y timestamps.
"""
from __future__ import annotations

import sys
import json
from pathlib import Path
from datetime import datetime

from loguru import logger


# ─────────────────────────────────────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────────────────────────────────────

def setup_logging(level: str = "INFO") -> None:
    """Configura loguru para output bonito en consola."""
    logger.remove()
    logger.add(
        sys.stderr,
        level=level,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
            "<level>{message}</level>"
        ),
        colorize=True,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Timestamps y timecodes
# ─────────────────────────────────────────────────────────────────────────────

def seconds_to_timecode(seconds: float) -> str:
    """Convierte segundos a formato HH:MM:SS.mmm"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}"


def timecode_to_seconds(tc: str) -> float:
    """Convierte HH:MM:SS o MM:SS a segundos."""
    parts = tc.strip().split(":")
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    elif len(parts) == 2:
        return int(parts[0]) * 60 + float(parts[1])
    return float(parts[0])


# ─────────────────────────────────────────────────────────────────────────────
# Paths y directorios
# ─────────────────────────────────────────────────────────────────────────────

def ensure_dir(path: str | Path) -> Path:
    """Crea el directorio si no existe y lo retorna."""
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_game_id(video_path: str | Path) -> str:
    """Extrae el ID del partido desde el nombre del archivo."""
    return Path(video_path).stem


def get_output_dirs(base_dir: str | Path, game_id: str) -> dict[str, Path]:
    """Retorna los paths de salida para un partido."""
    base = Path(base_dir)
    dirs = {
        "frames": ensure_dir(base / "data" / "frames" / game_id),
        "audio": ensure_dir(base / "data" / "audio"),
        "detections": ensure_dir(base / "data" / "detections"),
        "candidates": ensure_dir(base / "data" / "candidates"),
        "annotations": ensure_dir(base / "data" / "annotations"),
        "reports": ensure_dir(base / "data" / "reports"),
        "clips": ensure_dir(base / "videos" / "clips" / game_id),
        "reels": ensure_dir(base / "videos" / "reels"),
    }
    return dirs


# ─────────────────────────────────────────────────────────────────────────────
# JSON helpers
# ─────────────────────────────────────────────────────────────────────────────

def save_json(data: list | dict, path: str | Path, indent: int = 2) -> None:
    """Guarda datos como JSON con serialización de Pydantic."""
    p = Path(path)
    ensure_dir(p.parent)
    with open(p, "w", encoding="utf-8") as f:
        if hasattr(data, "model_dump"):
            json.dump(data.model_dump(), f, indent=indent, ensure_ascii=False)
        elif isinstance(data, list) and data and hasattr(data[0], "model_dump"):
            json.dump([item.model_dump() for item in data], f, indent=indent, ensure_ascii=False)
        else:
            json.dump(data, f, indent=indent, ensure_ascii=False, default=str)
    logger.debug(f"JSON guardado: {p}")


def load_json(path: str | Path) -> list | dict:
    """Carga datos desde JSON."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ─────────────────────────────────────────────────────────────────────────────
# Misc
# ─────────────────────────────────────────────────────────────────────────────

def format_duration(seconds: float) -> str:
    """Formatea duración en string legible (e.g. '1h 23m 45s')"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if h > 0:
        return f"{h}h {m}m {s}s"
    if m > 0:
        return f"{m}m {s}s"
    return f"{s}s"


def now_tag() -> str:
    """Tag de tiempo actual para nombres de archivo."""
    return datetime.now().strftime("%Y%m%d_%H%M%S")
