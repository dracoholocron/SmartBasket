"""
SmartBasket — Scorer
Asigna score ponderado a cada candidato y genera razones interpretables.
Los pesos se cargan desde scoring.yaml — sin modificar código.
"""
from __future__ import annotations

from loguru import logger
from basketball_highlights.schemas import CandidateSegment


def score_candidate(candidate: CandidateSegment, weights: dict, penalties: dict) -> CandidateSegment:
    """
    Calcula el score de un candidato aplicando pesos y penalizaciones.
    
    Args:
        candidate: El segmento candidato.
        weights: Diccionario de pesos por señal (de scoring.yaml).
        penalties: Diccionario de penalizaciones.
    
    Returns:
        El candidato con score actualizado.
    """
    score = 0.0
    signals = candidate.signals

    # ─── Pesos positivos ─────────────────────────────────────────────────────
    if signals.get("ball_near_hoop", 0):
        score += weights.get("ball_near_hoop", 3.0)

    if signals.get("upward_ball_motion", 0):
        score += weights.get("upward_ball_motion", 2.5)

    if signals.get("players_near_paint", 0):
        # Bonus proporcional a número de jugadores (hasta 3)
        n = min(signals["players_near_paint"], 3)
        score += weights.get("players_near_paint", 2.0) * (n / 2.0)

    if signals.get("motion_spike", 0):
        score += weights.get("motion_spike", 2.0) * min(signals["motion_spike"], 1.0)

    if signals.get("audio_peak", 0):
        score += weights.get("audio_peak", 1.5)

    if signals.get("camera_zoom_or_scene_change", 0):
        score += weights.get("camera_zoom_or_scene_change", 1.0)

    if signals.get("possible_score", 0):
        score += weights.get("possible_score", 3.0)

    if signals.get("celebration_like_motion", 0):
        score += weights.get("celebration_like_motion", 1.5)

    if signals.get("ball_acceleration", 0):
        score += weights.get("ball_acceleration", 1.5)

    # "possible_score" heuristic: balón cerca del aro + movimiento ascendente
    if signals.get("ball_near_hoop") and signals.get("upward_ball_motion"):
        score += weights.get("possible_score", 3.0)
        if "possible shot attempt" not in candidate.reasons:
            candidate.reasons.append("possible shot attempt")

    # ─── Penalizaciones ──────────────────────────────────────────────────────
    ball_detected = any("basketball" in r or "ball near" in r for r in candidate.reasons)
    if not ball_detected and not signals.get("ball_near_hoop"):
        score += penalties.get("no_ball_detected", -1.5)

    player_detected = signals.get("players_near_paint", 0) > 0
    if not player_detected:
        score += penalties.get("no_players_detected", -2.0)

    if not signals.get("motion_spike") and not signals.get("audio_peak"):
        score += penalties.get("static_scene", -1.0)

    if candidate.duration < 4.0:
        score += penalties.get("very_short_clip", -0.5)

    candidate.score = round(max(0.0, score), 2)
    return candidate


def rank_candidates(
    candidates: list[CandidateSegment],
    weights: dict,
    penalties: dict,
    min_score: float = 5.5,
) -> list[CandidateSegment]:
    """
    Aplica scoring a todos los candidatos, filtra por score mínimo y los ordena.
    
    Args:
        candidates: Lista de candidatos.
        weights: Pesos de scoring.
        penalties: Penalizaciones de scoring.
        min_score: Score mínimo para incluir en el resultado.
    
    Returns:
        Lista filtrada y ordenada por score descendente.
    """
    logger.info(f"Calculando scores para {len(candidates)} candidatos...")
    
    scored = [score_candidate(c, weights, penalties) for c in candidates]
    scored.sort(key=lambda c: c.score, reverse=True)

    filtered = [c for c in scored if c.score >= min_score]
    
    logger.info(
        f"  → {len(filtered)} candidatos con score ≥ {min_score} "
        f"(de {len(scored)} total)"
    )
    if filtered:
        logger.info(f"  → Score máximo: {filtered[0].score:.2f} | "
                    f"Score mínimo: {filtered[-1].score:.2f} | "
                    f"Score promedio: {sum(c.score for c in filtered) / len(filtered):.2f}")

    return filtered
