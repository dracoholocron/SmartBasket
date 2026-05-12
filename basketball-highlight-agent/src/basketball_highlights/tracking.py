"""
SmartBasket — Ball Tracking
Asocia detecciones del balón entre frames consecutivos (nearest-neighbor).
Calcula trayectoria, velocidad y dirección del balón.
"""
from __future__ import annotations

import math
from loguru import logger
from basketball_highlights.schemas import Detection


def track_ball(detections: list[Detection], max_distance_px: float = 200.0) -> list[dict]:
    """
    Asocia detecciones de balón entre frames consecutivos usando nearest-neighbor.
    
    Args:
        detections: Lista de todas las detecciones del pipeline.
        max_distance_px: Distancia máxima en píxeles para asociar detecciones.
    
    Returns:
        Lista de dicts con: frame_index, timestamp, cx, cy, width, height.
        Solo incluye frames donde se detectó el balón.
    """
    ball_dets = [d for d in detections if d.label == "basketball"]
    if not ball_dets:
        logger.warning("No se detectaron balones en ningún frame")
        return []

    # Agrupar por frame (tomar la detección con más confianza por frame)
    by_frame: dict[int, Detection] = {}
    for d in ball_dets:
        if d.frame_index not in by_frame or d.confidence > by_frame[d.frame_index].confidence:
            by_frame[d.frame_index] = d

    track = []
    frame_indices = sorted(by_frame.keys())
    prev_cx, prev_cy = None, None

    for fi in frame_indices:
        d = by_frame[fi]
        cx = d.center_x
        cy = d.center_y

        # Verificar que no salte demasiado (posible falso positivo)
        if prev_cx is not None:
            dist = math.sqrt((cx - prev_cx) ** 2 + (cy - prev_cy) ** 2)
            if dist > max_distance_px:
                # Salto grande: posible falso positivo, continuar pero marcar
                track.append({
                    "frame_index": fi,
                    "timestamp": d.timestamp,
                    "cx": cx, "cy": cy,
                    "width": d.width, "height": d.height,
                    "confidence": d.confidence,
                    "jump": True,
                })
                prev_cx, prev_cy = cx, cy
                continue

        track.append({
            "frame_index": fi,
            "timestamp": d.timestamp,
            "cx": cx, "cy": cy,
            "width": d.width, "height": d.height,
            "confidence": d.confidence,
            "jump": False,
        })
        prev_cx, prev_cy = cx, cy

    logger.info(f"  → Trayectoria del balón: {len(track)} posiciones rastreadas")
    return track


def compute_ball_motion(ball_track: list[dict]) -> list[dict]:
    """
    Calcula velocidad y dirección del balón entre posiciones consecutivas.
    
    Agrega a cada punto:
        - vx, vy: velocidad en píxeles por frame
        - speed: magnitud de la velocidad
        - moving_up: True si el balón se mueve hacia arriba (vy < 0)
        - moving_fast: True si la velocidad es alta (posible fast break)
    
    Returns:
        Lista de dicts con motion info por frame.
    """
    if not ball_track:
        return []

    motion = []
    for i, point in enumerate(ball_track):
        if i == 0:
            motion.append({**point, "vx": 0.0, "vy": 0.0, "speed": 0.0,
                           "moving_up": False, "moving_fast": False})
            continue

        prev = ball_track[i - 1]
        dt = point["timestamp"] - prev["timestamp"]
        if dt <= 0:
            dt = 1.0

        vx = (point["cx"] - prev["cx"]) / dt
        vy = (point["cy"] - prev["cy"]) / dt
        speed = math.sqrt(vx ** 2 + vy ** 2)

        motion.append({
            **point,
            "vx": round(vx, 2),
            "vy": round(vy, 2),
            "speed": round(speed, 2),
            "moving_up": vy < -20,          # negativo = hacia arriba en coordenadas imagen
            "moving_fast": speed > 300,     # px/s, ajustable
        })

    return motion


def get_ball_timestamps_near_hoop(
    ball_track: list[dict],
    hoop_boxes: list[dict],
    threshold_px: float = 150.0,
) -> list[float]:
    """
    Retorna los timestamps donde el balón está cerca de algún aro.
    
    Args:
        ball_track: Track del balón con posiciones.
        hoop_boxes: Lista de dicts con x1, y1, x2, y2 del aro.
        threshold_px: Distancia máxima en píxeles al centro del aro.
    
    Returns:
        Lista de timestamps donde el balón está cerca del aro.
    """
    near_timestamps = []
    for point in ball_track:
        for hoop in hoop_boxes:
            hoop_cx = (hoop["x1"] + hoop["x2"]) / 2
            hoop_cy = (hoop["y1"] + hoop["y2"]) / 2
            dist = math.sqrt((point["cx"] - hoop_cx) ** 2 + (point["cy"] - hoop_cy) ** 2)
            if dist <= threshold_px:
                near_timestamps.append(point["timestamp"])
                break
    return near_timestamps
