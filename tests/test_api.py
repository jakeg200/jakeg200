from __future__ import annotations

from fastapi.testclient import TestClient


def _learner(client: TestClient, handle: str = "sam") -> str:
    return str(client.post("/learners", json={"handle": handle}).json()["id"])


def test_health_and_seed(client: TestClient) -> None:
    assert client.get("/healthz").json() == {"status": "ok"}
    tasks = client.get("/tasks").json()
    assert len(tasks) == 12


def test_task_payload_withholds_the_answer(client: TestClient) -> None:
    """No client-facing task representation carries the canonical answer."""
    task = client.get("/tasks/lin-eq-007").json()
    assert "canonical_answer" not in task


def test_attempt_returns_the_chain_the_break_and_a_probe(client: TestClient) -> None:
    learner = _learner(client)
    response = client.post(
        "/attempts",
        json={
            "learner_id": learner,
            "task_id": "lin-eq-007",
            "raw_text": "7x take away 3x is 4x, and -2 add 10 is 8, so 4x = 8 and x = 2",
            "mode": "unassisted",
            "attested": True,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body["steps"]) == 4
    assert body["diagnosis"]["first_break_index"] == 1
    assert body["diagnosis"]["misconception_name"] == "Sign lost moving a term"
    assert body["probe"]
    assert "x = 3" not in body["probe"]
    assert body["coverage"]["steps"] == 4


def test_evidence_is_redacted_on_the_way_out(client: TestClient) -> None:
    learner = _learner(client)
    body = client.post(
        "/attempts",
        json={
            "learner_id": learner,
            "task_id": "lin-eq-007",
            "raw_text": "7x - 2 = 3x + 10\n4x = 8\nx = 2",
            "mode": "unassisted",
            "attested": True,
        },
    ).json()
    for step in body["steps"]:
        assert "x = 3" not in step["evidence"]


def test_unassisted_requires_an_attestation(client: TestClient) -> None:
    """Mode is self-declared, so declaring it has to be a deliberate act."""
    learner = _learner(client)
    payload = {
        "learner_id": learner,
        "task_id": "lin-eq-004",
        "raw_text": "4x + 5 = 17\n4x = 12\nx = 3",
        "mode": "unassisted",
    }
    assert client.post("/attempts", json=payload).status_code == 422
    assert client.post("/attempts", json={**payload, "attested": True}).status_code == 200


def test_assisted_needs_no_attestation(client: TestClient) -> None:
    learner = _learner(client)
    response = client.post(
        "/attempts",
        json={
            "learner_id": learner,
            "task_id": "lin-eq-004",
            "raw_text": "4x + 5 = 17\n4x = 12\nx = 3",
            "mode": "assisted",
        },
    )
    assert response.status_code == 200
    assert all(c["level"] == "not_evidenced" for c in response.json()["claims_updated"])


def test_mode_has_no_default(client: TestClient) -> None:
    learner = _learner(client)
    response = client.post(
        "/attempts",
        json={"learner_id": learner, "task_id": "lin-eq-004", "raw_text": "x = 3"},
    )
    assert response.status_code == 422


def test_attempt_can_be_fetched_back(client: TestClient) -> None:
    learner = _learner(client)
    created = client.post(
        "/attempts",
        json={
            "learner_id": learner,
            "task_id": "lin-eq-004",
            "raw_text": "4x + 5 = 17\n4x = 12\nx = 3",
            "mode": "unassisted",
            "attested": True,
        },
    ).json()
    fetched = client.get(f"/attempts/{created['id']}").json()
    assert [s["raw_text"] for s in fetched["steps"]] == [s["raw_text"] for s in created["steps"]]
    assert fetched["diagnosis"]["first_break_index"] is None


def test_record_endpoints(client: TestClient) -> None:
    learner = _learner(client, "recordee")
    client.post(
        "/attempts",
        json={
            "learner_id": learner,
            "task_id": "lin-eq-004",
            "raw_text": "4x + 5 = 17\n4x = 12\nx = 3",
            "mode": "unassisted",
            "attested": True,
        },
    )
    record = client.get(f"/learners/{learner}/record").json()
    assert record["signature"]["algorithm"] == "ed25519"
    assert record["mode_provenance"] == "self_declared"
    assert any(c["level"] == "emerging" for c in record["claims"])

    page = client.get(f"/learners/{learner}/record.html")
    assert page.status_code == 200
    assert "recordee" in page.text


def test_missing_things_are_404(client: TestClient) -> None:
    assert client.get("/tasks/nope").status_code == 404
    assert client.get("/attempts/nope").status_code == 404
    assert client.get("/learners/nope/record").status_code == 404
