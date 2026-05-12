"""
SmartBasket — VLM Labeler
Clasifica clips candidatos usando Qwen2.5-VL-3B-Instruct local.
Solo procesa los top N candidatos para no saturar VRAM.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

from loguru import logger
from tqdm import tqdm

from basketball_highlights.schemas import CandidateSegment, VLMLabel

VLM_PROMPT = """You are analyzing a youth basketball video clip.
Analyze the visual content carefully.

Return ONLY valid JSON with exactly this schema (no markdown, no explanation):
{
  "is_highlight": true,
  "play_type": "score | three_pointer | block | steal | assist | rebound | fast_break | foul | unknown",
  "confidence": 0.0,
  "description": "short description of what happens",
  "best_start_offset": 0.0,
  "best_end_offset": 0.0,
  "reason": "why this is or is not a highlight"
}

Prioritize clear basketball highlights: made baskets, three-pointers, blocks, steals, fast breaks, assists, and important rebounds.
Reject clips where nothing important happens.
confidence must be between 0.0 and 1.0.
"""


def _extract_frames_from_clip(
    clip_path: str,
    num_frames: int = 12,
    max_width: int = 640,
) -> list:
    """
    Extrae N frames representativos de un clip usando FFmpeg y los carga como PIL Images.
    """
    import subprocess
    import tempfile
    from PIL import Image as PILImage

    clip_path = Path(clip_path)
    frames = []

    with tempfile.TemporaryDirectory() as tmpdir:
        cmd = [
            "ffmpeg", "-y", "-loglevel", "error",
            "-i", str(clip_path),
            "-vf", f"select='not(mod(n,{max(1, int(30/num_frames))}))',scale={max_width}:-2",
            "-vsync", "vfr",
            "-frames:v", str(num_frames),
            "-q:v", "3",
            f"{tmpdir}/frame_%03d.jpg",
        ]
        try:
            subprocess.run(cmd, check=True, capture_output=True)
        except subprocess.CalledProcessError:
            logger.warning(f"No se pudieron extraer frames de: {clip_path.name}")
            return []

        frame_files = sorted(Path(tmpdir).glob("frame_*.jpg"))
        for ff in frame_files[:num_frames]:
            try:
                img = PILImage.open(str(ff)).convert("RGB")
                frames.append(img)
            except Exception:
                pass

    return frames


def _parse_vlm_response(response_text: str) -> dict:
    """Extrae JSON de la respuesta del VLM."""
    # Intentar extraer JSON desde el texto (el modelo puede agregar texto extra)
    json_match = re.search(r"\{.*\}", response_text, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group())
        except json.JSONDecodeError:
            pass
    raise ValueError(f"No se pudo parsear JSON del VLM: {response_text[:200]}")


class VLMLabeler:
    """
    Clasifica clips candidatos usando Qwen2.5-VL local.
    Se carga lazy (primera vez que se usa).
    """

    def __init__(
        self,
        model_id: str = "Qwen/Qwen2.5-VL-3B-Instruct",
        model_cache_dir: str = "/app/models/vlm",
        device: str = "cuda",
        quantization: Optional[int] = None,
        max_frames: int = 12,
        max_width: int = 640,
        max_new_tokens: int = 512,
        temperature: float = 0.1,
    ):
        self.model_id = model_id
        self.model_cache_dir = model_cache_dir
        self.device = device
        self.quantization = quantization
        self.max_frames = max_frames
        self.max_width = max_width
        self.max_new_tokens = max_new_tokens
        self.temperature = temperature
        self._model = None
        self._processor = None

    def _load(self):
        """Carga el modelo y processor (lazy)."""
        if self._model is not None:
            return

        import torch
        from transformers import AutoProcessor, Qwen2VLForConditionalGeneration, BitsAndBytesConfig

        logger.info(f"Cargando VLM: {self.model_id}...")

        # Configuración de cuantización
        quant_config = None
        if self.quantization == 4:
            quant_config = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_compute_dtype=torch.float16,
            )
            logger.info("  Usando cuantización 4-bit")
        elif self.quantization == 8:
            quant_config = BitsAndBytesConfig(load_in_8bit=True)
            logger.info("  Usando cuantización 8-bit")

        self._processor = AutoProcessor.from_pretrained(
            self.model_id,
            cache_dir=self.model_cache_dir,
        )
        self._model = Qwen2VLForConditionalGeneration.from_pretrained(
            self.model_id,
            cache_dir=self.model_cache_dir,
            torch_dtype=torch.float16 if self.device == "cuda" else torch.float32,
            device_map=self.device,
            quantization_config=quant_config,
        )
        logger.info(f"  VLM listo en {self.device}")

    def label_clip(self, clip_path: str) -> Optional[VLMLabel]:
        """
        Clasifica un clip usando el VLM.
        
        Args:
            clip_path: Ruta al clip de video.
        
        Returns:
            VLMLabel o None si falla.
        """
        self._load()

        frames = _extract_frames_from_clip(clip_path, self.max_frames, self.max_width)
        if not frames:
            logger.warning(f"No se pudieron extraer frames: {clip_path}")
            return None

        import torch

        # Construir mensaje con imágenes
        content = [{"type": "text", "text": VLM_PROMPT}]
        for frame in frames:
            content.append({"type": "image", "image": frame})

        messages = [{"role": "user", "content": content}]

        try:
            text = self._processor.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True
            )
            from qwen_vl_utils import process_vision_info
            image_inputs, video_inputs = process_vision_info(messages)

            inputs = self._processor(
                text=[text],
                images=image_inputs,
                videos=video_inputs,
                padding=True,
                return_tensors="pt",
            ).to(self.device)

            with torch.no_grad():
                outputs = self._model.generate(
                    **inputs,
                    max_new_tokens=self.max_new_tokens,
                    temperature=self.temperature,
                    do_sample=self.temperature > 0,
                )

            # Decodificar solo los tokens nuevos
            input_len = inputs["input_ids"].shape[1]
            output_ids = outputs[0][input_len:]
            response = self._processor.decode(output_ids, skip_special_tokens=True)

            data = _parse_vlm_response(response)
            return VLMLabel(**data)

        except Exception as e:
            logger.error(f"Error en VLM para {Path(clip_path).name}: {e}")
            return None

    def label_candidates(
        self,
        candidates: list[CandidateSegment],
        max_clips: int = 40,
    ) -> list[CandidateSegment]:
        """
        Clasifica los top N candidatos con el VLM.
        Actualiza play_type, confidence y vlm_reviewed.
        
        Returns:
            Lista de candidatos actualizada.
        """
        # Solo procesar los top N por score
        to_label = sorted(candidates, key=lambda c: c.score, reverse=True)[:max_clips]
        logger.info(f"Clasificando {len(to_label)} clips con VLM...")

        for candidate in tqdm(to_label, desc="VLM", unit="clip"):
            if not candidate.clip_path or not Path(candidate.clip_path).exists():
                logger.warning(f"Clip no encontrado: {candidate.id}")
                continue

            label = self.label_clip(candidate.clip_path)
            if label:
                candidate.play_type = label.play_type
                candidate.confidence = label.confidence
                candidate.vlm_reviewed = True
                # Ajustar score: si el VLM dice que NO es highlight, penalizar
                if not label.is_highlight:
                    candidate.score = max(0.0, candidate.score - 3.0)
                elif label.confidence > 0.7:
                    # VLM con alta confianza: bonus
                    candidate.score = round(candidate.score + 1.5, 2)
                if label.play_type not in ("unknown", None):
                    if f"vlm: {label.play_type}" not in candidate.reasons:
                        candidate.reasons.append(f"vlm: {label.play_type}")

        # Re-ordenar por score final
        candidates.sort(key=lambda c: c.score, reverse=True)
        logger.info("  VLM labeling completado")
        return candidates
