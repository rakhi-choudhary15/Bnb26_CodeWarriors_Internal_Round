"""End-to-end regression test for the 3-minute hackathon demo critical flow.

Exercises:
1. Intent creation & analysis
2. Blueprint generation
3. Workflow instantiation
4. Step execution & output provenance
5. Reference DNA extraction
6. Asset upload reservation
7. Content Genome retrieval
8. Impact propagation simulation
9. Impact resolution
10. Multi-platform adaptation
11. Publishing package creation
12. Creator Intelligence & Content Archaeology
"""

import uuid

from fastapi.testclient import TestClient

DEMO_OWNER = uuid.UUID("11111111-1111-1111-1111-111111111111")
DEMO_OTHER_OWNER = uuid.UUID("22222222-2222-2222-2222-222222222222")

def _headers(owner_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer dev:{owner_id}"}


def test_full_critical_demo_user_flow(client: TestClient) -> None:
    headers = _headers(DEMO_OWNER)

    # 1. Intent Analysis
    r1 = client.post(
        "/api/creation/intents",
        headers=headers,
        json={
            "primary_text": "I want to create a 30-second energetic dance Reel for Instagram",
            "details_text": "Bollywood-inspired, Gen-Z audience, high energy",
        },
    )
    assert r1.status_code == 201, r1.text
    data1 = r1.json()
    project_id = data1["project_id"]
    intent_id = data1["intent"]["id"]

    # 2. Blueprint Assembly
    r2 = client.post(
        "/api/creation/blueprints",
        headers=headers,
        json={"intent_id": intent_id},
    )
    assert r2.status_code == 201, r2.text
    data2 = r2.json()
    bp_id = data2["blueprint"]["id"]
    assert len(data2["blueprint"]["stages"]) >= 8

    # 3. Workflow Start
    r3 = client.post(
        f"/api/projects/{project_id}/workflows",
        headers=headers,
        json={"blueprint_id": bp_id},
    )
    assert r3.status_code == 201, r3.text
    wf_id = r3.json()["workflow"]["id"]
    steps = r3.json()["workflow"]["steps"]
    assert len(steps) >= 8

    # 4. Step Execution
    first_step_id = steps[0]["id"]
    r4 = client.post(
        f"/api/workflows/{wf_id}/steps/{first_step_id}/run",
        headers=headers,
    )
    assert r4.status_code == 200, r4.text
    assert "result" in r4.json()

    # 5. Reference DNA
    r5 = client.post(
        "/api/references",
        headers=headers,
        json={"title": "Bollywood Inspiration"},
    )
    assert r5.status_code == 201, r5.text
    ref_id = r5.json()["id"]

    r5b = client.post(
        "/api/references/analyze",
        headers=headers,
        json={"reference_id": ref_id},
    )
    assert r5b.status_code == 200, r5b.text
    assert "hook_duration_s" in r5b.json()["dna"]

    # 6. Asset Ingest Reservation
    r6 = client.post(
        "/api/assets/upload-url",
        headers=headers,
        json={
            "filename": "dance_take_01.mp4",
            "mime": "video/mp4",
            "size_bytes": 1024 * 1024,
            "kind": "video",
            "project_id": project_id,
        },
    )
    assert r6.status_code == 201, r6.text
    assert "upload_url" in r6.json()

    # 7. Content Genome
    r7 = client.get(
        f"/api/content-genome/{project_id}",
        headers=headers,
    )
    assert r7.status_code == 200, r7.text
    nodes = r7.json()["nodes"]
    assert len(nodes) >= 5

    # 8. Impact Propagation
    hook_nodes = [n for n in nodes if n["type"] == "hook"]
    trigger_node = hook_nodes[0] if hook_nodes else nodes[1]
    r8 = client.post(
        "/api/content-genome/propagate",
        headers=headers,
        json={
            "trigger_node_id": trigger_node["id"],
            "before_text": "Stop scrolling, try this Bollywood pop step!",
            "after_text": "Stop scrolling, TRANSFORM your footwork with this move!",
        },
    )
    assert r8.status_code == 200, r8.text
    impact_event_id = r8.json()["impact_event_id"]

    # 9. Impact Resolution
    r9 = client.post(
        f"/api/content-genome/impacts/{impact_event_id}/resolve",
        headers=headers,
        json={"action": "update_all"},
    )
    assert r9.status_code == 200, r9.text

    # 10. Multi-Platform Adaptation
    r10 = client.post(
        "/api/platform/adapt",
        headers=headers,
        json={"project_id": project_id},
    )
    assert r10.status_code == 200, r10.text
    variants = r10.json()["variants"]
    assert len(variants) >= 4

    # 11. Publishing Package
    v0_id = variants[0]["id"]
    r11 = client.post(
        "/api/publishing/jobs",
        headers=headers,
        json={"variant_id": v0_id},
    )
    assert r11.status_code == 201, r11.text

    # 12. Creator Intelligence & Content Archaeology
    r12 = client.get("/api/creator-intelligence", headers=headers)
    assert r12.status_code == 200, r12.text

    r13 = client.get("/api/content-opportunities", headers=headers)
    assert r13.status_code == 200, r13.text
    assert len(r13.json()["items"]) >= 1
