"""
SmartBasket — Clipper
Recorta clips individuales de candidatos usando FFmpeg.
Maneja pre-roll/post-roll, keyframes y re-encode cuando es necesario.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from loguru import logger
from tqdm import tqdm

from basketball_highlights.schemas import CandidateSegment


def cut_clip(
    video_path: str | Path,
    start_time: float,
    end_time: float,
    output_path: str | Path,
    reencode: bool = False,
    video_codec: str = "libx264",
    preset: str = "veryfast",
    crf: int = 20,
) -> str:
    """
    Recorta un clip del video usando FFmpeg.
    
    Args:
        video_path: Video fuente.
        start_time: Segundo de inicio del clip.
        end_time: Segundo de fin del clip.
        output_path: Ruta del clip de salida.
        reencode: Si True usa re-encode (más lento, keyframes correctos).
        video_codec: Codec para re-encode.
        preset: Preset de compresión para re-encode.
        crf: CRF (calidad) para re-encode.
    
    Returns:
        Ruta del clip generado.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    duration = end_time - start_time
    if duration <= 0:
        raise ValueError(f"Duración inválida: {duration}s ({start_time} → {end_time})")

    if reencode:
        cmd = [
            "ffmpeg", "-y", "-loglevel", "error",
            "-ss", str(start_time),
            "-i", str(video_path),
            "-t", str(duration),
            "-c:v", video_codec,
            "-preset", preset,
            "-crf", str(crf),
            "-c:a", "aac",
            "-movflags", "+faststart",
            str(output_path),
        ]
    else:
        # Modo stream copy: rápido pero puede tener problemas con keyframes
        cmd = [
            "ffmpeg", "-y", "-loglevel", "error",
            "-ss", str(start_time),
            "-to", str(end_time),
            "-i", str(video_path),
            "-c", "copy",
            str(output_path),
        ]

    try:
        subprocess.run(cmd, check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        if not reencode:
            # Reintentar con re-encode si stream copy falló
            logger.warning(f"Stream copy falló, reintentando con re-encode: {output_path.name}")
            return cut_clip(video_path, start_time, end_time, output_path, reencode=True,
                            video_codec=video_codec, preset=preset, crf=crf)
        raise RuntimeError(f"FFmpeg falló para {output_path.name}: {e.stderr.decode()}") from e

    return str(output_path)


def cut_candidate_clips(
    candidates: list[CandidateSegment],
    output_dir: str | Path,
    use_stream_copy: bool = True,
    video_codec: str = "libx264",
    preset: str = "veryfast",
    crf: int = 20,
) -> list[CandidateSegment]:
    """
    Recorta clips para todos los candidatos.
    
    Actualiza candidate.clip_path con la ruta del clip generado.
    
    Returns:
        Lista de candidatos con clip_path actualizado.
    """
    output_dir = Path(output_dir)
    logger.info(f"Recortando {len(candidates)} clips en {output_dir}...")

    updated = []
    for candidate in tqdm(candidates, desc="Cortando clips", unit="clip"):
        clip_name = f"{candidate.id}.mp4"
        clip_path = output_dir / clip_name

        try:
            cut_clip(
                video_path=candidate.video_path,
                start_time=candidate.start_time,
                end_time=candidate.end_time,
                output_path=clip_path,
                reencode=not use_stream_copy,
                video_codec=video_codec,
                preset=preset,
                crf=crf,
            )
            candidate.clip_path = str(clip_path)
            updated.append(candidate)
        except Exception as e:
            logger.error(f"Error cortando {candidate.id}: {e}")

    logger.info(f"  → {len(updated)} clips exportados")
    return updated
