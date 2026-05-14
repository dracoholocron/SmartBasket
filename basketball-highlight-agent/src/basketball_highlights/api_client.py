from __future__ import annotations

import time
from typing import Any, Dict, List, Optional
from uuid import UUID

import httpx
from loguru import logger


class ApiClient:
    def __init__(self, base_url: str, api_key: str | None = None, tenant_id: str | None = None):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.tenant_id = tenant_id
        self.headers = {
            "Content-Type": "application/json",
            "User-Agent": "SmartBasket-Pipeline/0.1.0",
        }
        if api_key:
            self.headers["X-API-Key"] = api_key

    def _request(self, method: str, path: str, **kwargs) -> Dict[str, Any]:
        url = f"{self.base_url}/{path.lstrip('/')}"
        try:
            with httpx.Client(headers=self.headers, timeout=30.0) as client:
                response = client.request(method, url, **kwargs)
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error {e.response.status_code} on {method} {url}: {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"Error on {method} {url}: {str(e)}")
            raise

    def get_health(self) -> bool:
        try:
            self._request("GET", "/health")
            return True
        except:
            return False

    def create_pipeline_run(self, game_id: str, pipeline_version: str, config: Dict[str, Any]) -> str:
        """Registra el inicio de una ejecución del pipeline."""
        payload = {
            "game_id": game_id,
            "tenant_id": self.tenant_id,
            "pipeline_version": pipeline_version,
            "config_snapshot": config,
            "status": "running",
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        # Nota: Por ahora usamos game_id como un string externo o UUID si ya existe
        # Asumimos que la API tiene un endpoint para esto.
        # Basado en nuestra arquitectura: POST /v1/pipeline-runs (a implementar si no existe)
        # Por ahora lo mandamos a un endpoint genérico o simulamos.
        try:
            res = self._request("POST", "/v1/pipeline-runs", json=payload)
            return res["id"]
        except:
            logger.warning("No se pudo registrar pipeline_run en la API. Continuando localmente.")
            return ""

    def update_pipeline_run(self, run_id: str, status: str, metrics: Dict[str, Any], error: str | None = None):
        """Actualiza el estado final de la ejecución."""
        if not run_id: return
        payload = {
            "status": status,
            "metrics": metrics,
            "error": error,
            "finished_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        try:
            self._request("PATCH", f"/v1/pipeline-runs/{run_id}", json=payload)
        except:
            logger.warning(f"No se pudo actualizar pipeline_run {run_id}")

    def post_events(self, game_id: str, run_id: str, events: List[Dict[str, Any]]):
        """Sube los eventos detectados a la API."""
        if not events: return
        payload = []
        for ev in events:
            # Mapeo de campos del pipeline local al esquema de la API
            api_ev = {
                "tenant_id": self.tenant_id,
                "game_id": game_id,
                "pipeline_run_id": run_id,
                "start_time_seconds": ev.get("start_time"),
                "end_time_seconds": ev.get("end_time"),
                "event_type": ev.get("label", "unknown"),
                "raw_score": ev.get("score", 0.0),
                "confidence": ev.get("confidence") if ev.get("confidence") is not None else 1.0,
                "signals": ev.get("signals", {}),
                "reasons": ev.get("reasons", []),
                "metadata": ev.get("vlm_analysis", {})
            }
            payload.append(api_ev)
        
        try:
            self._request("POST", "/v1/events/bulk", json=payload)
            logger.info(f"✅ {len(events)} eventos subidos a la API")
        except:
            logger.error("Error al subir eventos a la API")
