"""M0 acceptance: two browsers join a session and see each other's strokes. SPEC.md §12."""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from atrium.api.app import app  # noqa: E402


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _open(client: TestClient) -> str:
    response = client.post("/sessions", json={"learner_id": "l1", "problem_id": "le-03"})
    assert response.status_code == 200
    return response.json()["session_id"]


def test_seeded_topic_is_served(client: TestClient) -> None:
    topics = client.get("/topics").json()
    assert topics[0]["id"] == "linear-equations"
    assert len(topics[0]["skills"]) == 4


def test_opening_a_session_returns_a_problem(client: TestClient) -> None:
    body = client.post("/sessions", json={"learner_id": "l1", "problem_id": "le-03"}).json()
    assert body["problem"]["statement"] == "3x + 8 = 23"


def test_unknown_problem_is_rejected(client: TestClient) -> None:
    response = client.post("/sessions", json={"learner_id": "l1", "problem_id": "nope"})
    assert response.status_code == 404


def test_two_browsers_see_each_others_strokes(client: TestClient) -> None:
    """The M0 acceptance test, verbatim."""
    session_id = _open(client)
    url = f"/ws/{session_id}"
    with client.websocket_connect(url) as first, client.websocket_connect(url) as second:
        opened_first = first.receive_json()
        opened_second = second.receive_json()
        assert opened_first["producer"] is True
        assert opened_second["producer"] is False, "single-producer, per DECISIONS.md D2"

        first.send_json(
            {"type": "stroke", "id": "s1", "t_s": 0.2, "points": [{"x": 1, "y": 1, "t": 0}]}
        )
        mirrored = second.receive_json()
        assert mirrored["id"] == "s1"
        assert mirrored["from"] == opened_first["client_id"]


def test_events_are_logged_for_replay(client: TestClient) -> None:
    session_id = _open(client)
    with client.websocket_connect(f"/ws/{session_id}") as socket:
        socket.receive_json()
        socket.send_json(
            {"type": "stroke", "id": "s1", "t_s": 0.2, "points": [{"x": 1, "y": 1, "t": 0}]}
        )
    events = client.get(f"/sessions/{session_id}/events").json()
    assert any(event["type"] == "stroke" for event in events)


def test_a_missing_session_is_refused(client: TestClient) -> None:
    # starlette raises on the 4404 close
    with pytest.raises(Exception), client.websocket_connect("/ws/nope") as socket:  # noqa: B017
        socket.receive_json()


def test_the_learner_can_export_and_delete_their_model(client: TestClient) -> None:
    """DECISIONS.md D3: ownership that cannot be exercised is not ownership."""
    _open(client)
    assert client.get("/learners/l1/export").status_code == 200
    assert client.delete("/learners/l1").json() == {"deleted": "l1"}
