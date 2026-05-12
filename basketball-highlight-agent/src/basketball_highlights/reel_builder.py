"""
SmartBasket — Reel Builder
Concatena los mejores clips en un reel usando FFmpeg concat.
Soporta orden por score o cronológico.
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from loguru import logger
from basketball_highlights.schemas import CandidateSegment


def build_reel(
    candidates: list[CandidateSegment],
    output_path: str | Path,
    top_k: int = 10,
    mode: str = "score",
    reencode: bool = False,
) -> str:
    """
    Concatena los mejores clips candidatos en un reel.
    
    Args:
        candidates: Lista de candidatos con clip_path.
        output_path: Ruta del reel de salida.
        top_k: Número de clips a incluir.
        mode: "score" (por relevancia) o "chronological" (orden del partido).
        reencode: Si True fuerza re-encode para uniformidad de stream.
    
    Returns:
        Ruta del reel generado.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Filtrar candidatos sin clip_path
    valid = [c for c in candidates if c.clip_path and Path(c.clip_path).exists()]
    if not valid:
        raise ValueError("No hay clips válidos para construir el reel")

    # Ordenar según el modo
    if mode == "score":
        ordered = sorted(valid, key=lambda c: c.score, reverse=True)[:top_k]
    elif mode == "chronological":
        ordered = sorted(
            sorted(valid, key=lambda c: c.score, reverse=True)[:top_k],
            key=lambda c: c.start_time,
        )
    else:
        raise ValueError(f"Modo desconocido: {mode}")

    logger.info(f"Construyendo reel '{mode}' con {len(ordered)} clips...")

    # Crear lista de concatenación para FFmpeg
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
        concat_file = f.name
        for c in ordered:
            clip_path = str(Path(c.clip_path).resolve()).replace("\\", "/")
            f.write(f"file '{clip_path}'\n")

    try:
        if reencode:
            cmd = [
                "ffmpeg", "-y", "-loglevel", "error",
                "-f", "concat", "-safe", "0",
                "-i", concat_file,
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                "-c:a", "aac",
                "-movflags", "+faststart",
                str(output_path),
            ]
        else:
            cmd = [
                "ffmpeg", "-y", "-loglevel", "error",
                "-f", "concat", "-safe", "0",
                "-i", concat_file,
                "-c", "copy",
                str(output_path),
            ]
        subprocess.run(cmd, check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        if not reencode:
            logger.warning("Stream copy falló en reel, reintentando con re-encode...")
            Path(concat_file).unlink(missing_ok=True)
            return build_reel(candidates, output_path, top_k, mode, reencode=True)
        raise RuntimeError(f"Error construyendo reel: {e.stderr.decode()}") from e
    finally:
        Path(concat_file).unlink(missing_ok=True)

    size_mb = output_path.stat().st_size / (1024 * 1024)
    logger.info(f"  → Reel generado: {output_path} ({size_mb:.1f} MB)")
    logger.info(f"  → Clips incluidos: {[c.id for c in ordered]}")
    return str(output_path)
