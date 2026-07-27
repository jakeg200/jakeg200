"""Finding the first break, and naming it.

Two jobs, in this order.

**Locating.** The first break is the first step the ladder called invalid. Unverifiable
steps never break a chain — the ladder not reaching a step is our limitation, not the
learner's error.

**Naming.** We name the misconception by *modelling the error*: take the line the learner
was working from, apply each mistake a person actually makes, and see which one produces
the line they actually wrote. When one of them reproduces it exactly, we know what
happened rather than guessing at it. Only when none does do we ask a model, and a model's
answer is a low-confidence label, never a verdict.

This module is the one place permitted to see the canonical answer, and its output is
passed through the leakage filter before anybody reads it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import sympy
from pydantic import BaseModel, Field

from warrant import llm
from warrant.pipeline import leakage
from warrant.verify.base import StepView, VerificationResult
from warrant.verify.mathparse import MathForm, is_solved_form, parse, parse_statement


@dataclass
class DiagnosisResult:
    first_break_index: int | None
    error_class: str
    misconception_id: str | None
    confidence: float
    summary: str
    derivation_present: bool = False
    detail: dict[str, str] = field(default_factory=dict)


class ErrorLabel(BaseModel):
    misconception_id: str
    confidence: float = Field(ge=0.0, le=1.0)
    summary: str


LABEL_SYSTEM = """You name the mistake in one step of a person's mathematical working.

You are given the line they were working from and the line they wrote next, which has \
already been *proved* wrong by a symbolic engine. You are not deciding whether it is \
wrong. You are only naming which of the listed misconceptions best describes it.

