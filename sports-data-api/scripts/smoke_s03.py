"""
Smoke test end-to-end de S0.3 + S0.4-A + S0.4-D.

Reproduce el flujo completo del bridge del pipeline:
    tenant (reuse) -> 2 teams -> season -> game -> pipeline_run -> PATCH

Validaciones clave:
* El bug original (tz-aware datetime + status='succeeded') ya no rompe.
* tenant_id NO se acepta en payloads: se inyecta server-side desde
  el header X-Tenant-ID (S0.4-A) o se hereda del Game.
* Los enums (PipelineStatus, EventType) validan en el borde.
* S0.4-A: acceso cross-tenant -> 404.
* S0.4-D: sin credenciales -> 401; mint de API key con root token;
  auth por Bearer; key revocado -> 401.

Nota: corre con ALLOW_HEADER_TENANT_AUTH=true (default de dev) — por eso
el header X-Tenant-ID sigue alcanzando para autenticar la mayoría de los
checks. En prod el único mecanismo válido sería el Bearer token.

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
# Debe coincidir con API_ROOT_ADMIN_TOKEN del .env de dev.
ROOT_TOKEN = "change-me-in-dev"


def _request(
    method: str,
    path: str,
    body: dict | list | None = None,
    tenant_id: str | None = SMOKE_TENANT,
    extra_headers: dict[str, str] | None = None,
) -> tuple[int, Any]:
    """
    Hace una request. Manda X-Tenant-ID salvo que ``tenant_id=None``.
    ``extra_headers`` permite mandar Authorization/X-Root-Admin-Token, etc.
    """
    url = f"{BASE}{path}"
    data = json.dumps(body).encode() if body is not None else None
    headers: dict[str, str] = {}
    if data:
        headers["Content-Type"] = "application/json"
    if tenant_id is not None:
        headers["X-Tenant-ID"] = tenant_id
    if extra_headers:
        headers.update(extra_headers)
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

    # ── S0.4-D Negative: request sin credenciales ─────────────────────
    print("\n[11] S0.4-D: GET /v1/games sin credenciales -> 401")
    code, body = _request("GET", "/v1/games", tenant_id=None)
    _ok(code, 401, "missing credentials rejected", body)

    # ── S0.4-A Negative: acceso cross-tenant ──────────────────────────
    print("\n[12] S0.4-A: GET game con otro tenant -> 404 (sin leak)")
    other_tenant = str(uuid4())
    code, body = _request("GET", f"/v1/games/{game['id']}", tenant_id=other_tenant)
    _ok(code, 404, "cross-tenant game access returns 404", body)

    # ── S0.4-D: mint de API key con root token ────────────────────────
    print("\n[13] S0.4-D: POST /v1/admin/api-keys con root token")
    code, minted = _request(
        "POST",
        "/v1/admin/api-keys",
        {"name": f"smoke-{uuid4().hex[:6]}", "role": "pipeline", "tenant_id": SMOKE_TENANT},
        tenant_id=None,
        extra_headers={"X-Root-Admin-Token": ROOT_TOKEN},
    )
    _ok(code, 201, "mint API key via root token", minted)
    api_key = minted["api_key"]
    key_id = minted["id"]
    assert api_key.startswith("sdk_"), minted
    print(f"         minted key prefix: {minted['key_prefix']}")

    # ── S0.4-D: auth por Bearer con el key recién minteado ────────────
    print("\n[14] S0.4-D: GET /v1/teams con Authorization: Bearer")
    code, body = _request(
        "GET",
        "/v1/teams",
        tenant_id=None,
        extra_headers={"Authorization": f"Bearer {api_key}"},
    )
    _ok(code, 200, "Bearer auth accepted", body)

    # ── S0.4-D Negative: Bearer inválido ──────────────────────────────
    print("\n[15] S0.4-D: Bearer token inválido -> 401")
    code, body = _request(
        "GET",
        "/v1/teams",
        tenant_id=None,
        extra_headers={"Authorization": "Bearer sdk_not_a_real_key"},
    )
    _ok(code, 401, "invalid Bearer token rejected", body)

    # ── S0.4-D: revocar el key, después usarlo -> 401 ─────────────────
    print("\n[16] S0.4-D: revoke key, luego usarlo -> 401")
    code, body = _request(
        "DELETE",
        f"/v1/admin/api-keys/{key_id}",
        tenant_id=None,
        extra_headers={"X-Root-Admin-Token": ROOT_TOKEN},
    )
    _ok(code, 200, "revoke API key", body)
    assert body["revoked_at"] is not None, body
    code, body = _request(
        "GET",
        "/v1/teams",
        tenant_id=None,
        extra_headers={"Authorization": f"Bearer {api_key}"},
    )
    _ok(code, 401, "revoked key rejected", body)

    # ── S1-A: revisión humana de un evento ────────────────────────────
    print("\n[17] S1-A: GET eventos del game para tomar uno")
    code, evs = _request("GET", f"/v1/events?game_id={game['id']}")
    _ok(code, 200, "GET events by game_id", evs)
    assert len(evs) >= 1, evs
    event_id = evs[0]["id"]

    print("\n[18] S1-A: PATCH /v1/events/{id} (review humano)")
    code, reviewed = _request(
        "PATCH",
        f"/v1/events/{event_id}",
        {
            "reviewed_by": "smoke-tester",
            "review_status": "confirmed",
            "review_notes": "looks good",
        },
    )
    _ok(code, 200, "PATCH event review", reviewed)
    assert reviewed["review_status"] == "confirmed", reviewed

    print("\n[19] S1-A: GET /v1/events/{id}/tags (auditoría)")
    code, tags = _request("GET", f"/v1/events/{event_id}/tags")
    _ok(code, 200, "GET event tags", tags)
    assert len(tags) == 1, tags
    assert tags[0]["tagger"] == "smoke-tester", tags
    assert tags[0]["after_json"]["review_status"] == "confirmed", tags

    print("\n[20] S1-A: POST /v1/events/bulk-review")
    code, body = _request(
        "POST",
        "/v1/events/bulk-review",
        {
            "reviewed_by": "smoke-tester",
            "items": [
                {"event_id": ev["id"], "review_status": "rejected"}
                for ev in evs[1:3]
            ],
        },
    )
    _ok(code, 200, "POST events bulk-review", body)
    assert body["count"] == len(evs[1:3]), body

    # ── S1-A: registro de clips ───────────────────────────────────────
    print("\n[21] S1-A: POST /v1/clips (con event_id)")
    clip_payload = {
        "game_id": game["id"],
        "event_id": event_id,
        "storage_uri": f"/app/videos/clips/{uuid4().hex}.mp4",
        "duration_seconds": 4.2,
        "width": 1920,
        "height": 1080,
        "fps": 30.0,
        "format": "mp4",
    }
    code, clip = _request("POST", "/v1/clips", clip_payload)
    _ok(code, 201, "POST clip", clip)
    clip_id = clip["id"]

    print("\n[22] S1-A: GET /v1/clips/{id}")
    code, body = _request("GET", f"/v1/clips/{clip_id}")
    _ok(code, 200, "GET clip", body)
    assert body["event_id"] == event_id, body

    print("\n[23] S1-A: el evento quedó vinculado al clip (clip_id sincronizado)")
    code, body = _request("GET", f"/v1/events/{event_id}")
    _ok(code, 200, "GET event after clip link", body)
    assert body["clip_id"] == clip_id, body

    print("\n>> ALL CHECKS PASSED")


if __name__ == "__main__":
    main()
