"""Intervention timing. SPEC.md §10.

Record 20 real sessions. Have a human label every second with `should_speak: yes | no`. Score the
policy's choices as precision and recall against that.

**False-interruption rate is reported separately and is the number that matters.** Interrupting
someone who is thinking is the worst failure the room can make, and no other metric compensates for
it. A policy that speaks at every good moment and also at thirty bad ones has not scored well.

There are no fixtures in this repo yet, because the labels have to come from a human watching a
real session and there is no honest way to synthesise them. The harness is here so that the moment
the first session is recorded there is nothing to build. `test_timing.py` skips, loudly, until
`fixtures/` has sessions in it.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel

from atrium.observe.situation import Situation
from atrium.policy.budget import SilenceBudget
from atrium.policy.triggers import choose

FIXTURES = Path(__file__).parent / "fixtures"


class LabelledSecond(BaseModel):
    t_s: float
    situation: Situation
    should_speak: bool


class LabelledSession(BaseModel):
    session_id: str
    seconds: list[LabelledSecond]


class TimingScore(BaseModel):
    true_positive: int = 0
    false_positive: int = 0
    true_negative: int = 0
    false_negative: int = 0

    @property
    def precision(self) -> float:
        denom = self.true_positive + self.false_positive
        return self.true_positive / denom if denom else 1.0

    @property
    def recall(self) -> float:
        denom = self.true_positive + self.false_negative
        return self.true_positive / denom if denom else 1.0

    @property
    def false_interruption_rate(self) -> float:
        """Of all the seconds the human said 'do not speak', how often did we speak anyway?

        Reported separately from precision on purpose: precision hides this behind the seconds we
        got right, and this is the failure the room is judged on.
        """
        denom = self.false_positive + self.true_negative
        return self.false_positive / denom if denom else 0.0

    def __add__(self, other: TimingScore) -> TimingScore:
        return TimingScore(
            true_positive=self.true_positive + other.true_positive,
            false_positive=self.false_positive + other.false_positive,
            true_negative=self.true_negative + other.true_negative,
            false_negative=self.false_negative + other.false_negative,
        )


def score_session(session: LabelledSession) -> TimingScore:
    """Replay the policy over the labelled seconds. Pure — no model calls, no clock."""
    budget = SilenceBudget()
    score = TimingScore()
    for second in session.seconds:
        move = choose(second.situation, budget, second.t_s)
        spoke = move.speaks
        if spoke:
            budget.record(second.t_s, learner_initiated=second.situation.open_question is not None)
        if spoke and second.should_speak:
            score.true_positive += 1
        elif spoke and not second.should_speak:
            score.false_positive += 1
        elif not spoke and second.should_speak:
            score.false_negative += 1
        else:
            score.true_negative += 1
    return score


def load_sessions(directory: Path = FIXTURES) -> list[LabelledSession]:
    if not directory.exists():
        return []
    return [
        LabelledSession.model_validate(json.loads(path.read_text(encoding="utf-8")))
        for path in sorted(directory.glob("*.json"))
    ]


def score_all(directory: Path = FIXTURES) -> tuple[TimingScore, int]:
    sessions = load_sessions(directory)
    total = TimingScore()
    for session in sessions:
        total = total + score_session(session)
    return total, len(sessions)
