"""Tier 1 — symbolic verification with SymPy. Certain when it answers.

The tier answers "invalid" only when it holds a disproof: two solution sets that
differ, with a witness value, or a closed arithmetic statement that is false. Anything
short of that falls through as "unverifiable" so a later tier — or a human — can take it.

The important design idea here is the *charitable reading*. A learner writing
"7x - 3x = 4x" is stating a lemma, not transforming the equation; read as a
transformation its solution set is every real, which does not match the equation above
it. Reading it uncharitably would produce a confident accusation against somebody who
is entirely correct. So each step is tested against every reading a competent reader
would allow, and is only invalid when all of them fail.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from typing import Any, Literal

import sympy
from sympy import S

from warrant.config import settings
from warrant.verify.base import (
    StepView,
    TaskContext,
    VerificationResult,
    unverifiable,
)
from warrant.verify.mathparse import MathForm, parse, parse_statement

_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="sympy")

# Values used to hunt for a counterexample when solveset cannot decide. Chosen to avoid
# the poles and fixed points that make sampling accidentally agree.
_SAMPLES = [sympy.Rational(n, 4) for n in (-37, -13, -5, -1, 3, 7, 11, 29, 53, 101)]

_DOMAINS = {"reals": S.Reals, "complexes": S.Complexes, "integers": S.Integers}


def _run(fn: Any, *args: Any) -> Any:
    """Run a SymPy call under a wall-clock budget.

    A computation that overruns is not a wrong answer, it is no answer: the caller
    turns this into "unverifiable".
    """
    future = _POOL.submit(fn, *args)
    try:
        return future.result(timeout=settings.symbolic_timeout_s)
    except FuturesTimeout:
        future.cancel()
        raise TimeoutError("symbolic timeout") from None


def _solution_set(form: MathForm, sym: Any, domain: Any) -> Any:
    return _run(lambda: sympy.solveset(form.relation(), sym, domain=domain))


def _is_identity(form: MathForm, sym: Any, domain: Any) -> bool:
    """True when the equation holds for every value in the domain."""
    try:
        if _run(lambda: sympy.simplify(form.relation())) == 0:
            return True
        return bool(_solution_set(form, sym, domain) == domain)
    except Exception:
        return False


def _closed_truth(form: MathForm) -> bool | None:
    """For an equation with no free symbols: True, False, or None if undecidable."""
    try:
        diff = _run(lambda: sympy.simplify(form.lhs - form.rhs))
    except Exception:
        return None
    if diff == 0:
        return True
    if getattr(diff, "is_number", False):
        try:
            return bool(_run(lambda: sympy.N(diff)) == 0)
        except Exception:
            return None
    return None


def _sets_equal(s_prev: Any, s_curr: Any) -> bool:
    """Solution-set equality that survives differences of notation.

    Structural equality is not enough: {5.5} and {11/2} are the same set written two
    ways, and treating them as different would accuse a correct learner.
    """
    if s_prev == s_curr:
        return True
    if isinstance(s_prev, sympy.FiniteSet) and isinstance(s_curr, sympy.FiniteSet):
        if len(s_prev.args) != len(s_curr.args):
            return False
        remaining = list(s_curr.args)
        for value in s_prev.args:
            match = next(
                (
                    other
                    for other in remaining
                    if _run(lambda v=value, o=other: sympy.simplify(v - o)) == 0
                ),
                None,
            )
            if match is None:
                return False
            remaining.remove(match)
        return True
    return False


def _witness(prev: MathForm, curr: MathForm, sym: Any, s_prev: Any, s_curr: Any) -> str:
    """A concrete value that separates the two solution sets."""
    for source, other, label in ((s_prev, s_curr, "before"), (s_curr, s_prev, "after")):
        if isinstance(source, sympy.FiniteSet):
            for value in source.args:
                if value.is_number and other.contains(value) == sympy.false:
                    if label == "before":
                        return f"{sym} = {value} satisfies '{prev.source}' but not '{curr.source}'"
                    return f"{sym} = {value} satisfies '{curr.source}' but not '{prev.source}'"
    if s_curr == S.EmptySet:
        return f"no value of {sym} satisfies '{curr.source}'"
    return f"the solutions of '{prev.source}' and '{curr.source}' are not the same set"


def _sample_disagreement(prev: MathForm, curr: MathForm, syms: list[Any]) -> str | None:
    """Look for an assignment satisfying one relation and not the other."""
    if len(syms) != 1:
        return None
    sym = syms[0]
    for value in _SAMPLES:
        try:
            a = _run(lambda v=value: sympy.simplify(prev.relation().subs(sym, v)))
            b = _run(lambda v=value: sympy.simplify(curr.relation().subs(sym, v)))
        except Exception:
            return None
        if not (getattr(a, "is_number", False) and getattr(b, "is_number", False)):
            return None
        if (a == 0) != (b == 0):
            holds, fails = (prev.source, curr.source) if a == 0 else (curr.source, prev.source)
            return f"{sym} = {value} satisfies '{holds}' but not '{fails}'"
    return None


class SymbolicVerifier:
    """Tier 1. Deterministic, offline, and the only tier trusted with algebra."""

    tier: Literal[1, 2, 3] = 1
    name = "sympy"

    def verify(self, prev: StepView | None, curr: StepView, ctx: TaskContext) -> VerificationResult:
        started = time.perf_counter()

        def done(result: VerificationResult) -> VerificationResult:
            ms = int((time.perf_counter() - started) * 1000)
            return VerificationResult(
                tier=1,
                status=result.status,
                evidence=result.evidence,
                confidence=result.confidence,
                latency_ms=ms,
                detail=result.detail,
            )

        curr_form = parse(curr.raw_text)
        if not curr_form.ok:
            return done(unverifiable(1, f"could not parse the step: {curr_form.note}"))

        prev_form = parse(prev.raw_text) if prev is not None else parse_statement(ctx.statement)
        domain = _DOMAINS[ctx.var_domain]

        try:
            return done(self._decide(prev_form, curr_form, domain))
        except TimeoutError:
            return done(unverifiable(1, "symbolic check exceeded its time budget"))
        except Exception as exc:  # pragma: no cover - defensive
            return done(unverifiable(1, f"symbolic check could not complete: {exc}"))

    # -- readings -------------------------------------------------------------

    def _decide(self, prev: MathForm, curr: MathForm, domain: Any) -> VerificationResult:
        if curr.kind == "equation":
            return self._decide_equation(prev, curr, domain)
        if curr.kind == "expression" and prev.kind == "expression":
            return self._decide_expression(prev, curr)
        return unverifiable(1, "the step is not a self-contained equation")

    def _decide_equation(self, prev: MathForm, curr: MathForm, domain: Any) -> VerificationResult:
        # Reading A: a closed arithmetic claim, such as "-2 + 10 = 8" or "19 = 19".
        if not curr.symbols:
            truth = _closed_truth(curr)
            if truth is True:
                # True, and worth saying so — but a closed identity moves nothing along.
                # "19 = 19" is a check, and the claims layer must not read it as a
                # derivation.
                return VerificationResult(
                    tier=1,
                    status="valid",
                    evidence=f"'{curr.source}' is arithmetically true",
                    detail={"reading": "closed_identity", "derives": "no"},
                )
            if truth is False:
                return VerificationResult(
                    tier=1,
                    status="invalid",
                    evidence=f"'{curr.source}' is arithmetically false",
                    detail={"reading": "closed_identity"},
                )
            return unverifiable(1, "the arithmetic claim could not be decided")

        syms = sorted(curr.symbols | prev.symbols)
        symbols = [sympy.Symbol(name) for name in syms]

        # Reading B: a lemma — an identity true for every value, e.g. "7x - 3x = 4x".
        if len(symbols) == 1 and _is_identity(curr, symbols[0], domain):
            return VerificationResult(
                tier=1,
                status="valid",
                evidence=f"'{curr.source}' holds for every value of {symbols[0]}",
                detail={"reading": "lemma", "derives": "no"},
            )

        # Reading C: a move in the chain — it must preserve the solution set.
        if prev.kind == "equation" and prev.symbols and len(symbols) == 1:
            sym = symbols[0]
            s_prev = _solution_set(prev, sym, domain)
            s_curr = _solution_set(curr, sym, domain)
            if _sets_equal(s_prev, s_curr):
                return VerificationResult(
                    tier=1,
                    status="valid",
                    evidence=f"same solution set: {sympy.sstr(s_curr)}",
                    detail={"reading": "chain_move", "derives": "yes"},
                )
            if isinstance(s_prev, sympy.FiniteSet) and isinstance(s_curr, sympy.FiniteSet):
                return VerificationResult(
                    tier=1,
                    status="invalid",
                    evidence=_witness(prev, curr, sym, s_prev, s_curr),
                    detail={
                        "reading": "chain_move",
                        "solutions_before": sympy.sstr(s_prev),
                        "solutions_after": sympy.sstr(s_curr),
                    },
                )
            disagreement = _sample_disagreement(prev, curr, [sym])
            if disagreement:
                return VerificationResult(
                    tier=1,
                    status="invalid",
                    evidence=disagreement,
                    detail={"reading": "chain_move"},
                )
            return unverifiable(1, "the two solution sets could not be compared")

        return unverifiable(1, "no previous equation to compare the step against")

    def _decide_expression(self, prev: MathForm, curr: MathForm) -> VerificationResult:
        try:
            if _run(lambda: sympy.simplify(prev.expr - curr.expr)) == 0:
                return VerificationResult(
                    tier=1,
                    status="valid",
                    evidence=f"'{prev.source}' and '{curr.source}' are the same expression",
                    detail={"reading": "rewrite", "derives": "yes"},
                )
        except TimeoutError:
            return unverifiable(1, "symbolic check exceeded its time budget")

        syms = sorted(prev.symbols | curr.symbols)
        if len(syms) == 1:
            sym = sympy.Symbol(syms[0])
            for value in _SAMPLES:
                try:
                    diff = _run(
                        lambda v=value: sympy.simplify((prev.expr - curr.expr).subs(sym, v))
                    )
                except Exception:
                    return unverifiable(1, "expressions could not be compared")
                if getattr(diff, "is_number", False) and diff != 0:
                    return VerificationResult(
                        tier=1,
                        status="invalid",
                        evidence=(
                            f"at {sym} = {value}, '{prev.source}' and '{curr.source}' "
                            f"differ by {diff}"
                        ),
                        detail={"reading": "rewrite"},
                    )
        return unverifiable(1, "expressions could not be shown equal or unequal")
