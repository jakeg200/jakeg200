"""Verifier invariants. SPEC.md §7.

The asymmetry is the subsystem: it must be cheap to abstain and expensive to convict. Most of
these tests assert that something is *not* `invalid`, which looks lax and is the opposite — every
one of them is a false accusation that would otherwise reach a learner.
"""

from __future__ import annotations

import pytest

from atrium.verify.base import Step, StepKind, Tier, Verdict, Verification, unverifiable
from atrium.verify.formal import FormalVerifier
from atrium.verify.judge import JudgeReading, JudgeVerifier
from atrium.verify.ladder import Ladder
from atrium.verify.symbolic import ParseFailure, SymbolicVerifier, normalise, to_expr

TIER1 = SymbolicVerifier()


# --- tier 1 (§7) --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("prev", "curr"),
    [
        ("3x + 8 = 23", "3x = 15"),
        ("3x = 15", "x = 5"),
        ("2(x + 3)", "2x + 6"),
        ("5 - 2x = 1", "-2x = -4"),
        (r"\frac{3x}{3} = \frac{15}{3}", "x = 5"),
        ("x^2 - 1", "(x - 1)(x + 1)"),
        ("12 = 3x", "4 = x"),
    ],
)
def test_valid_steps_verify(prev: str, curr: str) -> None:
    assert TIER1.verify(Step(prev=prev, curr=curr)).verdict is Verdict.VALID


@pytest.mark.parametrize(
    ("prev", "curr"),
    [
        ("3x + 8 = 23", "3x = 31"),
        ("2(x + 3)", "2x + 3"),
        ("5 - 2x = 1", "2x = -4"),
        ("3x = 15", "x = 3"),
    ],
)
def test_invalid_steps_are_caught(prev: str, curr: str) -> None:
    result = TIER1.verify(Step(prev=prev, curr=curr))
    assert result.verdict is Verdict.INVALID
    assert result.reason, "an accusation must carry its evidence"


def test_parse_failure_is_unverifiable_never_invalid() -> None:
    """§7, verbatim: 'Parse failure returns unverifiable, never invalid.'"""
    result = TIER1.verify(Step(prev=r"\underbrace{3x}_{\text{stuff}}", curr="x = 5"))
    assert result.verdict is Verdict.UNVERIFIABLE


def test_unknown_command_is_refused_rather_than_guessed() -> None:
    with pytest.raises(ParseFailure):
        normalise(r"\undefinedcommand{x}")


def test_subscripted_log_is_refused() -> None:
    """Reading `log_2(x)` as a symbol times x would convict someone for correct work."""
    with pytest.raises(ParseFailure):
        to_expr("log_2(8)")


def test_first_line_has_no_antecedent() -> None:
    assert TIER1.verify(Step(prev="", curr="3x = 15")).verdict is Verdict.UNVERIFIABLE


def test_new_symbol_is_unverifiable() -> None:
    result = TIER1.verify(Step(prev="3x = 15", curr="3x = 5y"))
    assert result.verdict is Verdict.UNVERIFIABLE


def test_relation_to_expression_is_unverifiable() -> None:
    assert TIER1.verify(Step(prev="3x = 15", curr="5")).verdict is Verdict.UNVERIFIABLE


# --- tier 2 (§7) --------------------------------------------------------------------------------


def test_no_lean_toolchain_degrades_to_unverifiable() -> None:
    result = FormalVerifier().verify(Step(prev="3x = 15", curr="x = 5"))
    assert result.verdict is not Verdict.INVALID


def test_a_timeout_is_unverifiable() -> None:
    """§7 says this twice. The tier must never convict someone for being slow to compile."""
    verifier = FormalVerifier(timeout_s=0.0001)
    result = verifier.verify(Step(prev="3*x", curr="x*3"))
    assert result.verdict is not Verdict.INVALID


# --- tier 3 (§7) --------------------------------------------------------------------------------


