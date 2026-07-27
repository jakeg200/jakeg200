"""Tier 3 — the model judge. Uncertain by construction.

This tier exists to notice things the deterministic tiers cannot express, and it is
built so that its uncertainty survives contact with the rest of the system. Three
constraints, all enforced in code rather than trusted to the prompt:

* it may not call an algebraic step invalid — that is Tier 1's job, and if Tier 1 could
  not parse the step then the honest answer is that we do not know;
* "no" below the confidence floor becomes "unverifiable";
* if the model is unreachable, the answer is "unverifiable" — never a guess.
"""

from __future__ import annotations

import time
from typing import Literal

from pydantic import BaseModel, Field

from warrant import llm
from warrant.config import settings
from warrant.verify.base import (
    StepView,
    TaskContext,
    VerificationResult,
    unverifiable,
)

SYSTEM = """You are the last tier of a verification ladder that judges whether one step \
of a person's mathematical working follows from the step before it.

You are not a marker and not a tutor. You are answering one narrow question: given the \
previous line, is the next line a legitimate move?

Rules you must follow:
- Answer "cannot_tell" whenever the step could be valid under any reasonable reading. \
Ambiguous notation, an unusual but sound method, a step that skips routine arithmetic, \
an unstated but obvious justification: all of these are "cannot_tell", not "no".
- Answer "no" only when you can state the specific thing that is wrong, and when no \
competent reader would accept the move.
- Never consider whether the step leads towards a particular answer. A person may take \
an unexpected route and still be right at every step.
- Your confidence is the probability that a careful mathematician would agree with you.
"""

PROMPT = """Task: {statement}

Previous line: {prev}
Next line: {curr}

Does the next line follow from the previous line?"""


class Judgement(BaseModel):
    follows: Literal["yes", "no", "cannot_tell"]
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str


class ModelJudge:
    tier: Literal[1, 2, 3] = 3
    name = "model-judge"

    def verify(self, prev: StepView | None, curr: StepView, ctx: TaskContext) -> VerificationResult:
        started = time.perf_counter()

        def elapsed() -> int:
            return int((time.perf_counter() - started) * 1000)

        judgement = llm.complete(
            purpose="judge",
            system=SYSTEM,
            prompt=PROMPT.format(
                statement=ctx.statement,
                prev=prev.raw_text if prev is not None else "(the task statement itself)",
                curr=curr.raw_text,
            ),
            schema=Judgement,
        )

        if judgement is None:
            return unverifiable(3, "no model judgement available", elapsed())

        floor = settings.judge_min_confidence

        if judgement.follows == "cannot_tell":
            return unverifiable(3, judgement.reason, elapsed())

        if judgement.follows == "no":
            # Algebra belongs to Tier 1. A model is not permitted to accuse somebody of
            # an algebraic error that a symbolic engine could not confirm.
            if curr.kind == "algebraic":
                return unverifiable(
                    3, "algebraic step could not be settled symbolically", elapsed()
                )
            if judgement.confidence < floor:
                return unverifiable(3, judgement.reason, elapsed())
            return VerificationResult(
                tier=3,
                status="invalid",
                evidence=judgement.reason,
                confidence=judgement.confidence,
                latency_ms=elapsed(),
                detail={"reading": "model_judge"},
            )

        if judgement.confidence < floor:
            return unverifiable(3, judgement.reason, elapsed())
        return VerificationResult(
            tier=3,
            status="valid",
            evidence=judgement.reason,
            confidence=judgement.confidence,
            latency_ms=elapsed(),
            detail={"reading": "model_judge", "derives": "unknown"},
        )
