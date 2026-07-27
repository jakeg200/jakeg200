"""The session runtime end to end, and the Observer's reading of activity. SPEC.md §4, §5.

Runs with a scripted recogniser and a scripted realiser, so the loop is exercised without a model
call and the assertions are about the machinery rather than about prose.
"""

from __future__ import annotations

from atrium.observe.recognise import BBox, Reading, RecognisedLine
from atrium.observe.situation import Observer
from atrium.observe.strokes import Point, Stroke, StrokeBuffer
from atrium.policy.leakage import LeakageContext
from atrium.policy.moves import Move, MoveType
from atrium.policy.realise import Realisation
from atrium.seed.linear_equations import PROBLEMS, SKILLS, TITLE, TOPIC_ID
from atrium.session.events import EventType
from atrium.session.runtime import Session, Topic
from atrium.verify.base import Verdict


class ScriptedRecogniser:
    """Yields a prepared reading each time the canvas is snapshotted."""

    def __init__(self, readings: list[list[str]]) -> None:
        self.readings = readings
        self.calls = 0

    def read(self, png: bytes, previous: Reading) -> Reading:  # noqa: ARG002
        lines = self.readings[min(self.calls, len(self.readings) - 1)]
        self.calls += 1
        return Reading(lines=[RecognisedLine(latex=item) for item in lines])


class ScriptedRealiser:
    def realise(  # noqa: ARG002
        self, move: Move, situation: object, ctx: LeakageContext, **_: object
    ) -> Realisation:
        return Realisation(text=f"[{move.type.value}]", move=move)


def _topic() -> Topic:
    return Topic(
        id=TOPIC_ID,
        title=TITLE,
        skills=[s["id"] for s in SKILLS],
        problems=[p for p in PROBLEMS if p["id"] == "le-03"],
    )


def _stroke(sid: str, x: float, y: float, t: int) -> Stroke:
    return Stroke(id=sid, points=[Point(x=x, y=y, t=t), Point(x=x + 10, y=y + 2, t=t + 40)])


# --- stroke buffering (§5) ---------------------------------------------------------------------


def test_idle_boundary_fires_after_900ms() -> None:
    buffer = StrokeBuffer()
    assert buffer.add(_stroke("s1", 0, 0, 0)) is None
    assert buffer.tick(500) is None
    boundary = buffer.tick(1000)
    assert boundary is not None
    assert boundary.reason == "idle"


def test_region_change_flushes_without_waiting() -> None:
    """A learner who starts the next line immediately never goes idle (§5)."""
    buffer = StrokeBuffer()
    buffer.add(_stroke("s1", 0, 0, 0))
    boundary = buffer.add(_stroke("s2", 0, 400, 50))
    assert boundary is not None
    assert boundary.reason == "region_change"
    assert boundary.stroke_ids == ["s1"]


def test_bbox_union_covers_the_written_region() -> None:
    buffer = StrokeBuffer()
    buffer.add(_stroke("s1", 0, 0, 0))
    buffer.add(_stroke("s2", 5, 2, 10))
    boundary = buffer.tick(2000)
    assert boundary is not None
    assert isinstance(boundary.region, BBox)
    assert boundary.region.w >= 15


# --- the Observer (§5) --------------------------------------------------------------------------


def test_erasing_the_same_line_repeatedly_is_the_stall_signal() -> None:
    from atrium.observe.recognise import CanvasEvent, CanvasEventType

    observer = Observer("linear-equations")
    for at in (1.0, 20.0, 40.0):
        observer.on_canvas_events(
            [CanvasEvent(type=CanvasEventType.LINE_ERASED, line_index=2)], ["3x + 8 = 23"], at
        )
    assert observer.erasure_count(45.0) == 3
    # Different lines are tidying, not being stuck.
    other = Observer("linear-equations")
    for index, at in enumerate((1.0, 20.0, 40.0)):
        other.on_canvas_events(
            [CanvasEvent(type=CanvasEventType.LINE_ERASED, line_index=index)], [], at
        )
    assert other.erasure_count(45.0) == 1


def test_erasures_leave_the_window() -> None:
    from atrium.observe.recognise import CanvasEvent, CanvasEventType

    observer = Observer("t")
    observer.on_canvas_events(
        [CanvasEvent(type=CanvasEventType.LINE_ERASED, line_index=1)], [], 1.0
    )
    assert observer.erasure_count(200.0) == 0


def test_activity_moves_from_producing_to_stalled() -> None:
    from atrium.observe.recognise import CanvasEvent, CanvasEventType

    observer = Observer("t")
    observer.on_canvas_events(
        [CanvasEvent(type=CanvasEventType.LINE_ADDED, line_index=0, latex="3x + 8 = 23")],
        ["3x + 8 = 23"],
        10.0,
    )
    assert observer.situation(11.0).activity == "producing"
    assert observer.situation(30.0).activity == "idle"
    assert observer.situation(60.0).activity == "stalled"