class _FakeLLM:
    def __init__(self, reading: JudgeReading) -> None:
        self.reading = reading

    def structured(self, **_: object) -> JudgeReading:
        return self.reading


def _judge(follows: str, confidence: float) -> JudgeVerifier:
    return JudgeVerifier(
        llm=_FakeLLM(JudgeReading(follows=follows, confidence=confidence))  # type: ignore[arg-type]
    )


def test_judge_never_convicts_on_algebra() -> None:
    """§7: 'never for a step whose kind is algebraic'."""
    step = Step(prev="2(x + 3)", curr="2x + 3", kind=StepKind.ALGEBRAIC)
    assert _judge("no", 0.99).verify(step).verdict is Verdict.UNVERIFIABLE


def test_judge_below_threshold_abstains() -> None:
    step = Step(prev="a", curr="b", kind=StepKind.LOGICAL)
    assert _judge("no", 0.80).verify(step).verdict is Verdict.UNVERIFIABLE


def test_judge_above_threshold_may_convict_but_not_tell() -> None:
    step = Step(prev="a", curr="b", kind=StepKind.LOGICAL)
    result = _judge("no", 0.95).verify(step)
    assert result.verdict is Verdict.INVALID
    assert not result.tellable, "§7: the learner is only told on tier 1 or tier 2 evidence"


def test_cannot_tell_abstains() -> None:
    step = Step(prev="a", curr="b", kind=StepKind.LOGICAL)
    assert _judge("cannot_tell", 0.99).verify(step).verdict is Verdict.UNVERIFIABLE


def test_judge_failure_abstains() -> None:
    class Broken:
        def structured(self, **_: object) -> JudgeReading:
            raise RuntimeError("no model")

    result = JudgeVerifier(llm=Broken()).verify(Step(prev="a", curr="b"))  # type: ignore[arg-type]
    assert result.verdict is Verdict.UNVERIFIABLE


# --- the ladder (§7) ----------------------------------------------------------------------------


def test_ladder_stops_at_the_first_decisive_tier() -> None:
    class Exploding:
        tier = Tier.FORMAL

        def verify(self, step: Step) -> Verification:
            raise AssertionError("tier 1 decided; nothing below it should run")

    ladder = Ladder(tiers=[SymbolicVerifier(), Exploding()])  # type: ignore[list-item]
    assert ladder.verify(Step(prev="3x = 15", curr="x = 5")).verdict is Verdict.VALID


def test_ladder_falls_through_on_abstention() -> None:
    class Abstains:
        tier = Tier.SYMBOLIC

        def verify(self, step: Step) -> Verification:
            return unverifiable("nope", self.tier)

    class Decides:
        tier = Tier.FORMAL

        def verify(self, step: Step) -> Verification:
            return Verification(verdict=Verdict.VALID, tier=self.tier)

    ladder = Ladder(tiers=[Abstains(), Decides()])  # type: ignore[list-item]
    assert ladder.verify(Step(prev="a", curr="b")).verdict is Verdict.VALID


def test_first_break_finds_the_earliest_error() -> None:
    """§7/M2: probing line 5 when the mistake happened at line 2 is worse than saying nothing."""
    chain = ["3x + 8 = 23", "3x = 31", "x = 31/3"]
    result = Ladder(tiers=[SymbolicVerifier()]).first_break(chain)
    assert result is not None
    assert result.line_index == 1


def test_steps_after_a_break_are_judged_against_the_learners_own_line() -> None:
    """Once they have written 3x = 31, dividing by 3 is a correct step and must not be flagged."""
    chain = ["3x + 8 = 23", "3x = 31", "x = 31/3"]
    results = Ladder(tiers=[SymbolicVerifier()]).verify_chain(chain)
    assert results[1].verdict is Verdict.VALID


def test_a_correct_chain_has_no_break() -> None:
    chain = ["3x + 8 = 23", "3x = 15", "x = 5"]
    assert Ladder(tiers=[SymbolicVerifier()]).first_break(chain) is None
