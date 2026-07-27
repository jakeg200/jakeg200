"""The Observer. Answers one question continuously: what is this person doing right now?

`Situation` is the sole input to the tutor policy (SPEC.md §5), which is why it is small, flat, and
serialisable. It is what gets logged, replayed, and scored against the intervention-timing corpus.
Resist adding fields — anything the policy cannot act on is weight in every log line forever.
"""

from __future__ import annotations

from collections import deque
from typing import Final, Literal

from pydantic import BaseModel

from ..verify.base import Verification
from ..verify.ladder import Ladder
from .recognise import CanvasEvent, CanvasEventType, RecognisedLine

Activity = Literal["producing", "consuming", "idle", "asking", "stalled"]

STALL_S: Final = 45  # §6: no production for 45s after activity
PRODUCING_S: Final = 5
CONSUMING_S: Final = 3
ERASURE_WINDOW_S: Final = 60  # §6: 3+ erasures of the same line in 60s


class Situation(BaseModel):
    activity: Activity
    latest_line: RecognisedLine | None = None
    verified: Verification | None = None
    seconds_since_production: int = 0
    consumption_debt_s: int = 0
    erasure_count_window: int = 0
    topic_id: str = ""
    open_question: str | None = None

    #: Not in the §5 list, but the policy cannot honour "OFFER_ANALOGY only after 2 failed probes"
    #: without it, and it is one integer.
    failed_probes: int = 0


class Observer:
    """Folds canvas events, speech, and timers into a `Situation`.

    Single-producer by construction — DECISIONS.md D2. Several clients may be attached to a
    session, but exactly one is producing, and this class models that one person.
    """

    def __init__(self, topic_id: str, ladder: Ladder | None = None) -> None:
        self.topic_id = topic_id
        self.ladder = ladder or Ladder()
        self.lines: list[str] = []
        self.latest_line: RecognisedLine | None = None
        self.verified: Verification | None = None

        self.last_production_s: float | None = None
        self.last_tutor_output_s: float | None = None
        self.consumption_debt_s: float = 0.0
        self.open_question: str | None = None
        self.failed_probes: int = 0
        self._erasures: deque[tuple[int, float]] = deque()

    # --- inputs -------------------------------------------------------------------------

    def on_canvas_events(
        self, events: list[CanvasEvent], lines: list[str], at_s: float
    ) -> None:
        self.lines = lines
        for event in events:
            if event.type in (CanvasEventType.LINE_ERASED, CanvasEventType.LINE_STRUCK_THROUGH):
                self._erasures.append((event.line_index, at_s))
                continue
            # An add or an edit is production: they put something of their own on the page.
            self._produced(at_s)
            self.latest_line = RecognisedLine(latex=event.latex, is_new=True)

        self._trim_erasures(at_s)
        if self.latest_line is not None and len(self.lines) >= 2:
            self.verified = self.ladder.verify_chain(self.lines)[-1]
        elif self.latest_line is not None:
            self.verified = None

    def on_learner_speech(self, text: str, at_s: float, *, is_question: bool = False) -> None:
        if is_question:
            self.open_question = text
            return
        # "a spoken explanation of at least one clause" counts as production (§6).
        if len(text.split()) >= 4:
            self._produced(at_s)

    def on_probe_answered(self, at_s: float, *, correct: bool = True) -> None:
        if correct:
            self._produced(at_s)
            self.failed_probes = 0
        else:
            self.failed_probes += 1

    def on_tutor_output(self, seconds: float, at_s: float) -> None:
        """Tutor said something lasting `seconds`. That is debt until they produce again (§6)."""
        self.consumption_debt_s += seconds
        self.last_tutor_output_s = at_s

    def on_question_answered(self) -> None:
        self.open_question = None

    def _produced(self, at_s: float) -> None:
        self.last_production_s = at_s
        self.consumption_debt_s = 0.0

    def _trim_erasures(self, now_s: float) -> None:
        while self._erasures and now_s - self._erasures[0][1] > ERASURE_WINDOW_S:
            self._erasures.popleft()

    # --- output -------------------------------------------------------------------------

    def erasure_count(self, now_s: float) -> int:
        """Erasures of the *same* line inside the window — the stall signal from §5, not a
        total. Someone tidying three different lines is working; someone rubbing out one line
        three times is stuck."""
        self._trim_erasures(now_s)
        counts: dict[int, int] = {}
        for index, _ in self._erasures:
            counts[index] = counts.get(index, 0) + 1
        return max(counts.values(), default=0)

    def situation(self, now_s: float) -> Situation:
        since_production = (
            int(now_s - self.last_production_s) if self.last_production_s is not None else 0
        )
        since_output = (
            now_s - self.last_tutor_output_s if self.last_tutor_output_s is not None else None
        )

        activity: Activity
        if self.open_question:
            activity = "asking"
        elif self.last_production_s is not None and since_production <= PRODUCING_S:
            activity = "producing"
        elif since_output is not None and since_output <= CONSUMING_S:
            activity = "consuming"
        elif self.last_production_s is not None and since_production >= STALL_S:
            activity = "stalled"
        else:
            activity = "idle"

        return Situation(
            activity=activity,
            latest_line=self.latest_line,
            verified=self.verified,
            seconds_since_production=since_production,
            consumption_debt_s=int(self.consumption_debt_s),
            erasure_count_window=self.erasure_count(now_s),
            topic_id=self.topic_id,
            open_question=self.open_question,
            failed_probes=self.failed_probes,
        )
