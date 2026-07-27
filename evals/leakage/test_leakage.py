"""Blocking eval: no tutor output ever contains the next line or the final answer.

SPEC.md §10. **Target: zero. A single failure fails the build.** M3's acceptance gate.

The corpus asserts against `policy.leakage.check` rather than against live model output, and that
is deliberate rather than a shortcut: the guard is the thing that has to hold. A prompt that
usually behaves is not a safety property, and an eval that passes because the model was in a good
mood is not evidence. What ships is the filter, so what is tested is the filter.
"""

from __future__ import annotations

import pytest

from atrium.policy.leakage import LeakageBlocked, LeakageContext, check, guard
from evals.leakage.corpus import build

CASES = build()


def test_corpus_is_large_enough() -> None:
    assert len(CASES) >= 200, "§10 asks for 200 adversarial situations"


def test_no_leak_escapes() -> None:
    escaped = [
        f"{case.id} [{case.note}] under pressure {case.pressure!r}: {case.text!r}"
        for case in CASES
        if case.must_block and check(case.text, case.ctx) is None
    ]
    assert not escaped, "leaks escaped the guard (target is zero):\n" + "\n".join(escaped[:20])


def test_legitimate_moves_are_not_blocked() -> None:
    """Not safety-critical, but a guard that blocks everything is a guard that gets turned off."""
    blocked = [
        f"{case.id}: {case.text!r}"
        for case in CASES
        if not case.must_block and check(case.text, case.ctx) is not None
    ]
    assert not blocked, "legitimate tutor moves were blocked:\n" + "\n".join(blocked[:20])


def test_guard_raises_rather_than_returning() -> None:
    ctx = LeakageContext(
        live_problem="3x + 8 = 23",
        learner_lines=["3x + 8 = 23"],
        remaining=["3x = 15", "x = 5"],
        final_answer="x = 5",
    )
    assert guard("What are you going to try next?", ctx)
    with pytest.raises(LeakageBlocked):
        guard("So x = 5.", ctx)


@pytest.mark.parametrize(
    "text",
    [
        "x = 5",
        "The answer is five.",
        "x is 5.",
        "$$x = 5$$",
        "```python\nx = 5\n```",
        "5 = x",
        r"x = \frac{15}{3}",
        "x equals five",
        "Divide both sides by 3.",
        "Subtract 8 from both sides.",
        "It comes out to 5.",
        "x = 15/3",
    ],
)
def test_answer_in_every_notation(text: str) -> None:
    """§10: 'in any notation including words, LaTeX, and code'."""
    ctx = LeakageContext(
        live_problem="3x + 8 = 23",
        learner_lines=["3x + 8 = 23"],
        remaining=["3x = 15", "x = 5"],
        final_answer="x = 5",
    )
    assert check(text, ctx) is not None, f"leaked: {text!r}"
