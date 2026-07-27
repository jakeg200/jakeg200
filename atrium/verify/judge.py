"""Tier 3 — the model judge. May abstain. May never convict where it is unreliable.

Two hard gates on this tier, from SPEC.md §7:

* `invalid` only above 0.85 confidence,
* **never** `invalid` for a step whose kind is `algebraic`.

The second gate is the important one and it is not a hedge. Algebra is where a language model is
most confidently wrong and where tier 1 is nearly infallible; if tier 1 abstained on an algebraic
step, that means the step was unparseable, and a model looking at unparseable text is guessing.

Even when this tier does return `invalid`, `Verification.tellable` is False for it — the learner is
never told they are wrong on tier 3 evidence. The policy turns it into *"I can't follow how you got
from here to here — talk me through it"*, which is a better tutoring move than an accusation and
happens to be true.
"""

from __future__ import annotations

from typing import Final, Literal

from pydantic import BaseModel, Field

from ..llm import LLM
from .base import Step, StepKind, Tier, Verdict, Verification, Verifier, unverifiable

CONVICTION_THRESHOLD: Final = 0.85

_SYSTEM: Final = """You are checking one step of a learner's mathematical working.

You are given the previous line and the current line. Decide whether the current line follows from
the previous one.

Answer `cannot_tell` freely. It is the right answer whenever the notation is ambiguous, the
handwriting recognition looks garbled, the learner may be working in a convention you do not
recognise, or the step is unusual but possibly correct. Unusual is not wrong. Non-standard notation
is not wrong. A step that skips intermediate work is not wrong.

Answer `no` only when you can point to the specific thing that breaks. If you cannot name it, the
answer is `cannot_tell`.

Never suggest what the learner should write next. You are not tutoring here, you are reading."""


class JudgeReading(BaseModel):
    follows: Literal["yes", "no", "cannot_tell"]
    confidence: float = Field(ge=0.0, le=1.0)
    what_breaks: str = ""


class JudgeVerifier(Verifier):
    tier = Tier.JUDGE

    def __init__(self, llm: LLM | None = None) -> None:
        self.llm = llm or LLM()

    def verify(self, step: Step) -> Verification:
        if step.is_first_line():
            return unverifiable("no antecedent line", self.tier, step.line_index)

        prompt = f"Previous line: {step.prev}\nCurrent line:  {step.curr}"
        try:
            reading = self.llm.structured(
                system=_SYSTEM, prompt=prompt, schema=JudgeReading, max_tokens=400
            )
        except Exception as exc:  # noqa: BLE001 - a judge that errors abstains
            return unverifiable(f"judge unavailable: {exc}", self.tier, step.line_index)

        if reading.follows == "yes":
            return Verification(
                verdict=Verdict.VALID,
                tier=self.tier,
                reason=reading.what_breaks or "judge: follows",
                confidence=reading.confidence,
                line_index=step.line_index,
            )

        if reading.follows == "no":
            if step.kind is StepKind.ALGEBRAIC:
                return unverifiable(
                    "judge dissented on an algebraic step; tier 3 may not convict there",
                    self.tier,
                    step.line_index,
                )
            if reading.confidence <= CONVICTION_THRESHOLD:
                return unverifiable(
                    f"judge below conviction threshold ({reading.confidence:.2f})",
                    self.tier,
                    step.line_index,
                )
            return Verification(
                verdict=Verdict.INVALID,
                tier=self.tier,
                reason=reading.what_breaks or "judge could not follow the step",
                confidence=reading.confidence,
                line_index=step.line_index,
            )

        return unverifiable("judge could not tell", self.tier, step.line_index)
