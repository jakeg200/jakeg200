"""The ladder: deterministic tiers first, the model last, first conclusive answer wins.

The ladder also enforces the ordering's safety property independently of the tiers
themselves. Tier 3 is not trusted to police itself: if a tier above 2 returns "invalid"
for an algebraic step, the ladder downgrades it. Defence in depth, because this is the
rule whose violation would make the product dishonest.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from warrant.verify.base import (
    StepView,
    TaskContext,
    VerificationResult,
    VerifierProtocol,
    unverifiable,
)
from warrant.verify.formal import LeanVerifier
from warrant.verify.judge import ModelJudge
from warrant.verify.symbolic import SymbolicVerifier


@dataclass
class LadderOutcome:
    result: VerificationResult
    attempted: list[VerificationResult]


class VerifierLadder:
    def __init__(self, verifiers: list[VerifierProtocol] | None = None) -> None:
        self.verifiers: list[VerifierProtocol] = verifiers or [
            SymbolicVerifier(),
            LeanVerifier(),
            ModelJudge(),
        ]

    def verify(self, prev: StepView | None, curr: StepView, ctx: TaskContext) -> LadderOutcome:
        attempted: list[VerificationResult] = []
        for verifier in self.verifiers:
            result = verifier.verify(prev, curr, ctx)
            result = self._guard(result, curr)
            attempted.append(result)
            if result.conclusive:
                return LadderOutcome(result=result, attempted=attempted)

        last = attempted[-1] if attempted else unverifiable(3, "no verifier ran")
        return LadderOutcome(
            result=unverifiable(last.tier, self._why(attempted)), attempted=attempted
        )

    @staticmethod
    def _guard(result: VerificationResult, curr: StepView) -> VerificationResult:
        if result.status == "invalid" and result.tier == 3 and curr.kind == "algebraic":
            return unverifiable(
                3,
                "an algebraic step was not settled symbolically, so we do not know",
                result.latency_ms,
            )
        return result

    @staticmethod
    def _why(attempted: list[VerificationResult]) -> str:
        if not attempted:
            return "no verifier ran"
        return attempted[0].evidence or "no tier could settle this step"


def tier_coverage(results: list[VerificationResult]) -> dict[str, float | int]:
    """How much of the work the deterministic tiers are actually doing.

    If tier 3 is settling most of the maths, the formaliser is what needs fixing.
    """
    counts = Counter(r.tier for r in results if r.status in ("valid", "invalid"))
    total = len(results)
    settled = sum(counts.values())
    deterministic = counts[1] + counts[2]
    return {
        "steps": total,
        "settled": settled,
        "tier1": counts[1],
        "tier2": counts[2],
        "tier3": counts[3],
        "deterministic_share": (deterministic / total) if total else 0.0,
        "abstention_rate": ((total - settled) / total) if total else 0.0,
    }
