"""FastAPI surface: the room's websocket, the state view, and the learner's own data.

A thin adapter over `session/runtime.py`. Nothing here makes a tutoring decision; if a rule appears
in this file it is in the wrong place and it will not be covered by the evals.

`export` and `delete` are here from M0 rather than bolted on later, because DECISIONS.md D3 says
the learner owns the model. Ownership that cannot be exercised is not ownership, and a schema with
no `org_id` is only half of the commitment.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from ..model.readable import ReadableState
from ..model.skills import ClaimLevel, SkillView
from ..observe.strokes import Point, Stroke
from ..seed.linear_equations import PROBLEMS, SKILLS, TITLE, TOPIC_ID
from ..session.runtime import Session, Topic

app = FastAPI(title="Atrium", version="0.1.0")

#: In-memory for M0. Redis holds this in production (§4, §11); sessions are reconstructible from
#: the event log either way.
SESSIONS: dict[str, Session] = {}


def seeded_topic() -> Topic:
    return Topic(
        id=TOPIC_ID, title=TITLE, skills=[s["id"] for s in SKILLS], problems=PROBLEMS
    )


class OpenSession(BaseModel):
    learner_id: str
    topic_id: str = TOPIC_ID
    problem_id: str | None = None


class SessionOpened(BaseModel):
    session_id: str
    topic_id: str
    problem: dict[str, Any]


class LearnerState(BaseModel):
    """§9: what a human is shown instead of a test score."""

    learner_id: str
    readable: ReadableState | None = None
    skills: list[SkillView] = []


@app.get("/topics")
def topics() -> list[dict[str, Any]]:
    topic = seeded_topic()
    return [{"id": topic.id, "title": topic.title, "skills": topic.skills}]


@app.post("/sessions", response_model=SessionOpened)
def open_session(body: OpenSession) -> SessionOpened:
    topic = seeded_topic()
    if body.problem_id:
        chosen = [p for p in topic.problems if p["id"] == body.problem_id]
        if not chosen:
            raise HTTPException(404, f"no problem {body.problem_id}")
        topic.problems = chosen
    session = Session(topic, body.learner_id)
    SESSIONS[session.id] = session
    return SessionOpened(session_id=session.id, topic_id=topic.id, problem=session.problem)


@app.get("/sessions/{session_id}/events")
def session_events(session_id: str) -> list[dict[str, Any]]:
    session = _session(session_id)
    return [event.model_dump(mode="json") for event in session.log.events]


@app.get("/learners/{learner_id}/state", response_model=LearnerState)
def learner_state(learner_id: str) -> LearnerState:
    """§9. Skill estimates, evidence counts, readable state, links to the actual evidence.

    Wired to the ledger at M6; the shape is fixed now so the room has somewhere to deposit.
    """
    return LearnerState(learner_id=learner_id, skills=[])


@app.get("/learners/{learner_id}/export")
def export_learner(learner_id: str) -> dict[str, Any]:
    """D3: the learner owns this and can take it away."""
    return {"learner_id": learner_id, "sessions": [], "evidence": [], "struggles": []}


@app.delete("/learners/{learner_id}")
def delete_learner(learner_id: str) -> dict[str, str]:
    """D3: and can delete it. Hard delete, not a flag."""
    for session_id in [s for s, sess in SESSIONS.items() if sess.learner_id == learner_id]:
        SESSIONS.pop(session_id, None)
    return {"deleted": learner_id}


class Hub:
    """Fan-out for a session. Every client sees every stroke — that is M0's acceptance test."""

    def __init__(self) -> None:
        self.sockets: dict[str, list[WebSocket]] = {}

    async def join(self, session_id: str, socket: WebSocket) -> None:
        await socket.accept()
        self.sockets.setdefault(session_id, []).append(socket)

    def leave(self, session_id: str, socket: WebSocket) -> None:
        if socket in self.sockets.get(session_id, []):
            self.sockets[session_id].remove(socket)

    async def broadcast(self, session_id: str, message: dict[str, Any], skip: WebSocket) -> None:
        for socket in list(self.sockets.get(session_id, [])):
            if socket is skip:
                continue
            try:
                await socket.send_json(message)
            except RuntimeError:
                self.leave(session_id, socket)


HUB = Hub()


@app.websocket("/ws/{session_id}")
async def room(socket: WebSocket, session_id: str) -> None:
    session = SESSIONS.get(session_id)
    if session is None:
        await socket.close(code=4404)
        return

    await HUB.join(session_id, socket)
    client = session.join(0.0)
    await socket.send_json(
        {"type": "joined", "client_id": client.id, "producer": client.is_producer}
    )

    try:
        while True:
            message = await socket.receive_json()
            kind = message.get("type")
            t_s = float(message.get("t_s", 0.0))

            if kind == "stroke":
                stroke = Stroke(
                    id=message["id"],
                    erase=bool(message.get("erase", False)),
                    points=[Point.model_validate(p) for p in message.get("points", [])],
                )
                # Only the producer's strokes are evidence (D2); everyone's are mirrored, so a
                # tutor looking over a shoulder can point at things.
                if client.is_producer:
                    session.on_stroke(stroke, t_s, client.id)
                await HUB.broadcast(session_id, {**message, "from": client.id}, skip=socket)

            elif kind == "snapshot" and client.is_producer:
                import base64

                png = base64.b64decode(message["png"])
                events = session.on_snapshot(png, t_s)
                await socket.send_json(
                    {"type": "recognised", "events": [e.model_dump() for e in events]}
                )
                move, text = session.step(t_s)
                if text:
                    await socket.send_json(
                        {"type": "tutor", "move": move.type.value, "text": text}
                    )

            elif kind == "speech" and client.is_producer:
                session.on_learner_speech(
                    message["text"], t_s, is_question=bool(message.get("question"))
                )
                move, text = session.step(t_s)
                if text:
                    await socket.send_json(
                        {"type": "tutor", "move": move.type.value, "text": text}
                    )

            elif kind == "tick":
                boundary = session.tick(t_s)
                if boundary is not None:
                    await socket.send_json(
                        {"type": "boundary", "region": boundary.region.model_dump()}
                    )

    except WebSocketDisconnect:
        pass
    finally:
        HUB.leave(session_id, socket)
        session.leave(0.0, client.id)


def _session(session_id: str) -> Session:
    session = SESSIONS.get(session_id)
    if session is None:
        raise HTTPException(404, "no such session")
    return session


__all__ = ["ClaimLevel", "app"]
