"""
Smoke test del health endpoint (sin DB).

Tests con DB real vienen en S0.4 usando testcontainers-postgres.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from sports_data_api.main import create_app


@pytest.fixture
def client() -> TestClient:
    app = create_app()
    return TestClient(app)


def test_health_liveness(client: TestClient) -> None:
    """`/health` no toca DB, debe responder siempre."""
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "version" in body
