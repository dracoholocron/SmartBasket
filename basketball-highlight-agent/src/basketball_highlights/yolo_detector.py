"""
SmartBasket — YOLO Detector
Detección de balón, aro y jugadores sobre frames muestreados.
Soporta modelo custom basketball.pt y fallback a yolov8s.pt genérico.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from loguru import logger
from tqdm import tqdm

from basketball_highlights.schemas import Detection, FrameInfo


# ─── Mapeo de clases del modelo basketball custom ────────────────────────────
BASKETBALL_CLASSES = {
    "basketball": ["basketball", "ball"],
    "hoop": ["hoop", "basket", "ring", "rim"],
    "player": ["player", "person"],
    "referee": ["referee", "ref"],
}

# Clases COCO para fallback con yolov8s/m
COCO_FALLBACK = {
    "person": "player",
    "sports ball": "basketball",
}


class YOLODetector:
    """
    Detector YOLO para elementos de basketball.
    Usa modelo custom si existe, con fallback a COCO genérico.
    """

    def __init__(
        self,
        model_path: str | Path,
        device: str = "cuda",
        conf: float = 0.25,
        imgsz: int = 640,
        fallback_path: Optional[str | Path] = None,
    ):
        from ultralytics import YOLO

        self.device = device
        self.conf = conf
        self.imgsz = imgsz
        self.is_custom = False

        model_path = Path(model_path)
        if model_path.exists():
            logger.info(f"Cargando modelo YOLO custom: {model_path}")
            self.model = YOLO(str(model_path))
            self.is_custom = True
        elif fallback_path and Path(fallback_path).exists():
            logger.warning(f"Modelo custom no encontrado, usando fallback: {fallback_path}")
            self.model = YOLO(str(fallback_path))
        else:
            logger.warning("Descargando yolov8s.pt (fallback)...")
            self.model = YOLO("yolov8s.pt")

        # Registrar clases disponibles
        self.class_names = self.model.names
        logger.info(f"  YOLO listo | Clases: {list(self.class_names.values())[:10]}")

    def _normalize_label(self, raw_label: str) -> str:
        """Normaliza la etiqueta YOLO a las clases del sistema."""
        raw = raw_label.lower()
        # Intentar mapear a clases de basketball
        for canonical, variants in BASKETBALL_CLASSES.items():
            if any(v in raw for v in variants):
                return canonical
        # Fallback COCO
        return COCO_FALLBACK.get(raw, raw)

    def detect_frame(self, frame_path: str, timestamp: float, frame_index: int) -> list[Detection]:
        """
        Corre YOLO sobre un frame y retorna las detecciones.
        
        Args:
            frame_path: Ruta al frame JPEG.
            timestamp: Timestamp del frame en segundos.
            frame_index: Índice del frame en el video.
        
        Returns:
            Lista de Detection para ese frame.
        """
        results = self.model.predict(
            source=frame_path,
            device=self.device,
            conf=self.conf,
            imgsz=self.imgsz,
            verbose=False,
        )
        detections = []
        for result in results:
            boxes = result.boxes
            if boxes is None:
                continue
            for box in boxes:
                cls_id = int(box.cls[0])
                raw_label = self.class_names.get(cls_id, str(cls_id))
                label = self._normalize_label(raw_label)
                conf = float(box.conf[0])
                x1, y1, x2, y2 = box.xyxy[0].tolist()
                detections.append(Detection(
                    frame_index=frame_index,
                    timestamp=timestamp,
                    label=label,
                    confidence=conf,
                    x1=x1, y1=y1, x2=x2, y2=y2,
                ))
        return detections

    def detect_frames(self, frames: list[FrameInfo]) -> list[Detection]:
        """
        Corre YOLO sobre una lista de frames.
        
        Returns:
            Lista plana de todas las Detection de todos los frames.
        """
        all_detections = []
        logger.info(f"Ejecutando YOLO sobre {len(frames)} frames...")

        for frame_info in tqdm(frames, desc="YOLO", unit="frame"):
            dets = self.detect_frame(
                frame_path=frame_info.frame_path,
                timestamp=frame_info.timestamp,
                frame_index=frame_info.frame_index,
            )
            all_detections.extend(dets)

        # Estadísticas
        by_label: dict[str, int] = {}
        for d in all_detections:
            by_label[d.label] = by_label.get(d.label, 0) + 1

        logger.info(f"  → {len(all_detections)} detecciones totales: {by_label}")
        return all_detections
