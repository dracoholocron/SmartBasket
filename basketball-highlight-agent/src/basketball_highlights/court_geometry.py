"""
SmartBasket — Court Geometry
Estima zonas del aro y pintura. Calcula distancias entre balón, aro y jugadores.
Soporta detección automática del aro y configuración manual de regiones.
"""
from __future__ import annotations

import math
from loguru import logger
from basketball_highlights.schemas import Detection


def get_hoop_boxes_from_detections(detections: list[Detection]) -> list[dict]:
    """
    Extrae las bounding boxes de los aros detectados por YOLO.
    Agrupa por posición y retorna centros únicos (izquierdo/derecho).
    
    Returns:
        Lista de dicts con x1, y1, x2, y2 para cada aro.
    """
    hoop_dets = [d for d in detections if d.label == "hoop"]
    if not hoop_dets:
        return []

    # Agrupar aros por posición horizontal (izquierdo vs derecho)
    # Tomar el aro con mayor confianza de cada lado
    frames_with_hoop: dict[int, Detection] = {}
    for d in hoop_dets:
        if d.frame_index not in frames_with_hoop or d.confidence > frames_with_hoop[d.frame_index].confidence:
            frames_with_hoop[d.frame_index] = d

    if not frames_with_hoop:
        return []

    # Calcular bounding box promedio de todos los aros detectados
    # Separar por posición horizontal (izquierda < 50% de imagen)
    left_hoops = []
    right_hoops = []

    # Necesitamos el ancho de imagen para separar; usar cx como proxy
    all_cx = [d.center_x for d in frames_with_hoop.values()]
    median_cx = sorted(all_cx)[len(all_cx) // 2] if all_cx else 0

    for d in frames_with_hoop.values():
        box = {"x1": d.x1, "y1": d.y1, "x2": d.x2, "y2": d.y2}
        if d.center_x < median_cx:
            left_hoops.append(box)
        else:
            right_hoops.append(box)

    result = []
    for group in [left_hoops, right_hoops]:
        if group:
            result.append({
                "x1": sum(b["x1"] for b in group) / len(group),
                "y1": sum(b["y1"] for b in group) / len(group),
                "x2": sum(b["x2"] for b in group) / len(group),
                "y2": sum(b["y2"] for b in group) / len(group),
            })

    logger.info(f"  Aros detectados: {len(result)}")
    return result


def get_manual_hoop_regions(config: dict) -> list[dict]:
    """
    Carga regiones de aro configuradas manualmente desde el YAML.
    
    Args:
        config: Sección 'court.manual_hoop_regions' del config.
    
    Returns:
        Lista de dicts con x1, y1, x2, y2.
    """
    if not config.get("enabled", False):
        return []
    regions = config.get("regions", [])
    logger.info(f"Usando {len(regions)} regiones manuales de aro")
    return [{"x1": r["x1"], "y1": r["y1"], "x2": r["x2"], "y2": r["y2"]} for r in regions]


def ball_near_hoop(
    ball_cx: float,
    ball_cy: float,
    hoop_boxes: list[dict],
    threshold_px: float = 150.0,
) -> bool:
    """
    Verifica si el balón está cerca de algún aro.
    
    Args:
        ball_cx, ball_cy: Centro del balón.
        hoop_boxes: Lista de bounding boxes de aros.
        threshold_px: Distancia máxima en píxeles.
    
    Returns:
        True si el balón está dentro del threshold de algún aro.
    """
    for hoop in hoop_boxes:
        hoop_cx = (hoop["x1"] + hoop["x2"]) / 2
        hoop_cy = (hoop["y1"] + hoop["y2"]) / 2
        dist = math.sqrt((ball_cx - hoop_cx) ** 2 + (ball_cy - hoop_cy) ** 2)
        if dist <= threshold_px:
            return True
    return False


def players_near_hoop(
    player_detections: list[Detection],
    hoop_boxes: list[dict],
    threshold_px: float = 300.0,
) -> int:
    """
    Cuenta cuántos jugadores están cerca del área del aro.
    
    Returns:
        Número de jugadores dentro del threshold de algún aro.
    """
    count = 0
    player_dets = [d for d in player_detections if d.label == "player"]
    for player in player_dets:
        for hoop in hoop_boxes:
            hoop_cx = (hoop["x1"] + hoop["x2"]) / 2
            hoop_cy = (hoop["y1"] + hoop["y2"]) / 2
            dist = math.sqrt((player.center_x - hoop_cx) ** 2 + (player.center_y - hoop_cy) ** 2)
            if dist <= threshold_px:
                count += 1
                break
    return count
