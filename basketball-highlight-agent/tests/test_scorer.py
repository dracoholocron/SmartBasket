"""
Tests para el módulo de scoring.
"""
import pytest
from basketball_highlights.schemas import CandidateSegment
from basketball_highlights.scorer import score_candidate, rank_candidates

WEIGHTS = {
    "ball_near_hoop": 3.0,
    "upward_ball_motion": 2.5,
    "players_near_paint": 2.0,
    "motion_spike": 2.0,
    "audio_peak": 1.5,
    "camera_zoom_or_scene_change": 1.0,
    "possible_score": 3.0,
    "celebration_like_motion": 1.5,
    "ball_acceleration": 1.5,
}

PENALTIES = {
    "no_ball_detected": -1.5,
    "no_players_detected": -2.0,
    "static_scene": -1.0,
    "very_short_clip": -0.5,
}


def make_candidate(cid: str, signals: dict, reasons: list[str], start: float = 100.0, end: float = 120.0) -> CandidateSegment:
    return CandidateSegment(
        id=cid,
        video_path="/app/videos/input/test.mp4",
        start_time=start,
        end_time=end,
        score=0.0,
        reasons=reasons,
        signals=signals,
    )


class TestScoreCandidate:
    def test_canasta_clara(self):
        """Canasta con balón cerca del aro + movimiento ascendente + audio."""
        c = make_candidate("test_001", {
            "ball_near_hoop": 1.0,
            "upward_ball_motion": 1.0,
            "players_near_paint": 3.0,
            "audio_peak": 1.0,
        }, ["ball near hoop", "upward ball motion", "audio peak"])
        scored = score_candidate(c, WEIGHTS, PENALTIES)
        # ball(3) + upward(2.5) + players(2*1.5=3) + audio(1.5) + possible_score(3) = 13
        assert scored.score >= 10.0

    def test_sin_senales(self):
        """Candidato sin señales relevantes debe tener score bajo."""
        c = make_candidate("test_002", {}, [])
        scored = score_candidate(c, WEIGHTS, PENALTIES)
        assert scored.score < 2.0

    def test_solo_audio_peak(self):
        """Solo pico de audio sin detección visual."""
        c = make_candidate("test_003", {"audio_peak": 1.0}, ["audio peak"])
        scored = score_candidate(c, WEIGHTS, PENALTIES)
        # audio(1.5) - no_ball(-1.5) - no_players(-2.0) = -2.0 → clamped a 0
        assert scored.score >= 0.0

    def test_score_no_negativo(self):
        """El score nunca debe ser negativo."""
        c = make_candidate("test_004", {}, [])
        scored = score_candidate(c, WEIGHTS, PENALTIES)
        assert scored.score >= 0.0


class TestRankCandidates:
    def test_ordenados_por_score(self):
        """Los candidatos deben estar ordenados de mayor a menor score."""
        candidates = [
            make_candidate("c1", {"audio_peak": 1.0}, ["audio peak"]),
            make_candidate("c2", {"ball_near_hoop": 1.0, "audio_peak": 1.0}, ["ball near hoop", "audio peak"]),
            make_candidate("c3", {}, []),
        ]
        ranked = rank_candidates(candidates, WEIGHTS, PENALTIES, min_score=0.0)
        scores = [c.score for c in ranked]
        assert scores == sorted(scores, reverse=True)

    def test_filtro_por_score_minimo(self):
        """Candidatos por debajo del score mínimo deben ser excluidos."""
        candidates = [
            make_candidate("c1", {"ball_near_hoop": 1.0, "upward_ball_motion": 1.0, "audio_peak": 1.0},
                           ["ball near hoop", "audio peak"]),
            make_candidate("c2", {}, []),
        ]
        ranked = rank_candidates(candidates, WEIGHTS, PENALTIES, min_score=5.5)
        assert all(c.score >= 5.5 for c in ranked)

    def test_lista_vacia(self):
        """Lista vacía no debe fallar."""
        result = rank_candidates([], WEIGHTS, PENALTIES)
        assert result == []
