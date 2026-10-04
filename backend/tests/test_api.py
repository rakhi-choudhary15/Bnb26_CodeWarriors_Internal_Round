"""API tests: ownership, error envelope, idempotency, and the creation vertical slice.

These exercise the real app through HTTP, against a temporary SQLite database.
Nothing is mocked except the model provider, which is already deterministic in dev
mode (AGENTS.md §14: API tests for auth/ownership).
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _headers(owner: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer dev:{owner}"}


# ---------------------------------------------------------------------------
# Health & auth
# ---------------------------------------------------------------------------
def test_health_is_open_and_reports_real_capabilities(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] in {"ok", "degraded"}
    # No FFmpeg here, so media must not claim to be available.
    assert body["media"]["ok"] is False
    assert "ffprobe_not_installed" in body["media"]["missing"]
    assert body["database"]["ok"] is True
    assert body["skills"]["registered"] >= 10


def test_request_id_is_echoed_on_success_and_errors(client: TestClient) -> None:
    response = client.get("/api/health", headers={"x-request-id": "abc123"})
    assert response.headers["x-request-id"] == "abc123"
    missing = client.get("/api/projects/not-a-uuid")
    assert missing.status_code in (401, 422, 404)
    assert "x-request-id" in missing.headers


def test_unknown_route_uses_the_error_envelope(client: TestClient) -> None:
    response = client.get("/api/definitely-not-a-route")
    assert response.status_code == 404
    assert set(response.json()["error"]) >= {"code", "message", "request_id"}


# ---------------------------------------------------------------------------
# Creation vertical slice
# ---------------------------------------------------------------------------
def test_intent_creates_project_and_parses(client: TestClient) -> None:
    owner = uuid.uuid4()
    response = client.post(
        "/api/creation/intents",
        headers=_headers(owner),
        json={
            "primary_text": "A 30 second reel teaching founders how to price their first product",
            "details_text": "Confident, no jargon, ends with a question.",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert uuid.UUID(body["project_id"])
    intent = body["intent"]
    parsed = intent["parsed"]
    assert parsed["platform"] == "instagram_reels"
    assert 3 <= parsed["duration_s"] <= 90
    assert parsed["stages"], "the intent must propose stages"
    assert 0.0 <= intent["confidence"]["overall"] <= 1.0
    # Every proposed stage has to be a skill the registry can actually run.
    from app.modules.skills.registry import has_skill

    assert all(has_skill(stage) for stage in parsed["stages"])


def test_intent_rejects_too_short_text(client: TestClient) -> None:
    response = client.post(
        "/api/creation/intents",
        headers=_headers(uuid.uuid4()),
        json={"primary_text": "hi"},
    )
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert error["details"]["fields"]


def test_intent_rejects_unknown_fields(client: TestClient) -> None:
    response = client.post(
        "/api/creation/intents",
        headers=_headers(uuid.uuid4()),
        json={"primary_text": "a valid long enough description of a reel", "surprise": 1},
    )
    assert response.status_code == 422


def test_blueprint_and_workflow_flow(client: TestClient) -> None:
    owner = uuid.uuid4()
    intent_id = _create_intent(client, owner)

    created = client.post(
        "/api/creation/blueprints", headers=_headers(owner), json={"intent_id": intent_id}
    )
    assert created.status_code == 201, created.text
    blueprint = created.json()["blueprint"]
    assert blueprint["version"] == 1
    assert blueprint["stages"]
    stage_keys = [stage["key"] for stage in blueprint["stages"]]

    project_id = _project_id_for(client, owner, intent_id)
    workflows = client.post(
        f"/api/projects/{project_id}/workflows",
        headers=_headers(owner),
        json={"blueprint_id": blueprint["id"]},
    )
    assert workflows.status_code == 201, workflows.text
    workflow = workflows.json()["workflow"]
    steps = workflow["steps"]
    assert [s["position"] for s in steps] == list(range(len(steps)))
    # Exactly one step is unlocked, and it is the first.
    ready = [s for s in steps if s["status"] == "ready"]
    assert len(ready) == 1 and ready[0]["position"] == 0
    assert [s["status"] for s in steps[1:]] == ["locked"] * (len(steps) - 1)
    assert step_keys_match(steps, stage_keys)


def test_blueprint_patch_rejects_unknown_skill(client: TestClient) -> None:
    owner = uuid.uuid4()
    intent_id = _create_intent(client, owner)
    blueprint_id = client.post(
        "/api/creation/blueprints", headers=_headers(owner), json={"intent_id": intent_id}
    ).json()["blueprint"]["id"]

    response = client.patch(
        f"/api/creation/blueprints/{blueprint_id}",
        headers=_headers(owner),
        json={"stages": [{"key": "s1", "skill_ids": ["nope.not_a_skill"]}]},
    )
    assert response.status_code == 422
    assert response.json()["error"]["details"]["skill_id"] == "nope.not_a_skill"


def test_blueprint_patch_bumps_version(client: TestClient) -> None:
    owner = uuid.uuid4()
    intent_id = _create_intent(client, owner)
    blueprint = client.post(
        "/api/creation/blueprints", headers=_headers(owner), json={"intent_id": intent_id}
    ).json()["blueprint"]

    patched = client.patch(
        f"/api/creation/blueprints/{blueprint['id']}",
        headers=_headers(owner),
        json={"stages": [{"key": "only", "title": "One stage", "skill_ids": ["hook.generate"]}]},
    )
    assert patched.status_code == 200
    assert patched.json()["blueprint"]["version"] == 2
    assert patched.json()["blueprint"]["stages"][0]["skill_ids"] == ["hook.generate"]


# ---------------------------------------------------------------------------
# Ownership: the security-critical behaviour
# ---------------------------------------------------------------------------
def test_intent_is_not_visible_to_another_owner(client: TestClient) -> None:
    mine = uuid.uuid4()
    theirs = uuid.uuid4()
    intent_id = _create_intent(client, mine)

    assert client.get(f"/api/creation/intents/{intent_id}", headers=_headers(mine)).status_code == 200
    # 404, never 403: a stranger must not learn the id exists.
    assert client.get(f"/api/creation/intents/{intent_id}", headers=_headers(theirs)).status_code == 404
    assert (
        client.patch(
            f"/api/creation/intents/{intent_id}",
            headers=_headers(theirs),
            json={"parsed": {"tone": ["shouting"]}},
        ).status_code
        == 404
    )


def test_project_list_only_shows_your_own(client: TestClient) -> None:
    mine, theirs = uuid.uuid4(), uuid.uuid4()
    _create_intent(client, mine)
    _create_intent(client, theirs)

    items = client.get("/api/projects", headers=_headers(mine)).json()["items"]
    assert len(items) == 1


def test_creating_a_workflow_needs_the_project_to_be_yours(client: TestClient) -> None:
    victim, attacker = uuid.uuid4(), uuid.uuid4()
    intent_id = _create_intent(client, victim)
    project_id = _project_id_for(client, victim, intent_id)

    response = client.post(
        f"/api/projects/{project_id}/workflows",
        headers=_headers(attacker),
        json={"blueprint_id": str(uuid.uuid4())},
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Workflow state machine
# ---------------------------------------------------------------------------
def test_workflow_step_run_and_advance(client: TestClient) -> None:
    owner = uuid.uuid4()
    workflow, steps = _ready_workflow(client, owner)
    first = steps[0]

    run = client.post(
        f"/api/workflows/{workflow['id']}/steps/{first['id']}/run", headers=_headers(owner)
    )
    assert run.status_code == 200, run.text
    assert run.json()["result"], "an inline step must return its validated output"

    accept = client.patch(
        f"/api/workflows/{workflow['id']}/steps/{first['id']}",
        headers=_headers(owner),
        json={"status": "done"},
    )
    assert accept.status_code == 200
    assert accept.json()["status"] == "done"

    after = client.get(f"/api/workflows/{workflow['id']}", headers=_headers(owner)).json()
    statuses = [s["status"] for s in after["workflow"]["steps"]]
    assert statuses[0] == "done"
    assert statuses[1] == "ready", "accepting a step unlocks exactly the next one"


def test_a_step_receives_the_validated_output_of_the_step_before_it(
    client: TestClient,
) -> None:
    """The demo path: `hook.generate` declares `input_schema=ConceptOutput`.

    It needs the `concepts` that `concept.generate` produced, so a workflow only
    works if a finished step persists its output where the next one reads it.
    Without that, step two fails validation the moment a creator runs it.
    """
    owner = uuid.uuid4()
    workflow, steps = _ready_workflow(client, owner)

    first_run = client.post(
        f"/api/workflows/{workflow['id']}/steps/{steps[0]['id']}/run", headers=_headers(owner)
    )
    assert first_run.status_code == 200, first_run.text
    produced = first_run.json()["result"]
    assert produced, "the first step must return output for the next one to consume"

    client.patch(
        f"/api/workflows/{workflow['id']}/steps/{steps[0]['id']}",
        headers=_headers(owner),
        json={"status": "done"},
    )

    second_run = client.post(
        f"/api/workflows/{workflow['id']}/steps/{steps[1]['id']}/run", headers=_headers(owner)
    )
    assert second_run.status_code == 200, second_run.text
    chained = second_run.json()["result"]
    assert chained, "the dependent step must run, not fail on a missing input"
    # Whatever step two produced, it must not be a validation error.
    assert "error" not in chained, chained


def test_copy_stages_receive_the_creators_own_words(client: TestClient) -> None:
    owner = uuid.uuid4()
    workflow, steps = _ready_workflow(client, owner, subject="energetic dancing video")
    client.post(
        f"/api/workflows/{workflow['id']}/steps/{steps[0]['id']}/run", headers=_headers(owner)
    )
    step = client.get(f"/api/workflows/{workflow['id']}", headers=_headers(owner)).json()[
        "workflow"
    ]["steps"][0]
    concepts = step["output_ref"]["concepts"]
    assert concepts, "the concept stage must produce options"
    # Generic filler about "your idea" is the failure mode this guards against:
    # without the brief reaching the skills, copy cannot mention the subject.
    assert "your idea" not in json.dumps(concepts).lower()
    assert any("danc" in json.dumps(c).lower() for c in concepts)


def test_hooks_survive_the_spoken_budget_whole(client: TestClient) -> None:
    owner = uuid.uuid4()
    workflow, steps = _ready_workflow(
        client, owner, subject="a 30-second energetic dancing video for Instagram"
    )
    client.post(
        f"/api/workflows/{workflow['id']}/steps/{steps[0]['id']}/run", headers=_headers(owner)
    )
    client.patch(
        f"/api/workflows/{workflow['id']}/steps/{steps[0]['id']}",
        headers=_headers(owner),
        json={"status": "done"},
    )
    client.post(
        f"/api/workflows/{workflow['id']}/steps/{steps[1]['id']}/run", headers=_headers(owner)
    )
    hooks = client.get(f"/api/workflows/{workflow['id']}", headers=_headers(owner)).json()[
        "workflow"
    ]["steps"][1]["output_ref"]["hooks"]
    assert hooks, "the hook stage must produce options"
    assert not any(h["text"].endswith("…") for h in hooks), (
        "a hook cut mid-phrase by the spoken budget is unusable copy"
    )
    assert "hook_truncated_to_spoken_budget" not in json.dumps(hooks)


def test_a_step_keeps_its_provenance_next_to_its_output(client: TestClient) -> None:
    owner = uuid.uuid4()
    workflow, steps = _ready_workflow(client, owner)
    client.post(
        f"/api/workflows/{workflow['id']}/steps/{steps[0]['id']}/run", headers=_headers(owner)
    )
    step = client.get(f"/api/workflows/{workflow['id']}", headers=_headers(owner)).json()[
        "workflow"
    ]["steps"][0]
    assert step["output_ref"]["skill_id"], "the step records which skill produced the output"


def test_locked_step_cannot_run(client: TestClient) -> None:
    owner = uuid.uuid4()
    workflow, steps = _ready_workflow(client, owner)
    locked = next(s for s in steps if s["status"] == "locked")

    response = client.post(
        f"/api/workflows/{workflow['id']}/steps/{locked['id']}/run", headers=_headers(owner)
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CONFLICT"


def test_step_status_rejects_a_bogus_value(client: TestClient) -> None:
    owner = uuid.uuid4()
    workflow, steps = _ready_workflow(client, owner)
    response = client.patch(
        f"/api/workflows/{workflow['id']}/steps/{steps[0]['id']}",
        headers=_headers(owner),
        json={"status": "teleported"},
    )
    assert response.status_code == 422


def test_two_active_workflows_conflict(client: TestClient) -> None:
    owner = uuid.uuid4()
    workflow, _ = _ready_workflow(client, owner)
    response = client.post(
        f"/api/projects/{workflow['project_id']}/workflows",
        headers=_headers(owner),
        json={"blueprint_id": workflow["blueprint_id"]},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CONFLICT"


# ---------------------------------------------------------------------------
# Assets
# ---------------------------------------------------------------------------
def test_upload_ticket_and_magic_byte_verification(client: TestClient, tmp_path: Path) -> None:
    owner = uuid.uuid4()
    ticket = client.post(
        "/api/assets/upload-url",
        headers=_headers(owner),
        json={
            "filename": "clip.mp4",
            "mime": "video/mp4",
            "size_bytes": 1024,
            "kind": "video",
        },
    )
    assert ticket.status_code == 201, ticket.text
    body = ticket.json()
    assert body["method"] == "PUT"
    assert body["upload_url"]
    assert body["key"].startswith(f"{owner}/"), "storage keys must be owner-scoped"

    # A .txt renamed to .mp4 must be rejected on content, not on name.
    lying = client.put(
        f"/api/assets/{body['asset_id']}/content",
        headers={**_headers(owner), "content-type": "video/mp4"},
        content=b"this is plain text pretending to be an mp4" * 10,
    )
    assert lying.status_code == 422

    real = _tiny_mp4_bytes()
    ok = client.put(
        f"/api/assets/{body['asset_id']}/content",
        headers={**_headers(owner), "content-type": "video/mp4"},
        content=real,
    )
    assert ok.status_code == 204
    assert ok.headers["x-verified-mime"] == "video/mp4"


def test_upload_declaring_an_unsupported_type_is_refused(client: TestClient) -> None:
    response = client.post(
        "/api/assets/upload-url",
        headers=_headers(uuid.uuid4()),
        json={
            "filename": "payload.exe",
            "mime": "application/x-msdownload",
            "size_bytes": 10,
            "kind": "video",
        },
    )
    assert response.status_code == 422


def test_asset_is_not_visible_to_another_owner(client: TestClient) -> None:
    mine, theirs = uuid.uuid4(), uuid.uuid4()
    asset_id = client.post(
        "/api/assets/upload-url",
        headers=_headers(mine),
        json={"filename": "a.mp4", "mime": "video/mp4", "size_bytes": 10, "kind": "video"},
    ).json()["asset_id"]

    assert client.get(f"/api/assets/{asset_id}", headers=_headers(mine)).status_code == 200
    assert client.get(f"/api/assets/{asset_id}", headers=_headers(theirs)).status_code == 404
    assert client.delete(f"/api/assets/{asset_id}", headers=_headers(theirs)).status_code == 404


def test_upload_ticket_with_project_id_succeeds(client: TestClient) -> None:
    owner = uuid.uuid4()
    res = client.post(
        "/api/creation/intents",
        headers=_headers(owner),
        json={"primary_text": "Dance reel for project upload test"},
    )
    assert res.status_code == 201
    project_id = res.json()["project_id"]

    ticket = client.post(
        "/api/assets/upload-url",
        headers=_headers(owner),
        json={
            "filename": "clip_with_project.mp4",
            "mime": "video/mp4",
            "size_bytes": 2048,
            "kind": "video",
            "project_id": project_id,
        },
    )
    assert ticket.status_code == 201, ticket.text
    body = ticket.json()
    assert body["method"] == "PUT"
    assert project_id in body["key"]


def test_upload_ticket_for_unowned_project_rejected(client: TestClient) -> None:
    owner_a = uuid.uuid4()
    owner_b = uuid.uuid4()
    res = client.post(
        "/api/creation/intents",
        headers=_headers(owner_b),
        json={"primary_text": "Owner B project"},
    )
    assert res.status_code == 201
    project_b_id = res.json()["project_id"]

    ticket = client.post(
        "/api/assets/upload-url",
        headers=_headers(owner_a),
        json={
            "filename": "clip.mp4",
            "mime": "video/mp4",
            "size_bytes": 1024,
            "kind": "video",
            "project_id": project_b_id,
        },
    )
    assert ticket.status_code == 404, "Cross-owner project upload must be refused with 404"


def test_upload_ticket_with_invalid_project_id_rejected(client: TestClient) -> None:
    ticket = client.post(
        "/api/assets/upload-url",
        headers=_headers(uuid.uuid4()),
        json={
            "filename": "clip.mp4",
            "mime": "video/mp4",
            "size_bytes": 1024,
            "kind": "video",
            "project_id": "not-a-valid-uuid",
        },
    )
    assert ticket.status_code == 422


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------
def test_job_idempotency_key_returns_the_same_job(client: TestClient) -> None:
    owner = uuid.uuid4()
    asset_id = _uploaded_asset(client, owner)

    first = client.post(
        "/api/assets/complete",
        headers={**_headers(owner), "Idempotency-Key": "probe-once"},
        json={"asset_id": asset_id},
    )
    assert first.status_code == 202, first.text
    assert first.json()["job_id"]

    second = client.post(
        "/api/assets/complete",
        headers={**_headers(owner), "Idempotency-Key": "probe-once"},
        json={"asset_id": asset_id},
    )
    assert second.status_code == 200
    assert second.json()["job_id"] == first.json()["job_id"]
    assert second.json()["reused"] is True


def test_job_is_not_visible_to_another_owner(client: TestClient) -> None:
    owner = uuid.uuid4()
    asset_id = _uploaded_asset(client, owner)
    job_id = client.post(
        "/api/assets/complete", headers=_headers(owner), json={"asset_id": asset_id}
    ).json()["job_id"]

    assert client.get(f"/api/jobs/{job_id}", headers=_headers(owner)).status_code == 200
    assert client.get(f"/api/jobs/{job_id}", headers=_headers(uuid.uuid4())).status_code == 404


def test_job_poll_shape(client: TestClient) -> None:
    owner = uuid.uuid4()
    asset_id = _uploaded_asset(client, owner)
    job_id = client.post(
        "/api/assets/complete", headers=_headers(owner), json={"asset_id": asset_id}
    ).json()["job_id"]

    body = client.get(f"/api/jobs/{job_id}", headers=_headers(owner)).json()
    assert set(body) >= {"id", "status", "stage", "progress", "attempts"}
    assert body["status"] in {"queued", "running", "succeeded", "failed", "cancelled"}
    # An unfinished job must not hand back a result that does not exist.
    if body["status"] != "succeeded":
        assert "result" not in body


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _create_intent(
    client: TestClient, owner: uuid.UUID, subject: str = "a 30 second reel explaining how to cold email a founder"
) -> str:
    response = client.post(
        "/api/creation/intents",
        headers=_headers(owner),
        json={"primary_text": f"I want to create {subject}"},
    )
    assert response.status_code == 201, response.text
    return response.json()["intent"]["id"]


def _project_id_for(client: TestClient, owner: uuid.UUID, intent_id: str) -> str:
    return client.get(
        f"/api/creation/intents/{intent_id}", headers=_headers(owner)
    ).json()["intent"]["project_id"]


def _ready_workflow(
    client: TestClient, owner: uuid.UUID, subject: str = "a 30 second reel explaining how to cold email a founder"
) -> tuple[dict, list[dict]]:
    intent_id = _create_intent(client, owner, subject=subject)
    blueprint = client.post(
        "/api/creation/blueprints", headers=_headers(owner), json={"intent_id": intent_id}
    ).json()["blueprint"]
    project_id = _project_id_for(client, owner, intent_id)
    workflow = client.post(
        f"/api/projects/{project_id}/workflows",
        headers=_headers(owner),
        json={"blueprint_id": blueprint["id"]},
    ).json()["workflow"]
    return workflow, workflow["steps"]


def _uploaded_asset(client: TestClient, owner: uuid.UUID) -> str:
    ticket = client.post(
        "/api/assets/upload-url",
        headers=_headers(owner),
        json={"filename": "clip.mp4", "mime": "video/mp4", "size_bytes": 4096, "kind": "video"},
    ).json()
    client.put(
        f"/api/assets/{ticket['asset_id']}/content",
        headers={**_headers(owner), "content-type": "video/mp4"},
        content=_tiny_mp4_bytes(),
    )
    return str(ticket["asset_id"])


def step_keys_match(steps: list[dict], stage_keys: list[str]) -> bool:
    """Every blueprint stage became a step, in the same order."""
    if len(steps) != len(stage_keys):
        return False
    return all(step["key"] == key for step, key in zip(steps, stage_keys, strict=True))


def _tiny_mp4_bytes() -> bytes:
    """The smallest byte string with a real `ftyp` MP4 signature."""
    return b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom" + b"\x00" * 64
