"""The ladder's ordering, and the guarantees that do not depend on any single tier."""

from __future__ import annotations

from typing import Literal

from warrant.verify.base import (
    StepView,
    TaskContext,
    VerificationResult,
    VerifierProtocol,
)
from warrant.verify.formal import LeanVerifier
from warrant.verify.judge import Judgement, ModelJudge
from warrant.verify.ladder import VerifierLadder, tier_coverage

TASK = TaskContext(statement="Solve 7x - 2 = 3x + 10")


class Fixed:
    """A verifier that always says the same thing, for testing the ordering."""

    def __init__(self, tier: Literal[1, 2, 3], status: str, name: str = "fixed") -> None:
        self.tier = tier
        self.name = name
        self._status = status

    def verify(self, prev: StepView | None, curr: StepView, ctx: TaskContext) -> VerificationResult:
        return VerificationResult(tier=self.tier, status=self._status)  # type: ignore[arg-type]


def test_first_conclusive_answer_wins() -> None:
    ladder = VerifierLadder([Fixed(1, "valid"), Fixed(2, "invalid")])
    outcome = ladder.verify(None, StepView(0, "4x = 12", "algebraic"), TASK)
    assert outcome.result.tier == 1
    assert outcome.result.status == "valid"
    assert len(outcome.attempted) == 1


def test_unverifiable_falls_through() -> None:
    ladder = VerifierLadder([Fixed(1, "unverifiable"), Fixed(2, "unverifiable"), Fixed(3, "valid")])
    outcome = ladder.verify(None, StepView(0, "anything", "inference"), TASK)
    assert outcome.result.tier == 3
    assert len(outcome.attempted) == 3


def test_tier_three_may_not_call_algebra_wrong() -> None:
    """The rule that keeps the product honest, enforced above the tier that could break it."""
    ladder = VerifierLadder([Fixed(3, "invalid", "rogue-judge")])
    outcome = ladder.verify(None, StepView(0, "4x = 12", "algebraic"), TASK)
    assert outcome.result.status == "unverifiable"


def test_tier_three_may_still_call_an_inference_wrong() -> None:
    ladder = VerifierLadder([Fixed(3, "invalid")])
    outcome = ladder.verify(None, StepView(0, "so it must be positive", "inference"), TASK)
    assert outcome.result.status == "invalid"


def test_judge_maps_low_confidence_no_to_unverifiable(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        "warrant.verify.judge.llm.complete",
        lambda **_: Judgement(follows="no", confidence=0.6, reason="not sure"),
    )
    result = ModelJudge().verify(None, StepView(0, "therefore it holds", "inference"), TASK)
    assert result.status == "unverifiable"


def test_judge_cannot_tell_is_unverifiable(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        "warrant.verify.judge.llm.complete",
        lambda **_: Judgement(follows="cannot_tell", confidence=0.99, reason="ambiguous"),
    )
    result = ModelJudge().verify(None, StepView(0, "therefore it holds", "inference"), TASK)
    assert result.status == "unverifiable"


def test_judge_without_a_model_abstains() -> None:
    result = ModelJudge().verify(None, StepView(0, "therefore it holds", "inference"), TASK)
    assert result.status == "unverifiable"


def test_lean_tier_disabled_abstains() -> None:
    result = LeanVerifier().verify(None, StepView(0, "x = 3", "inference"), TASK)
    assert result.status == "unverifiable"
    assert result.tier == 2


def test_lean_timeout_is_unverifiable(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """The single most important correctness property in the system."""
    monkeypatch.setattr("warrant.verify.formal.lean_available", lambda: True)
    monkeypatch.setattr(LeanVerifier, "_run", lambda self, source: None)
    step = StepView(0, "x = 3", "inference", formalised="x = 3")
    result = LeanVerifier().verify(None, step, TASK)
    assert result.status == "unverifiable"


def test_lean_failure_to_prove_is_not_a_disproof(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr("warrant.verify.formal.lean_available", lambda: True)
    monkeypatch.setattr(LeanVerifier, "_run", lambda self, source: False)
    step = StepView(0, "x = 3", "inference", formalised="x = 3")
    assert LeanVerifier().verify(None, step, TASK).status == "unverifiable"


def test_coverage_counts_deterministic_tiers() -> None:
    results = [
        VerificationResult(tier=1, status="valid"),
        VerificationResult(tier=1, status="invalid"),
        VerificationResult(tier=3, status="valid"),
        VerificationResult(tier=3, status="unverifiable"),
    ]
    coverage = tier_coverage(results)
    assert coverage["deterministic_share"] == 0.5
    assert coverage["abstention_rate"] == 0.25


def test_verifiers_satisfy_the_protocol() -> None:
    for verifier in VerifierLadder().verifiers:
        assert isinstance(verifier, VerifierProtocol)
