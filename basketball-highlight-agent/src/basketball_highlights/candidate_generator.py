"""
SmartBasket — Candidate Generator
Convierte señales del pipeline en segmentos candidatos a highlight.
Combina detecciones YOLO, audio peaks, motion scores y scene changes.
"""
from __future__ import annotations

import uuid
from loguru import logger

from basketball_highlights.schemas import (
    Detection, AudioPeak, SceneChange, CandidateSegment
)
from basketball_highlights.court_geometry import ball_near_hoop, players_near_hoop
from basketball_highlights.tracking import track_ball, compute_ball_motion


def _generate_id(game_id: str, index: int) -> str:
    return f"{game_id}_{index:04d}"


def _create_window(
    timestamp: float,
    pre_roll: float,
    post_roll: float,
    video_duration: float,
    min_clip: float,
    max_clip: float,
) -> tuple[float, float]:
    """Crea una ventana de tiempo [start, end] alrededor de un evento."""
    start = max(0.0, timestamp - pre_roll)
    end = min(video_duration, timestamp + post_roll)
    # Asegurar duración mínima y máxima
    duration = end - start
    if duration < min_clip:
        end = min(video_duration, start + min_clip)
    if duration > max_clip:
        end = start + max_clip
    return start, end


def merge_overlapping_candidates(
    candidates: list[CandidateSegment],
    gap_seconds: float = 4.0,
) -> list[CandidateSegment]:
    """
    Fusiona candidatos solapados o muy cercanos entre sí.
    
    Args:
        candidates: Lista de candidatos ordenados por start_time.
        gap_seconds: Separación máxima para considerar fusión.
    
    Returns:
        Lista de candidatos fusionados.
    """
    if not candidates:
        return []

    sorted_cands = sorted(candidates, key=lambda c: c.start_time)
    merged = [sorted_cands[0]]

    for current in sorted_cands[1:]:
        prev = merged[-1]
        if current.start_time <= prev.end_time + gap_seconds:
            merged[-1] = prev.merge_with(current)
        else:
            merged.append(current)

    logger.info(f"  Fusión: {len(candidates)} → {len(merged)} candidatos")
    return merged


def generate_candidates(
    game_id: str,
    video_path: str,
    video_duration: float,
    detections: list[Detection],
    audio_peaks: list[AudioPeak],
    scenes: list[SceneChange],
    motion_scores: list[dict],
    hoop_boxes: list[dict],
    config: dict,
) -> list[CandidateSegment]:
    """
    Genera segmentos candidatos combinando todas las señales del pipeline.
    
    Señales analizadas:
        - Balón cerca del aro (YOLO)
        - Balón con trayectoria ascendente (tracking)
        - Jugadores cerca del aro (YOLO)
        - Picos de audio
        - Picos de movimiento
        - Cambios de escena
    
    Returns:
        Lista de CandidateSegment fusionados y ordenados por timestamp.
    """
    pre_roll = config.get("pre_roll_seconds", 3.0)
    post_roll = config.get("post_roll_seconds", 5.0)
    min_clip = config.get("min_clip_seconds", 6.0)
    max_clip = config.get("max_clip_seconds", 24.0)
    ball_threshold = config.get("ball_hoop_threshold_px", 150.0)

    # ─── Calcular tracking del balón ─────────────────────────────────────────
    ball_track = track_ball(detections)
    ball_motion = compute_ball_motion(ball_track)
    ball_motion_by_ts = {round(b["timestamp"], 1): b for b in ball_motion}

    # ─── Índices de señales para búsqueda rápida ─────────────────────────────
    audio_peak_times = {round(p.timestamp, 1) for p in audio_peaks if p.is_peak}
    motion_by_ts = {round(m["timestamp"], 1): m["motion_score"] for m in motion_scores}

    # Calcular percentil 88 de motion scores
    motion_values = list(motion_by_ts.values())
    motion_threshold = 0.0
    if motion_values:
        import numpy as np
        motion_threshold = float(np.percentile(motion_values, config.get("motion_peak_percentile", 88)))

    # Agrupar detecciones por timestamp (con redondeo a 0.1s)
    dets_by_ts: dict[float, list[Detection]] = {}
    for d in detections:
        key = round(d.timestamp, 1)
        dets_by_ts.setdefault(key, []).append(d)

    # ─── Generar eventos candidatos ───────────────────────────────────────────
    raw_events: list[tuple[float, list[str], dict[str, float]]] = []

    # 1. Eventos de YOLO: balón cerca del aro, jugadores cerca del aro
    for ts_key, ts_dets in dets_by_ts.items():
        signals: dict[str, float] = {}
        reasons: list[str] = []

        ball_dets = [d for d in ts_dets if d.label == "basketball"]
        player_dets = [d for d in ts_dets if d.label == "player"]

        if ball_dets and hoop_boxes:
            ball = ball_dets[0]
            if ball_near_hoop(ball.center_x, ball.center_y, hoop_boxes, ball_threshold):
                signals["ball_near_hoop"] = 1.0
                reasons.append("ball near hoop")

                # ¿Balón moviéndose hacia arriba?
                bm = ball_motion_by_ts.get(ts_key)
                if bm and bm.get("moving_up"):
                    signals["upward_ball_motion"] = 1.0
                    reasons.append("upward ball motion")

        # Jugadores cerca del aro
        n_players_near = players_near_hoop(ts_dets, hoop_boxes)
        if n_players_near >= 2:
            signals["players_near_paint"] = float(n_players_near)
            reasons.append(f"{n_players_near} players near paint")

        # Pico de movimiento
        motion_score = motion_by_ts.get(ts_key, 0.0)
        if motion_score >= motion_threshold:
            signals["motion_spike"] = motion_score
            reasons.append("high motion")

        # Pico de audio cercano (+/-1.5s)
        for audio_ts in audio_peak_times:
            if abs(audio_ts - ts_key) <= 1.5:
                signals["audio_peak"] = 1.0
                reasons.append("audio peak")
                break

        if reasons:
            raw_events.append((ts_key, reasons, signals))

    # 2. Eventos de audio puros (sin detección YOLO correspondiente)
    for ts_key in audio_peak_times:
        if ts_key not in {round(e[0], 1) for e in raw_events}:
            raw_events.append((ts_key, ["audio peak"], {"audio_peak": 1.0}))

    # 3. Cambios de escena como señal adicional
    scene_times = {round(s.start_time, 1) for s in scenes}

    # ─── Convertir eventos a segmentos candidatos ─────────────────────────────
    candidates = []
    for i, (ts, reasons, signals) in enumerate(raw_events):
        # Agregar señal de scene change si hay uno cercano
        for st in scene_times:
            if abs(st - ts) <= 2.0:
                signals["camera_zoom_or_scene_change"] = 1.0
                if "scene change" not in reasons:
                    reasons.append("scene change nearby")
                break

        start, end = _create_window(ts, pre_roll, post_roll, video_duration, min_clip, max_clip)
        candidates.append(CandidateSegment(
            id=_generate_id(game_id, i),
            video_path=video_path,
            start_time=round(start, 3),
            end_time=round(end, 3),
            score=0.0,           # se calcula en scorer.py
            reasons=reasons,
            signals=signals,
        ))

    # ─── Fusionar candidatos solapados ────────────────────────────────────────
    gap = config.get("merge_gap_seconds", 4.0)
    candidates = merge_overlapping_candidates(candidates, gap)

    # Re-numerar IDs después de fusión
    for i, c in enumerate(candidates):
        c.id = _generate_id(game_id, i)

    logger.info(f"  → {len(candidates)} candidatos generados")
    return candidates
