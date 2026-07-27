"""Intervention timing eval. SPEC.md §10.

Skips until real labelled sessions exist — see `score.py` for why they cannot be synthesised. What
*is* tested unconditionally is the property the whole trigger table rests on: silence is the
default, and an idle learner who is thinking never gets interrupted.
"""

from __future__ import annotations

import pytest

from atrium.observe.situation import Situation
from atrium.policy.budget import SilenceBudget
from atrium.policy.triggers import choose
from evals.timing.score import FIXTURES, score_all

#: Not a build gate yet — the first real number sets the bar. Recorded here so the intent is not
#: lost: §10 says no other metric compensates for interrupting a thinking learner.
FALSE_INTERRUPTION_TARGET = 0.02


def test_labelled_sessions_present() -> None:
    _, count = score_all()
    if count == 0:
        pytest.skip(f"no labelled sessions in {FIXTURES} — §10 wants 20 recorded and hand-labelled")
    assert count >= 20, f"§10 asks for 20 recorded sessions, found {count}"


def test_false_interruption_rate() -> None:
    score, count = score_all()
    if count == 0:
        pytest.skip("no labelled sessions yet")
    assert score.false_interruption_rate <= FALSE_INTERRUPTION_TARGET, (
        f"false interruption rate {score.false_interruption_rate:.2%} — "
        f"precision {score.precision:.2f}, recall {score.recall:.2f}"
    )


@pytest.mark.parametrize("seconds_idle", [0, 5, 15, 30, 44])
def test_thinking_is_never_interrupted(seconds_idle: int) -> None:
    """A learner mid-thought, below the stall threshold, with nothing wrong on screen.

    The room says nothing. This is the single most important behaviour in the product and it does
    not depend on a corpus.
    """
    situation = Situation(
        activity="idle",
        seconds_since_production=seconds_idle,
        consumption_debt_s=0,
        topic_id="linear-equations",
    )
    move = choose(situation, SilenceBudget(), now_s=float(seconds_idle))
    assert not move.speaks, f"interrupted a thinking learner at {seconds_idle}s with {move.type}"
