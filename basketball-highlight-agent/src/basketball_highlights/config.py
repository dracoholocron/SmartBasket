"""
SmartBasket — Config loader
Carga los archivos YAML de configuración y los expone como objetos tipados.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from loguru import logger


def _load_yaml(path: str | Path) -> dict[str, Any]:
    """Carga un archivo YAML y retorna el diccionario."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Config no encontrada: {p}")
    with open(p, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _deep_merge(base: dict, override: dict) -> dict:
    """Combina dos dicts de forma recursiva. override tiene precedencia."""
    result = base.copy()
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


class AppConfig:
    """
    Configuración central del sistema.
    Combina default.yaml + scoring.yaml + models.yaml
    """

    def __init__(self, config_dir: str | Path = "/app/configs"):
        self._dir = Path(config_dir)
        self._default = _load_yaml(self._dir / "default.yaml")
        self._scoring = _load_yaml(self._dir / "scoring.yaml")
        self._models = _load_yaml(self._dir / "models.yaml")
        logger.info(f"Config cargada desde: {self._dir}")

    # ─── Secciones principales ─────────────────────────────────────────────

    @property
    def video(self) -> dict:
        return self._default.get("video", {})

    @property
    def models(self) -> dict:
        return self._default.get("models", {})

    @property
    def thresholds(self) -> dict:
        return self._default.get("thresholds", {})

    @property
    def output(self) -> dict:
        return self._default.get("output", {})

    @property
    def ffmpeg(self) -> dict:
        return self._default.get("ffmpeg", {})

    @property
    def weights(self) -> dict:
        return self._scoring.get("weights", {})

    @property
    def penalties(self) -> dict:
        return self._scoring.get("penalties", {})

    @property
    def yolo(self) -> dict:
        return self._models.get("yolo", {})

    @property
    def vlm(self) -> dict:
        return self._models.get("vlm", {})

    @property
    def court(self) -> dict:
        return self._models.get("court", {})

    # ─── Helpers ──────────────────────────────────────────────────────────

    def get(self, *keys: str, default: Any = None) -> Any:
        """Obtiene un valor de config por cadena de keys."""
        obj: Any = self._default
        for k in keys:
            if isinstance(obj, dict):
                obj = obj.get(k)
            else:
                return default
        return obj if obj is not None else default

    def resolve_model_path(self, path_key: str) -> Path:
        """Resuelve la ruta de un modelo relativo al directorio de trabajo."""
        raw = self.models.get(path_key, "")
        p = Path(raw)
        if not p.is_absolute():
            p = Path("/app") / p
        return p

    def get_yolo_model_path(self) -> Path:
        """Retorna la ruta del modelo YOLO a usar (custom o fallback)."""
        custom = self.resolve_model_path("yolo_model_path")
        fallback = self.resolve_model_path("fallback_yolo_model")
        if custom.exists():
            logger.info(f"Usando modelo YOLO custom: {custom}")
            return custom
        logger.warning(f"Modelo custom no encontrado, usando fallback: {fallback}")
        return fallback

    def use_vlm(self) -> bool:
        """Retorna si el VLM está habilitado."""
        env_val = os.environ.get("VLM_ENABLED", "").lower()
        if env_val in ("false", "0", "no"):
            return False
        return self.models.get("use_vlm", True)


# Instancia global (lazy singleton por config_dir)
_config_cache: dict[str, AppConfig] = {}


def get_config(config_dir: str | Path = "/app/configs") -> AppConfig:
    """Retorna la instancia de config (cached)."""
    key = str(config_dir)
    if key not in _config_cache:
        _config_cache[key] = AppConfig(config_dir)
    return _config_cache[key]
