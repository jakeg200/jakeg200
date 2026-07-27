"""Turning a step into something a machine can check.

Formalisation is what buys tier coverage. Every step that formalises cleanly is a step
the deterministic tiers can settle, and every step that does not is a step the model
judge has to guess at. When tier 3 starts settling most of the maths, this file is the
thing to improve — not the judge's prompt.
"""

from __future__ import annotations

from dataclasses import dataclass

import sympy
from pydantic import BaseModel, Field

from warrant import llm
from warrant.config import settings
from warrant.verify.base import StepKind
from warrant.verify.mathparse import MathForm, parse


@dataclass(frozen=True)
class Formalisation:
    formalised: str | None
    confidence: float | None
    form: MathForm | None = None


class LeanTerm(BaseModel):
    lean: str
    confidence: float = Field(ge=0.0, le=1.0)


LEAN_SYSTEM = """You translate one line of a person's mathematical working into a single \
Lean 4 proposition using mathlib names. Real variables are already bound as (x : ℝ).

Return only the proposition, no proof, no theorem header. If the line is not a \
proposition — if it is an instruction like "divide both sides by 4", or commentary — \
return an empty string and confidence 0.
"""


def formalise(raw_text: str, kind: StepKind, prior: str | None = None) -> Formalisation:
    """Formalise one step. Returns nothing rather than something doubtful."""
    form = parse(raw_text)

    if form.ok:
        # SymPy's srepr is exact and round-trippable, which is what tier 1 consumes.
        expression = sympy.Eq(form.lhs, form.rhs) if form.kind == "equation" else form.expr
        confidence = 0.95 if form.kind == "equation" else 0.8
        return Formalisation(formalised=sympy.srepr(expression), confidence=confidence, form=form)

    if kind == "inference" and settings.lean_enabled:
        result = llm.complete(
            purpose="formalise",
            system=LEAN_SYSTEM,
            prompt=f"Previous line: {prior or '(none)'}\nLine: {raw_text}",
            schema=LeanTerm,
        )
        if result is not None and result.lean.strip() and result.confidence > 0.6:
            return Formalisation(formalised=result.lean.strip(), confidence=result.confidence)

    return Formalisation(formalised=None, confidence=None, form=None)
