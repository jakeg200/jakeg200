"""Verification types shared by every tier.

The asymmetry in this module is the whole point of the subsystem: it is cheap to say
`unverifiable` and expensive to say `invalid`. A tier that cannot decide must return
`unverifiable`. A tier that crashes, times out, or fails to parse must return `unverifiable`.
Only a tier holding positive evidence of a break may return `invalid`.

SPEC.md §7.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class Verdict(str, Enum):
    VALID = "valid"
    INVALID = "invalid"
    UNVERIFIABLE = "unverifiable"


class Tier(str, Enum):
    SYMBOLIC = "symbolic"  # tier 1, SymPy
    FORMAL = "formal"  # tier 2, Lean 4 + mathlib
    JUDGE = "judge"  # tier 3, model


class StepKind(str, Enum):
    """What sort of move the learner made between two lines.

    `ALGEBRAIC` is called out because tier 3 may never convict on it (SPEC.md §7): a model
    judge is bad at algebra in exactly the confident way that produces false accusations, and
    algebra is precisely what tier 1 is good at. If tier 1 abstained on an algebraic step, the
    honest answer is that nobody knows, not that the model has a hunch.
    """

    ALGEBRAIC = "algebraic"
    EQUATION_SOLVE = "equation_solve"
    SUBSTITUTION = "substitution"
    DEFINITION = "definition"
    LOGICAL = "logical"
    UNKNOWN = "unknown"


class Step(BaseModel):
    """One transition in a derivation: `prev` became `curr`."""

    prev: str
    curr: str
    kind: StepKind = StepKind.UNKNOWN
    line_index: int = 0

    def is_first_line(self) -> bool:
        return not self.prev.strip()


class Verification(BaseModel):
    verdict: Verdict
    tier: Tier | None = None
    reason: str = ""
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    line_index: int = 0

    @property
    def tellable(self) -> bool:
        """May we tell the learner they are wrong on this?

        Only on tier 1 or tier 2 evidence. SPEC.md §7. A tier 3 `invalid` still routes to a
        tutoring move ("talk me through it"), but never to an accusation.
        """
        return self.verdict is Verdict.INVALID and self.tier in (Tier.SYMBOLIC, Tier.FORMAL)


def unverifiable(reason: str, tier: Tier | None = None, line_index: int = 0) -> Verification:
    """The safe answer. Every failure path in every tier funnels through here."""
    return Verification(
        verdict=Verdict.UNVERIFIABLE, tier=tier, reason=reason, line_index=line_index
    )


class Verifier:
    """One tier. Implementations live in symbolic.py, formal.py, judge.py."""

    tier: Tier

    def verify(self, step: Step) -> Verification:  # pragma: no cover - interface
        raise NotImplementedError
