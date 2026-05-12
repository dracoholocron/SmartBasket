"""
SmartBasket — Pydantic schemas
Modelos de datos para todo el pipeline de highlights.
"""
from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, Field


# ─────────────────────────────────────────────────────────────────────────────
# Detección YOLO individual en un frame
# ─────────────────────────────────────────────────────────────────────────────
class Detection(BaseModel):
    """Una detección YOLO en un frame específico."""
    frame_index: int
    timestamp: float
    label: str                    # "basketball", "hoop", "player", etc.
    confidence: float
    x1: float
    y1: float
    x2: float
    y2: float

    @property
    def center_x(self) -> float:
        return (self.x1 + self.x2) / 2

    @property
    def center_y(self) -> float:
        return (self.y1 + self.y2) / 2

    @property
    def width(self) -> float:
        return self.x2 - self.x1

    @property
    def height(self) -> float:
        return self.y2 - self.y1

    @property
    def area(self) -> float:
        return self.width * self.height


# ─────────────────────────────────────────────────────────────────────────────
# Segmento candidato a highlight
# ─────────────────────────────────────────────────────────────────────────────
class CandidateSegment(BaseModel):
    """Un segmento de tiempo candidato a highlight."""
    id: str
    video_path: str
    start_time: float
    end_time: float
    score: float = 0.0
    reasons: list[str] = Field(default_factory=list)
    signals: dict[str, float] = Field(default_factory=dict)
    play_type: Optional[str] = None
    confidence: Optional[float] = None
    clip_path: Optional[str] = None
    vlm_reviewed: bool = False

    @property
    def duration(self) -> float:
        return self.end_time - self.start_time

    def overlaps(self, other: "CandidateSegment", gap_seconds: float = 0.0) -> bool:
        """Verifica si este segmento se solapa o está muy cerca del otro."""
        return self.start_time <= other.end_time + gap_seconds and \
               self.end_time + gap_seconds >= other.start_time

    def merge_with(self, other: "CandidateSegment") -> "CandidateSegment":
        """Fusiona dos segmentos solapados en uno más grande."""
        return CandidateSegment(
            id=self.id,
            video_path=self.video_path,
            start_time=min(self.start_time, other.start_time),
            end_time=max(self.end_time, other.end_time),
            score=max(self.score, other.score),
            reasons=list(set(self.reasons + other.reasons)),
            signals={**other.signals, **self.signals},
            play_type=self.play_type or other.play_type,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Resultado del VLM
# ─────────────────────────────────────────────────────────────────────────────
class VLMLabel(BaseModel):
    """Clasificación de un clip por el modelo VLM."""
    is_highlight: bool
    play_type: str   # score|three_pointer|block|steal|assist|rebound|fast_break|foul|unknown
    confidence: float
    description: str
    best_start_offset: Optional[float] = None
    best_end_offset: Optional[float] = None
    reason: str


# ─────────────────────────────────────────────────────────────────────────────
# Información de un frame muestreado
# ─────────────────────────────────────────────────────────────────────────────
class FrameInfo(BaseModel):
    """Información de un frame extraído del video."""
    frame_path: str
    timestamp: float
    frame_index: int


# ─────────────────────────────────────────────────────────────────────────────
# Pico de audio
# ─────────────────────────────────────────────────────────────────────────────
class AudioPeak(BaseModel):
    """Un pico de energía de audio detectado."""
    timestamp: float
    energy: float
    is_peak: bool


# ─────────────────────────────────────────────────────────────────────────────
# Escena detectada
# ─────────────────────────────────────────────────────────────────────────────
class SceneChange(BaseModel):
    """Cambio de escena o corte de cámara detectado."""
    start_time: float
    end_time: float
    scene_number: int


# ─────────────────────────────────────────────────────────────────────────────
# Anotación humana
# ─────────────────────────────────────────────────────────────────────────────
class HumanAnnotation(BaseModel):
    """Anotación humana sobre un candidato."""
    candidate_id: str
    approved: bool
    corrected_play_type: Optional[str] = None
    corrected_start_time: Optional[float] = None
    corrected_end_time: Optional[float] = None
    notes: str = ""


# ─────────────────────────────────────────────────────────────────────────────
# Reporte de procesamiento de un video
# ─────────────────────────────────────────────────────────────────────────────
class VideoReport(BaseModel):
    """Reporte final del procesamiento de un partido."""
    video: str
    duration_seconds: float
    num_candidates: int
    num_clips_exported: int
    num_vlm_highlights: int = 0
    average_score: float
    reel_path: Optional[str] = None
    processing_time_seconds: Optional[float] = None
