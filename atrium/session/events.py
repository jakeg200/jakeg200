"""The event log. SPEC.md §4: session state is reconstructible from it.

Append-only and total: strokes, recognitions, verifications, moves, utterances, speech. Two things
depend on that being true —

* **Replay.** Every eval in §10 runs offline from recorded sessions. If a decision depended on
  something that was never logged, that eval is measuring a different system from the one that
  shipped.
* **Evidence links.** §9 requires the state view to link to *the actual moments of evidence*. An
  event id is that link.

Redis holds the live projection; this log is the truth it is rebuilt from.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class EventType(str, Enum):
    SESSION_OPENED = "session_opened"
    SESSION_CLOSED = "session_closed"
    CLIENT_JOINED = "client_joined"
    CLIENT_LEFT = "client_left"
    STROKE = "stroke"
    STROKE_UNDO = "stroke_undo"
    BOUNDARY = "boundary"
    RECOGNISED = "recognised"
    CANVAS_EVENT = "canvas_event"
    VERIFIED = "verified"
    SITUATION = "situation"
    MOVE_CHOSEN = "move_chosen"
    TUTOR_SAID = "tutor_said"
    LEAKAGE_BLOCKED = "leakage_blocked"
    BUDGET_BREACH = "budget_breach"
    LEARNER_SAID = "learner_said"
    PRODUCTION = "production"


class Event(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    session_id: str
    type: EventType
    at: datetime = Field(default_factory=datetime.utcnow)
    #: Seconds since session open. The log is replayed on this, not on wall clock.
    t_s: float = 0.0
    client_id: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)


class EventLog:
    """In-memory with optional JSONL durability.

    Postgres is where this lives in production (§11); the file backend exists so a recorded
    session is a file you can copy into `evals/fixtures/` and replay, which is what the timing and
    leakage corpora actually are.
    """

    def __init__(self, session_id: str, path: Path | None = None) -> None:
        self.session_id = session_id
        self.path = path
        self.events: list[Event] = []
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)

    def append(
        self,
        type: EventType,
        t_s: float,
        payload: dict[str, Any] | None = None,
        client_id: str = "",
    ) -> Event:
        event = Event(
            session_id=self.session_id,
            type=type,
            t_s=t_s,
            client_id=client_id,
            payload=payload or {},
        )
        self.events.append(event)
        if self.path is not None:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(event.model_dump_json() + "\n")
        return event

    def of_type(self, *types: EventType) -> list[Event]:
        wanted = set(types)
        return [e for e in self.events if e.type in wanted]

    @classmethod
    def replay(cls, path: Path) -> EventLog:
        raw = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
        session_id = raw[0]["session_id"] if raw else ""
        log = cls(session_id)
        log.events = [Event.model_validate(item) for item in raw]
        return log
