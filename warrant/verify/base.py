"""Verifier interface.

Every verifier answers one question: does this step follow from the previous one?
It may answer "valid", "invalid", or "unverifiable". The third answer is not a
failure mode — it is the honest answer whenever the verifier's method does not
reach, and the pipeline is built so that it costs the learner nothing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol, runtime_checkable

Status = Literal["valid", "invalid", "unverifiable"]
StepKind = Literal["algebraic", "inference", "definition", "assertion", "restatement"]


@dataclass(frozen=True)
class StepView:
    """The slice of a Step a verifier is allowed to see."""

    index: int
    raw_text: str
    kind: StepKind
    formalised: str | None = None
    formaliser_confidence: float | None = None


@dataclass(frozen=True)
class TaskContext:
    """What a verifier knows about the task.

    Deliberately does not carry the canonical answer. No verifier is permitted to
    check a learner's step against the answer; that would collapse assessment of a
    derivation back into assessment of an artefact.
    """

    statement: str
    domain: str = "maths"
    notation: str = "text"
    var_domain: Literal["reals", "complexes", "integers"] = "reals"


@dataclass(frozen=True)
class VerificationResult:
    tier: Literal[1, 2, 3]
    status: Status
    evidence: str = ""
    confidence: float | None = None
    latency_ms: int = 0
    detail: dict[str, str] = field(default_factory=dict)

    @property
    def conclusive(self) -> bool:
        return self.status in ("valid", "invalid")


@runtime_checkable
class VerifierProtocol(Protocol):
    tier: Literal[1, 2, 3]
    name: str

    def verify(
        self,
        prev: StepView | None,
        curr: StepView,
        ctx: TaskContext,
    ) -> VerificationResult:
        """Judge whether `curr` follows from `prev` (or from the task, when prev is None)."""
        ...


def unverifiable(tier: Literal[1, 2, 3], reason: str, latency_ms: int = 0) -> VerificationResult:
    return VerificationResult(
        tier=tier, status="unverifiable", evidence=reason, latency_ms=latency_ms
    )
