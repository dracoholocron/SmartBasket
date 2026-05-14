"""
Smoke test end-to-end de S0.3 + S0.4-A.

Reproduce el flujo completo del bridge del pipeline:
    tenant (reuse) -> 2 teams -> season -> game -> pipeline_run -> PATCH

Validaciones clave:
* El bug original (tz-aware datetime + status='succeeded') ya no rompe.
* tenant_id NO se acepta en payloads: se inyecta server-side desde
  el header X-Tenant-ID (S0.4-A) o se hereda del Game.
* Los enums (PipelineStatus, EventType) validan en el borde.
* S0.4-A: requests sin X-Tenant-ID -> 422; acceso cross-tenant -> 404.

Uso (desde C:\\code\\SmartBasket):
    python sports-data-api/scripts/smoke_s03.py

Requiere sólo stdlib (urllib + json). Sin httpx/requests.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from typing import Any
from uuid import uuid4

BASE = "http://localhost:8000"
SMOKE_TENANT = "00000000-0000-0000-0000-000000000001"


def _request(
    method: str,
    path: str,
    body: dict | list | None = None,
    tenant_id: str | None = SMOKE_TENANT,
) -> tuple[int, Any]:
    """Hace una request. Manda X-Tenant-ID salvo que ``tenant_id=None``."""
    url = f"{BASE}{path}"
    data = json.dumps(body).encode() if body is not None else None
    headers: dict[str, str] = {}
    if data:
        headers["Content-Type"] = "application/json"
    if tenant_id is not None:
        headers["X-Tenant-ID"] = tenant_id
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers=headers,
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            code = resp.status
            payload = resp.read().decode()
    except urllib.error.HTTPError as exc:
        code = exc.code
        payload = exc.read().decode()
    parsed: Any
    try:
        parsed = json.loads(payload) if payload else None
    except json.JSONDecodeError:
        parsed = payload
    return code, parsed


def _ok(code: int, expected: int, label: str, body: Any) -> None:
    if code != expected:
        print(f"  [FAIL] {label}: expected {expected}, got {code}")
        print(f"         body: {body}")
        sys.exit(1)
    print(f"  [OK]   {label} ({code})")


def main() -> None:
    print(">> Smoke test S0.3")

    # ── Tenant ────────────────────────────────────────────────────────
    print("\n[1] Tenant smoke (reuse existing)")
    code, body = _request("GET", f"/v1/tenants/{SMOKE_TENANT}")
    _ok(code, 200, "GET smoke tenant", body)

    # ── Teams ─────────────────────────────────────────────────────────
    print("\n[2] Teams (tenant_id inyectado desde X-Tenant-ID)")
    home_payload = {"name": f"Home-{uuid4().hex[:6]}"}
    code, home = _request("POST", "/v1/teams", home_payload)
    _ok(code, 201, "POST home team", home)
    away_payload = {"name": f"Away-{uuid4().hex[:6]}"}
    code, away = _request("POST", "/v1/teams", away_payload)
    _ok(code, 201, "POST away team", away)

    # ── Season ────────────────────────────────────────────────────────
    print("\n[3] Season")
    season_payload = {
        "name": f"Smoke {uuid4().hex[:6]}",
        "start_date": "2026-01-01",
        "end_date": "2026-12-31",
    }
    code, season = _request("POST", "/v1/seasons", season_payload)
    _ok(code, 201, "POST season", season)

    # ── Game ──────────────────────────────────────────────────────────
    print("\n[4] Game")
    game_payload = {
        "season_id": season["id"],
        "home_team_id": home["id"],
        "away_team_id": away["id"],
        "played_at": "2026-05-11T15:10:08Z",
        "video_uri": "/app/videos/20260511_151008.mp4",
        "video_duration_seconds": 702.85,
    }
    code, game = _request("POST", "/v1/games", game_payload)
    _ok(code, 201, "POST game", game)
    assert game["pipeline_status"] == "pending", game

    # ── PipelineRun ───────────────────────────────────────────────────
    print("\n[5] PipelineRun create (tenant_id NOT in payload — heredado)")
    run_payload = {
        "game_id": game["id"],
        "pipeline_version": "smoke-0.1",
        "config_snapshot": {"threshold": 3.0},
        "status": "running",
    }
    code, run = _request("POST", "/v1/pipeline-runs", run_payload)
    _ok(code, 201, "POST pipeline_run", run)
    assert run["tenant_id"] == SMOKE_TENANT, (
        f"tenant_id should be inherited from Game, got {run['tenant_id']!r}"
    )
    print(f"         tenant_id inherited correctly: {run['tenant_id']}")

    # ── PATCH PipelineRun (replica el bug original) ───────────────────
    print("\n[6] PipelineRun PATCH (tz-aware finished_at + status='succeeded')")
    finished_at_utc = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    patch_payload = {
        "status": "succeeded",
        "finished_at": finished_at_utc,
        "metrics": {
            "num_candidates": 8,
            "num_clips_exported": 3,
            "average_score": 3.59,
        },
    }
    code, run_final = _request("PATCH", f"/v1/pipeline-runs/{run['id']}", patch_payload)
    _ok(code, 200, "PATCH pipeline_run -> succeeded", run_final)
    assert run_final["status"] == "succeeded", run_final
    assert run_final["finished_at"] is not None, run_final
    print(f"         status: {run_final['status']}")
    print(f"         finished_at: {run_final['finished_at']}")

    # ── Negative: enum inválido en status ─────────────────────────────
    print("\n[7] Negative: status='nonsense' (Pydantic enum guard)")
    code, body = _request(
        "PATCH",
        f"/v1/pipeline-runs/{run['id']}",
        {"status": "nonsense"},
    )
    _ok(code, 422, "PATCH with invalid status rejected", body)

    # ── Negative: home_team_id == away_team_id ────────────────────────
    print("\n[8] Negative: same team home/away")
    bad_game = {**game_payload, "away_team_id": home["id"]}
    code, body = _request("POST", "/v1/games", bad_game)
    _ok(code, 422, "POST game same team rejected", body)

    # ── Bulk Event ────────────────────────────────────────────────────
    print("\n[9] Event bulk (tenant heredado del game)")
    events_payload = [
        {
            "game_id": game["id"],
            "pipeline_run_id": run["id"],
            "start_time_seconds": 10.0,
            "end_time_seconds": 14.0,
            "event_type": "made_shot",
            "raw_score": 4.2,
            "reasons": ["audio peak", "ball near rim"],
        }
        for _ in range(3)
    ]
    code, body = _request("POST", "/v1/events/bulk", events_payload)
    _ok(code, 201, "POST events bulk x3", body)
    assert body["count"] == 3

    # ── Negative: event_type inválido ─────────────────────────────────
    print("\n[10] Negative: event_type='aardvark'")
    bad_events = [{**events_payload[0], "event_type": "aardvark"}]
    code, body = _request("POST", "/v1/events/bulk", bad_events)
    _ok(code, 422, "POST event invalid event_type rejected", body)

    # ── S0.4-A Negative: request sin X-Tenant-ID ──────────────────────
    print("\n[11] S0.4-A: GET /v1/games sin X-Tenant-ID -> 422")
    code, body = _request("GET", "/v1/games", tenant_id=None)
    _ok(code, 422, "missing X-Tenant-ID header rejected", body)

    # ── S0.4-A Negative: acceso cross-tenant ──────────────────────────
    print("\n[12] S0.4-A: GET game con otro tenant -> 404 (sin leak)")
    other_tenant = str(uuid4())
    code, body = _request("GET", f"/v1/games/{game['id']}", tenant_id=other_tenant)
    _ok(code, 404, "cross-tenant game access returns 404", body)

    print("\n>> ALL CHECKS PASSED")


if __name__ == "__main__":
    main()
