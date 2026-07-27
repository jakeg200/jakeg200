"""The session runtime: Observer → Verifier → Situation → Policy → Move → words.

One class holding the loop from SPEC.md §4, deliberately synchronous and clock-injected so the
whole thing replays deterministically from an event log. The websocket layer in `api/` is a thin
adapter over this; nothing in here knows what a socket is.

Multi-client, single-producer — DECISIONS.md D2. Several clients may attach and all of them see the
strokes (that is M0's acceptance test), but exactly one holds the producer role and the learner
model only ever attributes evidence to them.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..observe.recognise import (
    CanvasEvent,
    NullRecogniser,
    Reading,
    Recogniser,
    diff,
)
from ..observe.situation import Observer
from ..observe.strokes import Boundary, Stroke, StrokeBuffer
from ..policy.budget import SilenceBudget
from ..policy.leakage import LeakageContext
from ..policy.moves import Analogue, Move, MoveType
from ..policy.realise import Realiser, escalate_to_full_working
from ..policy.triggers import _is_answer_demand, choose
from ..verify.ladder import Ladder
from .events import EventLog, EventType


@dataclass
class Client:
    id: str
    is_producer: bool = False


@dataclass
class Topic:
    id: str
    title: str
    skills: list[str] = field(default_factory=list)
    problems: list[dict[str, Any]] = field(default_factory=list)


class Session:
    def __init__(
        self,
        topic: Topic,
        learner_id: str,
        session_id: str | None = None,
        recogniser: Recogniser | None = None,
        realiser: Realiser | None = None,
        log_path: Path | None = None,
    ) -> None:
        self.id = session_id or uuid.uuid4().hex
        self.topic = topic
        self.learner_id = learner_id
        self.clients: dict[str, Client] = {}

        self.log = EventLog(self.id, log_path)
        self.buffer = StrokeBuffer()
        self.recogniser = recogniser or NullRecogniser()
        self.realiser = realiser or Realiser()
        self.observer = Observer(topic.id, Ladder())
        self.budget = SilenceBudget()

        self.reading = Reading()
        self.strokes: list[Stroke] = []
        self.problem: dict[str, Any] = topic.problems[0] if topic.problems else {}
        self.answer_demands = 0
        self.tutor_moves: list[tuple[float, MoveType]] = []
        self.log.append(EventType.SESSION_OPENED, 0.0, {"topic": topic.id, "learner": learner_id})

    # --- clients ------------------------------------------------------------------------

    def join(self, t_s: float, client_id: str | None = None) -> Client:
        """First client in is the producer. Everyone after is a spectator (D2)."""
        client = Client(
            id=client_id or uuid.uuid4().hex,
            is_producer=not any(c.is_producer for c in self.clients.values()),
        )
        self.clients[client.id] = client
        self.log.append(
            EventType.CLIENT_JOINED, t_s, {"producer": client.is_producer}, client.id
        )
        return client

    def leave(self, t_s: float, client_id: str) -> None:
        client = self.clients.pop(client_id, None)
        if client is None:
            return
        self.log.append(EventType.CLIENT_LEFT, t_s, {}, client_id)
        # The producer role does not float to a spectator on disconnect: evidence attributed to
        # whoever happened to still be connected would be worse than no evidence.

    # --- canvas -------------------------------------------------------------------------

    def on_stroke(self, stroke: Stroke, t_s: float, client_id: str = "") -> Boundary | None:
        """Ingest a stroke. Returns a boundary if it is time to read the canvas."""
        self.strokes.append(stroke)
        self.log.append(
            EventType.STROKE, t_s, {"id": stroke.id, "erase": stroke.erase}, client_id
        )
        boundary = self.buffer.add(stroke)
        if boundary is not None:
            self.log.append(EventType.BOUNDARY, t_s, boundary.model_dump())
        return boundary

    def tick(self, t_s: float) -> Boundary | None:
        boundary = self.buffer.tick(int(t_s * 1000))
        if boundary is not None:
            self.log.append(EventType.BOUNDARY, t_s, boundary.model_dump())
        return boundary

    def on_snapshot(self, png: bytes, t_s: float) -> list[CanvasEvent]:
        """A region snapshot arrived. Recognise, diff, verify, and update the Situation."""
        reading = self.recogniser.read(png, self.reading)
        events = diff(self.reading, reading)
        self.reading = reading
        self.log.append(EventType.RECOGNISED, t_s, {"lines": [ln.latex for ln in reading.lines]})
        for event in events:
            self.log.append(EventType.CANVAS_EVENT, t_s, event.model_dump())

        self.observer.on_canvas_events(events, [ln.latex for ln in reading.lines], t_s)
        if self.observer.verified is not None:
            self.log.append(EventType.VERIFIED, t_s, self.observer.verified.model_dump())
        return events

    # --- speech -------------------------------------------------------------------------

    def on_learner_speech(self, text: str, t_s: float, *, is_question: bool = False) -> None:
        self.log.append(EventType.LEARNER_SAID, t_s, {"text": text, "question": is_question})
        if is_question and _is_answer_demand(text):
            self.answer_demands += 1
        self.observer.on_learner_speech(text, t_s, is_question=is_question)

    # --- the loop -----------------------------------------------------------------------

    def step(self, t_s: float) -> tuple[Move, str]:
        """One turn of the policy. Returns the chosen move and what was said (empty for OBSERVE).

        This is the function the timing eval replays. Keep it free of I/O beyond the log.
        """
        situation = self.observer.situation(t_s)
        self.log.append(EventType.SITUATION, t_s, situation.model_dump(mode="json"))

        move = choose(situation, self.budget, t_s, analogue=self._analogue())
        self.log.append(EventType.MOVE_CHOSEN, t_s, {"move": move.type.value, "why": move.trigger})

        if move.type is MoveType.OBSERVE:
            return move, ""

        realisation = self.realiser.realise(
            move, situation, self.leakage_context(), readable_state=""
        )
        for kind in realisation.blocked:
            self.log.append(EventType.LEAKAGE_BLOCKED, t_s, {"kind": kind, "move": move.type.value})

        learner_initiated = situation.open_question is not None
        self.budget.record(t_s, learner_initiated=learner_initiated)
        for breach in self.budget.breaches[len(self.log.of_type(EventType.BUDGET_BREACH)) :]:
            self.log.append(EventType.BUDGET_BREACH, t_s, breach.model_dump())

        # Speaking costs the learner time, which is debt until they produce again (§6).
        self.observer.on_tutor_output(_speaking_seconds(realisation.text), t_s)
        self.observer.on_question_answered()
        self.tutor_moves.append((t_s, move.type))
        self.log.append(
            EventType.TUTOR_SAID,
            t_s,
            {"text": realisation.text, "move": move.type.value, "fell_back": realisation.fell_back},
        )
        return move, realisation.text

    # --- context ------------------------------------------------------------------------

    def leakage_context(self) -> LeakageContext:
        written = [ln.latex for ln in self.reading.lines]
        canonical: list[str] = list(self.problem.get("solution_steps", []))
        remaining = [line for line in canonical if not _already_written(line, written)]
        return LeakageContext(
            live_problem=self.problem.get("statement", ""),
            learner_lines=written,
            remaining=remaining,
            final_answer=self.problem.get("answer", ""),
            variable=self.problem.get("variable", "x"),
        )

    def _analogue(self) -> Analogue | None:
        """The fade example, if the problem carries one.

        DECISIONS.md D1: after the third flat demand for the answer it may be fully worked. The
        distance guard in `realise.py` still has to pass — escalation changes how much of a
        different problem is shown, never which problem.
        """
        raw = self.problem.get("analogue")
        if not raw:
            return None
        return Analogue(
            problem=raw["statement"],
            worked_to_step=-1 if escalate_to_full_working(self.answer_demands) else 1,
            steps=raw.get("steps", []),
        )

    def close(self, t_s: float) -> None:
        self.log.append(EventType.SESSION_CLOSED, t_s, {})


def _already_written(line: str, written: list[str]) -> bool:
    target = line.replace(" ", "")
    return any(w.replace(" ", "") == target for w in written)


def _speaking_seconds(text: str) -> float:
    """Roughly 150 words per minute. The debt counter measures the learner's time, not tokens."""
    return len(text.split()) / 2.5
