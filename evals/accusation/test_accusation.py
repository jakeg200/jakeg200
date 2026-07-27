"""Blocking eval: we never claim a break in a correct chain. SPEC.md §10, M2 acceptance."""

from __future__ import annotations

import pytest

from atrium.verify.base import Step, Verdict
from atrium.verify.ladder import Ladder
from atrium.verify.symbolic import SymbolicVerifier
from evals.accusation.corpus import build

FAIL_ABOVE = 0.02  # §10: target < 1%, fail the build above 2%

#: Tier 1 only. M2 is "it knows when you are wrong" with no tutor and no model judge, and the
#: safety claim has to hold on the deterministic tier alone — if it only holds once a model is in
#: the loop, it is not a claim about the verifier.
LADDER = Ladder(tiers=[SymbolicVerifier()])


def _accusations() -> tuple[int, int, list[str]]:
    total = 0
    wrong: list[str] = []
    for name, chain in build():
        for result in LADDER.verify_chain(chain):
            total += 1
            if result.tellable:
                wrong.append(f"{name} line {result.line_index}: {result.reason}")
    return total, len(wrong), wrong


def test_corpus_is_large_enough() -> None:
    assert len(build()) >= 60, "§10 asks for 60+ correct derivations"


def test_no_false_accusations() -> None:
    total, count, detail = _accusations()
    rate = count / total if total else 0.0
    assert rate <= FAIL_ABOVE, (
        f"false accusation rate {rate:.2%} over the {FAIL_ABOVE:.0%} build gate:\n"
        + "\n".join(detail[:20])
    )
    assert count == 0, "target is zero; investigate before relaxing:\n" + "\n".join(detail[:20])


@pytest.mark.parametrize(
    ("prev", "curr"),
    [
        ("3x + 8 = 23", "3x = 31"),  # sign error crossing the equals
        ("5 - 2x = 1", "2x = -4"),  # sign dropped
        ("2(x + 3)", "2x + 3"),  # failed distribution
        ("4x - 4 = 2x + 6", "2x = 2"),  # arithmetic slip
        ("3x = 15", "x = 3"),  # divided the wrong way
    ],
)
def test_real_errors_are_still_caught(prev: str, curr: str) -> None:
    """The safety property is only worth anything if the verifier still convicts when it should.

    A checker that returns `unverifiable` for everything passes the blocking eval above and is
    useless, so recall gets a test too — just not a build gate, because a missed error costs a
    probe and a false accusation costs the learner's trust.
    """
    result = LADDER.verify(Step(prev=prev, curr=curr))
    assert result.verdict is Verdict.INVALID
    assert result.tellable