Describe the mistake in terms of the step itself. Never state or imply what the correct \
answer to the problem is, and never give the corrected line.
"""


# ---------------------------------------------------------------------------
# linear error models
# ---------------------------------------------------------------------------


def _sides(form: MathForm) -> tuple[Any, Any, Any, Any] | None:
    """(aL, bL, aR, bR) for aL*x + bL = aR*x + bR, or None if it is not linear."""
    if form.kind != "equation" or len(form.symbols) != 1:
        return None
    sym = sympy.Symbol(next(iter(form.symbols)))
    try:
        left = sympy.Poly(form.lhs, sym)
        right = sympy.Poly(form.rhs, sym)
    except Exception:
        return None
    if left.degree() > 1 or right.degree() > 1:
        return None
    al = left.coeff_monomial(sym) if left.degree() >= 1 else sympy.Integer(0)
    bl = left.coeff_monomial(1)
    ar = right.coeff_monomial(sym) if right.degree() >= 1 else sympy.Integer(0)
    br = right.coeff_monomial(1)
    return al, bl, ar, br


def _root(form: MathForm) -> Any | None:
    sides = _sides(form)
    if sides is None:
        return None
    al, bl, ar, br = sides
    if al - ar == 0:
        return None
    return sympy.simplify((br - bl) / (al - ar))


def _partial_distributions(expr: Any) -> list[Any]:
    """Ways of expanding k(a + b) that reach only part of the way inside the bracket."""
    out: list[Any] = []
    if not expr.is_Mul:
        return out
    coefficient, rest = expr.as_coeff_Mul()
    if not coefficient.is_number or not rest.is_Add:
        return out
    variable = sum((t for t in rest.args if t.free_symbols), sympy.Integer(0))
    constant = sum((t for t in rest.args if not t.free_symbols), sympy.Integer(0))
    if variable == 0 or constant == 0:
        return out
    out.append(coefficient * variable + constant)
    out.append(variable + coefficient * constant)
    return out


def _distribution_models(prev: MathForm) -> list[tuple[str, Any, str]]:
    if prev.kind != "equation" or len(prev.symbols) != 1:
        return []
    models: list[tuple[str, Any, str]] = []
    lefts = [prev.lhs, *_partial_distributions(prev.lhs)]
    rights = [prev.rhs, *_partial_distributions(prev.rhs)]
    for left in lefts:
        for right in rights:
            if left is prev.lhs and right is prev.rhs:
                continue
            candidate = MathForm(kind="equation", lhs=left, rhs=right, symbols=prev.symbols)
            root = _root(candidate)
            if root is not None:
                models.append(
                    (
                        "distribution_incomplete",
                        root,
                        "the factor outside the bracket reached only part of what is inside it",
                    )
                )
    return models


def _error_models(prev: MathForm) -> list[tuple[str, Any, str]]:
    """Roots a learner would reach after each named mistake, given the previous line.

    Ordered from structurally specific to generic, so that a bracket mistake is named as
    one rather than as whichever sign slip happens to land on the same number.
    """
    sides = _sides(prev)
    if sides is None:
        return []
    al, bl, ar, br = sides
    models: list[tuple[str, Any, str]] = list(_distribution_models(prev))

    def add(mid: str, value: Any, note: str) -> None:
        try:
            simplified = sympy.simplify(value)
        except Exception:
            return
        if simplified.is_number and not simplified.has(sympy.zoo, sympy.nan, sympy.oo):
            models.append((mid, simplified, note))

    # An operation carried out on one side and not the other.
    if al != 0:
        add(
            "operation_applied_to_one_side",
            (br - bl) / al,
            "the unknown was removed from one side only",
        )
        add("operation_applied_to_one_side", br / al, "a constant was cleared from one side only")
    if al - 2 * ar != 0:
        add(
            "operation_applied_to_one_side",
            (br - bl) / (al - 2 * ar),
            "a term in the unknown was taken off one side only",
        )
    if al - ar != 0:
        add(
            "operation_applied_to_one_side",
            br / (al - ar),
            "a constant was cleared from one side only",
        )

    # Dividing through, done wrong.
    if al - ar not in (0, 1):
        add(
            "divide_only_one_term",
            br - bl,
            "the coefficient of the unknown was dropped rather than divided by",
        )
    if al - ar != 0:
        add(
            "inverse_operation_error",
            (br - bl) * (al - ar),
            "the coefficient was multiplied through instead of divided by",
        )
    add(
        "inverse_operation_error",
        br - al,
        "the coefficient was subtracted rather than divided by",
    )

    # A term in the unknown merged with a constant.
    if al + bl != 0:
        add(
            "combine_unlike_terms",
            (br - bl) / (al + bl),
            "a term in the unknown was combined with a constant",
        )

    # Signs. Every way of crossing the equals sign except the correct one.
    for x_sign in (1, -1):
        for c_sign in (1, -1):
            if x_sign == -1 and c_sign == -1:
                continue  # this is the correct move
            denominator = al + x_sign * ar
            if denominator == 0:
                continue
            note = (
                "a constant crossed the equals sign without changing sign"
                if c_sign == 1 and x_sign == -1
                else "a term in the unknown crossed the equals sign without changing sign"
                if x_sign == 1 and c_sign == -1
                else "terms crossed the equals sign without changing sign"
            )
            add("sign_error_across_equals", (br + c_sign * bl) / denominator, note)

    # Speculative readings last. These predict the same number as a plain sign slip often
    # enough that putting them earlier would rename the commonest error in the topic.
    if al + bl != 0:
        add(
            "combine_unlike_terms",
            br / (al + bl),
            "a term in the unknown was combined with a constant",
        )
    if bl != 0:
        add(
            "combine_unlike_terms",
            br / bl,
            "a constant was treated as the coefficient of the unknown",
        )
    return models


def _cancelled_across_sum(prev: MathForm, curr: MathForm) -> bool:
    """Did they strike the unknown out of a sum, as though it cancelled?

    Deleting x from both sides of 7x - 2 = 3x + 10 leaves exactly what you get by
    substituting x = 1, which makes this cheap to detect and hard to fake.
    """
    if curr.kind != "equation" or curr.symbols or prev.kind != "equation":
        return False
    if len(prev.symbols) != 1:
        return False
    sym = sympy.Symbol(next(iter(prev.symbols)))
    try:
        return bool(sympy.simplify(prev.relation().subs(sym, 1) - curr.relation()) == 0)
    except Exception:
        return False


def _is_bare_division(prev: MathForm) -> bool:
    """prev looks like 'a x = b': the next move is a division and nothing else."""
    sides = _sides(prev)
    if sides is None:
        return False
    al, bl, ar, br = sides
    return bool(al != 0 and bl == 0 and ar == 0)


def classify_linear(prev: MathForm, curr: MathForm) -> tuple[str, float, str] | None:
    """Which named mistake turns `prev` into `curr`?"""
    if _cancelled_across_sum(prev, curr):
        return (
            "cancel_across_sum",
            0.85,
            "the unknown was struck out of a sum on both sides as though it cancelled",
        )

    curr_root = _root(curr)
    if curr_root is None:
        return None
    for misconception_id, predicted, note in _error_models(prev):
        if sympy.simplify(predicted - curr_root) == 0:
            return misconception_id, 0.9, note

    # The structure survived — same coefficient on the unknown — but the number did not.
    prev_sides, curr_sides = _sides(prev), _sides(curr)
    if prev_sides and curr_sides:
        al, _, ar, _ = prev_sides
        ac, _, arc, _ = curr_sides
        if (al - ar) == (ac - arc) and (al - ar) != 0:
            return "arithmetic_slip", 0.7, "the method is right but a number is not"

    # Nothing named fits, but the step was the single division that finishes the problem
    # and the shape of it is right. That is a slip, not a misconception.
    if _is_bare_division(prev) and is_solved_form(curr):
        return (
            "arithmetic_slip",
            0.65,
            "the division was the right move but came out to the wrong number",
        )
    return None


# ---------------------------------------------------------------------------
# blame attribution
# ---------------------------------------------------------------------------


def _numbers(form: MathForm) -> set[Any]:
    if not form.ok:
        return set()
    target = form.rhs if form.kind == "equation" else form.expr
    if target is None:
        return set()
    return {n for n in target.atoms(sympy.Number)}


def attribute_break(
    break_index: int,
    steps: list[StepView],
    results: list[VerificationResult],
) -> int:
    """Move the blame back onto the line that actually produced the wrong quantity.

    A learner who writes "-2 add 10 is 8, so 4x = 8" has made their mistake on the first
    of those lines; the equation merely inherits it. Both lines are true in isolation, so
    only the second is provably wrong, and reporting that one would point at the symptom.

    This can only ever move an existing break earlier. It cannot create one, so it cannot
    affect the false-accusation rate.
    """
    broken = parse(steps[break_index].raw_text)
    wrong_values = _numbers(broken)
    if not wrong_values:
        return break_index

    candidate = break_index
    for index in range(break_index - 1, -1, -1):
        result = results[index]
        reading = result.detail.get("reading", "")
        # Only step over lines that were true but derived nothing: stated arithmetic and
        # lemmas. A genuine chain move in between means the break belongs where it is.
        if not (
            result.status == "unverifiable"
            or (result.status == "valid" and reading in ("closed_identity", "lemma"))
        ):
            break
        form = parse(steps[index].raw_text)
        concluded = _numbers(form)
        if concluded & wrong_values:
            candidate = index
        elif result.status == "valid":
            # A true line that has nothing to do with the wrong quantity is not the cause.
            continue
    return candidate


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------


def _last_deriving_form(
    steps: list[StepView], results: list[VerificationResult], upto: int, statement: str
) -> MathForm:
    for index in range(upto - 1, -1, -1):
        if results[index].detail.get("derives") == "yes":
            form = parse(steps[index].raw_text)
            if form.ok:
                return form
    return parse_statement(statement)


def has_derivation(results: list[VerificationResult]) -> bool:
    """True when at least one step actually moved the problem along.

    Stating an answer and substituting it back is a legitimate *check*, and it verifies,
    but it derives nothing. Telling those two things apart is the whole point.
    """
    return any(r.status == "valid" and r.detail.get("derives") == "yes" for r in results)


def diagnose(
    steps: list[StepView],
    results: list[VerificationResult],
    statement: str,
    canonical_answer: str = "",
) -> DiagnosisResult:
    derivation = has_derivation(results)

    first_break: int | None = next(
        (i for i, r in enumerate(results) if r.status == "invalid"), None
    )

    if first_break is None:
        if not derivation and steps:
            return DiagnosisResult(
                first_break_index=None,
                error_class="no_derivation",
                misconception_id="no_derivation",
                confidence=0.9,
                summary=(
                    "Nothing here is wrong. But every line either states a value or "
                    "checks one — no line derives anything, so this does not yet show "
                    "how the result was reached."
                ),
                derivation_present=False,
            )
        unsettled = sum(1 for r in results if r.status == "unverifiable")
        summary = "Every step that could be checked follows from the one before it."
        if unsettled:
            summary += f" {unsettled} step(s) could not be checked and were left alone."
        return DiagnosisResult(
            first_break_index=None,
            error_class="none",
            misconception_id="none",
            confidence=1.0,
            summary=summary,
            derivation_present=derivation,
        )

    attributed = attribute_break(first_break, steps, results)
    prev_form = _last_deriving_form(steps, results, attributed, statement)
    curr_form = parse(steps[first_break].raw_text)

    detail = {"proved_at_index": str(first_break), "attributed_to_index": str(attributed)}

    label = classify_linear(prev_form, curr_form)
    if label is not None:
        misconception_id, confidence, note = label
        summary = f"Step {attributed + 1} does not follow: {note}."
        return DiagnosisResult(
            first_break_index=attributed,
            error_class=misconception_id,
            misconception_id=misconception_id,
            confidence=confidence,
            summary=leakage.redact(summary, canonical_answer),
            derivation_present=derivation,
            detail=detail,
        )

    lost = _lost_solution(results[first_break])
    if lost is not None:
        return DiagnosisResult(
            first_break_index=attributed,
            error_class="lost_solution",
            misconception_id="lost_solution",
            confidence=0.8,
            summary=leakage.redact(
                f"Step {attributed + 1} changes which values satisfy the equation.",
                canonical_answer,
            ),
            derivation_present=derivation,
            detail=detail,
        )

    guess = _ask_model(steps, first_break, statement)
    if guess is not None:
        return DiagnosisResult(
            first_break_index=attributed,
            error_class=guess.misconception_id,
            misconception_id=guess.misconception_id,
            confidence=min(guess.confidence, 0.6),
            summary=leakage.redact(guess.summary, canonical_answer),
            derivation_present=derivation,
            detail=detail,
        )

    return DiagnosisResult(
        first_break_index=attributed,
        error_class="unjustified_leap",
        misconception_id="unjustified_leap",
        confidence=0.5,
        summary=leakage.redact(
            f"Step {attributed + 1} does not follow from the line before it.",
            canonical_answer,
        ),
        derivation_present=derivation,
        detail=detail,
    )


def _lost_solution(result: VerificationResult) -> str | None:
    before = result.detail.get("solutions_before")
    after = result.detail.get("solutions_after")
    if not before or not after:
        return None
    before_values = set(re.findall(r"-?\d+(?:/\d+)?", before))
    after_values = set(re.findall(r"-?\d+(?:/\d+)?", after))
    if before_values and before_values > after_values:
        return "solutions were lost"
    return None


def _ask_model(steps: list[StepView], index: int, statement: str) -> ErrorLabel | None:
    from warrant.taxonomy import MISCONCEPTIONS

    catalogue = "\n".join(
        f"- {m.id}: {m.description}" for m in MISCONCEPTIONS.values() if m.id != "none"
    )
    previous = steps[index - 1].raw_text if index > 0 else "(the task statement)"
    return llm.complete(
        purpose="diagnose",
        system=LABEL_SYSTEM,
        prompt=(
            f"Task: {statement}\n\nPrevious line: {previous}\n"
            f"The wrong line: {steps[index].raw_text}\n\n"
            f"Misconceptions:\n{catalogue}"
        ),
        schema=ErrorLabel,
    )
