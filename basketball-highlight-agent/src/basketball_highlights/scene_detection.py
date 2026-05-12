"""
SmartBasket — Scene Detection
Detecta cortes de cámara y cambios de escena usando PySceneDetect.
"""
from __future__ import annotations

from pathlib import Path

from loguru import logger

from basketball_highlights.schemas import SceneChange


def detect_scenes(
    video_path: str | Path,
    threshold: float = 27.0,
) -> list[SceneChange]:
    """
    Detecta cambios de escena en el video usando PySceneDetect.
    
    Args:
        video_path: Ruta al video.
        threshold: Sensibilidad del detector (menor = más sensible).
    
    Returns:
        Lista de SceneChange con start_time, end_time y número de escena.
    """
    try:
        from scenedetect import open_video, SceneManager
        from scenedetect.detectors import ContentDetector
    except ImportError:
        logger.warning("PySceneDetect no disponible, saltando scene detection")
        return []

    video_path = Path(video_path)
    logger.info(f"Detectando escenas en: {video_path.name}")

    video = open_video(str(video_path))
    scene_manager = SceneManager()
    scene_manager.add_detector(ContentDetector(threshold=threshold))
    scene_manager.detect_scenes(video, show_progress=False)

    raw_scenes = scene_manager.get_scene_list()
    scenes = []

    for i, (start, end) in enumerate(raw_scenes):
        scenes.append(SceneChange(
            start_time=round(start.get_seconds(), 3),
            end_time=round(end.get_seconds(), 3),
            scene_number=i + 1,
        ))

    logger.info(f"  → {len(scenes)} escenas detectadas")
    return scenes