def test_tutor_output_accrues_debt_and_production_clears_it() -> None:
    from atrium.observe.recognise import CanvasEvent, CanvasEventType

    observer = Observer("t")
    observer.on_tutor_output(40.0, 10.0)
    observer.on_tutor_output(60.0, 20.0)
    assert observer.situation(25.0).consumption_debt_s == 100
    observer.on_canvas_events(
        [CanvasEvent(type=CanvasEventType.LINE_ADDED, line_index=0, latex="3x = 15")],
        ["3x + 8 = 23", "3x = 15"],
        30.0,
    )
    assert observer.situation(31.0).consumption_debt_s == 0


def test_a_spoken_explanation_counts_as_production() -> None:
    observer = Observer("t")
    observer.on_tutor_output(120.0, 5.0)
    observer.on_learner_speech("because both sides have to stay balanced", 20.0)
    assert observer.situation(21.0).consumption_debt_s == 0


def test_a_grunt_does_not_count_as_production() -> None:
    observer = Observer("t")
    observer.on_tutor_output(120.0, 5.0)
    observer.on_learner_speech("yeah ok", 20.0)
    assert observer.situation(21.0).consumption_debt_s > 0


# --- the session loop (§4) ----------------------------------------------------------------------


def test_two_clients_share_a_session_and_only_one_produces() -> None:
    """M0 acceptance, and DECISIONS.md D2."""
    session = Session(_topic(), "learner-1", recogniser=ScriptedRecogniser([[]]))
    first = session.join(0.0)
    second = session.join(1.0)
    assert first.is_producer
    assert not second.is_producer
    assert len(session.clients) == 2


def test_strokes_are_logged_for_replay() -> None:
    session = Session(_topic(), "l1", recogniser=ScriptedRecogniser([[]]))
    client = session.join(0.0)
    session.on_stroke(_stroke("s1", 0, 0, 0), 0.1, client.id)
    assert len(session.log.of_type(EventType.STROKE)) == 1


def test_recognition_produces_canvas_events_and_verification() -> None:
    session = Session(
        _topic(),
        "l1",
        recogniser=ScriptedRecogniser([["3x + 8 = 23"], ["3x + 8 = 23", "3x = 31"]]),
        realiser=ScriptedRealiser(),  # type: ignore[arg-type]
    )
    session.join(0.0)
    session.on_snapshot(b"png", 1.0)
    events = session.on_snapshot(b"png", 2.0)
    assert len(events) == 1
    assert session.observer.verified is not None
    assert session.observer.verified.verdict is Verdict.INVALID


def test_a_wrong_line_is_probed_not_corrected() -> None:
    session = Session(
        _topic(),
        "l1",
        recogniser=ScriptedRecogniser([["3x + 8 = 23"], ["3x + 8 = 23", "3x = 31"]]),
        realiser=ScriptedRealiser(),  # type: ignore[arg-type]
    )
    session.join(0.0)
    session.on_snapshot(b"png", 1.0)
    session.on_snapshot(b"png", 2.0)
    move, text = session.step(3.0)
    assert move.type is MoveType.ASK_PROBE
    assert move.target_line_index == 1
    assert text


def test_correct_work_is_left_alone() -> None:
    session = Session(
        _topic(),
        "l1",
        recogniser=ScriptedRecogniser([["3x + 8 = 23"], ["3x + 8 = 23", "3x = 15"]]),
        realiser=ScriptedRealiser(),  # type: ignore[arg-type]
    )
    session.join(0.0)
    session.on_snapshot(b"png", 1.0)
    session.on_snapshot(b"png", 2.0)
    move, _ = session.step(2.5)
    assert move.type in (MoveType.CONFIRM, MoveType.OBSERVE)


def test_leakage_context_excludes_lines_already_written() -> None:
    session = Session(
        _topic(), "l1", recogniser=ScriptedRecogniser([["3x + 8 = 23", "3x = 15"]])
    )
    session.join(0.0)
    session.on_snapshot(b"png", 1.0)
    ctx = session.leakage_context()
    assert "3x = 15" not in ctx.remaining
    assert "x = 5" in ctx.remaining
    assert ctx.final_answer == "x = 5"


def test_repeated_demands_escalate_the_fade_example() -> None:
    """DECISIONS.md D1: the fourth flat demand may be met with a fully worked *other* problem."""
    session = Session(_topic(), "l1", recogniser=ScriptedRecogniser([[]]))
    session.join(0.0)
    for at in (10.0, 20.0, 30.0):
        session.on_learner_speech("just tell me the answer", at, is_question=True)
    assert session._analogue() is not None
    assert not session._analogue().fully_worked  # type: ignore[union-attr]
    session.on_learner_speech("just tell me the answer", 40.0, is_question=True)
    assert session._analogue().fully_worked  # type: ignore[union-attr]


def test_the_event_log_replays() -> None:
    session = Session(_topic(), "l1", recogniser=ScriptedRecogniser([[]]))
    session.join(0.0)
    session.on_stroke(_stroke("s1", 0, 0, 0), 0.5)
    session.close(9.0)
    types = [e.type for e in session.log.events]
    assert types[0] is EventType.SESSION_OPENED
    assert types[-1] is EventType.SESSION_CLOSED
    assert all(e.session_id == session.id for e in session.log.events)
