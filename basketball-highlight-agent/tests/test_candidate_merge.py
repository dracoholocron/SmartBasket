"""
Tests para fusión y generación de candidatos.
"""
import pytest
from basketball_highlights.schemas import CandidateSegment
from basketball_highlights.candidate_generator import merge_overlapping_candidates


def make_candidate(cid: str, start: float, end: float, score: float = 5.0) -> CandidateSegment:
    return CandidateSegment(
        id=cid,
        video_path="/app/videos/test.mp4",
        start_time=start,
        end_time=end,
        score=score,
        reasons=["test"],
        signals={},
    )


class TestMergeOverlappingCandidates:
    def test_no_overlap(self):
        """Candidatos sin solapamiento no deben fusionarse."""
        c1 = make_candidate("c1", 0.0, 10.0)
        c2 = make_candidate("c2", 20.0, 30.0)
        result = merge_overlapping_candidates([c1, c2], gap_seconds=0.0)
        assert len(result) == 2

    def test_overlap(self):
        """Candidatos solapados deben fusionarse."""
        c1 = make_candidate("c1", 0.0, 15.0)
        c2 = make_candidate("c2", 10.0, 25.0)
        result = merge_overlapping_candidates([c1, c2], gap_seconds=0.0)
        assert len(result) == 1
        assert result[0].start_time == 0.0
        assert result[0].end_time == 25.0

    def test_gap_merge(self):
        """Candidatos dentro del gap deben fusionarse."""
        c1 = make_candidate("c1", 0.0, 10.0)
        c2 = make_candidate("c2", 12.0, 20.0)  # gap de 2s
        result = merge_overlapping_candidates([c1, c2], gap_seconds=4.0)
        assert len(result) == 1

    def test_gap_no_merge(self):
        """Candidatos fuera del gap no deben fusionarse."""
        c1 = make_candidate("c1", 0.0, 10.0)
        c2 = make_candidate("c2", 20.0, 30.0)  # gap de 10s
        result = merge_overlapping_candidates([c1, c2], gap_seconds=4.0)
        assert len(result) == 2

    def test_score_max_preserved(self):
        """Al fusionar, se preserva el score máximo."""
        c1 = make_candidate("c1", 0.0, 15.0, score=6.0)
        c2 = make_candidate("c2", 10.0, 25.0, score=9.0)
        result = merge_overlapping_candidates([c1, c2], gap_seconds=0.0)
        assert result[0].score == 9.0

    def test_reasons_merged(self):
        """Las razones se fusionan sin duplicados."""
        c1 = make_candidate("c1", 0.0, 15.0)
        c1.reasons = ["audio peak", "ball near hoop"]
        c2 = make_candidate("c2", 10.0, 25.0)
        c2.reasons = ["audio peak", "high motion"]
        result = merge_overlapping_candidates([c1, c2], gap_seconds=0.0)
        assert "audio peak" in result[0].reasons
        assert result[0].reasons.count("audio peak") == 1

    def test_empty_list(self):
        """Lista vacía no debe fallar."""
        result = merge_overlapping_candidates([])
        assert result == []

    def test_single_candidate(self):
        """Un solo candidato no debe modificarse."""
        c = make_candidate("c1", 5.0, 20.0)
        result = merge_overlapping_candidates([c])
        assert len(result) == 1
        assert result[0].start_time == 5.0
