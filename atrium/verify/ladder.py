"""The ladder: deterministic tiers first, model tier last, and first-break localisation.

Order is tier 1 → tier 2 → tier 3, stopping at the first tier that reaches a verdict. A tier that
returns `unverifiable` hands down; a tier that decides is believed.

`first_break` is the other half of M2. Given a whole derivation, find the *earliest* line that
breaks — because that is where the learner's understanding actually went, and probing line 5 when
the mistake happened at line 2 is worse than saying nothing. Everything after a break is evaluated
relative to the learner's own (wrong) line, not relative to the correct chain: once they have
written 3x = 31, dividing by 3 to get x = 31/3 is a *correct* step and must not be flagged. Only
the first break is theirs to fix.
"""

from __future__ import annotations

from .base import Step, Tier, Verdict, Verification, Verifier
from .formal import FormalVerifier
from .judge import JudgeVerifier
from .symbolic import SymbolicVerifier, infer_kind


class Ladder:
    def __init__(self, tiers: list[Verifier] | None = None) -> None:
        self.tiers: list[Verifier] = tiers if tiers is not None else [
            SymbolicVerifier(),
            FormalVerifier(),
            JudgeVerifier(),
        ]

    def verify(self, step: Step) -> Verification:
        if step.kind.name == "UNKNOWN":
            step = step.model_copy(update={"kind": infer_kind(step)})

        last: Verification | None = None
        for tier in self.tiers:
            result = tier.verify(step)
            last = result
            if result.verdict is not Verdict.UNVERIFIABLE:
                return result
        assert last is not None
        return last

    def verify_chain(self, lines: list[str]) -> list[Verification]:
        """Verify each transition. Index i is the step from `lines[i-1]` to `lines[i]`."""
        out: list[Verification] = []
        for i in range(1, len(lines)):
            out.append(self.verify(Step(prev=lines[i - 1], curr=lines[i], line_index=i)))
        return out

    def first_break(self, lines: list[str]) -> Verification | None:
        """The earliest line where the chain provably breaks, or None.

        Returns only breaks we may actually surface — `Verification.tellable`, i.e. tier 1 or
        tier 2 evidence. A tier 3 dissent is reachable through `verify_chain` and routes to a
        different move; it is deliberately not a "break".
        """
        for result in self.verify_chain(lines):
            if result.tellable:
                return result
        return None


_DEFAULT = Ladder()


def verify(step: Step) -> Verification:
    return _DEFAULT.verify(step)


def first_break(lines: list[str]) -> Verification | None:
    return _DEFAULT.first_break(lines)


__all__ = ["Ladder", "Step", "Tier", "Verdict", "Verification", "first_break", "verify"]
