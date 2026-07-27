"""Tier 1 — SymPy. Certain, deterministic, and biased hard against accusing anyone.

Two criteria, per SPEC.md §7:

* equation moves — solution-set equality,
* expression moves — ``simplify(prev - curr) == 0``.

The subtlety that the whole false-accusation eval turns on: **``simplify(diff) != 0`` is not
evidence of a break.** SymPy failing to reduce something to zero is a statement about SymPy, not
about the learner. So a non-zero simplification never returns `invalid` on its own — it demotes to
a hunt for a *counterexample*, and only a concrete point where the two lines genuinely disagree is
allowed to convict. Everything else is `unverifiable`.

That asymmetry costs recall on real errors, which is the correct trade. A missed error becomes a
probe a few seconds later when the learner's next line is also wrong. A false accusation costs the
learner's trust in the room, and they only lend it once.
"""

from __future__ import annotations

import random
from tokenize import TokenError
from typing import Final

import sympy
from sympy.core.sympify import SympifyError
from sympy.parsing.sympy_parser import (
    convert_xor,
    implicit_multiplication_application,
    parse_expr,
    standard_transformations,
)

from .base import Step, StepKind, Tier, Verdict, Verification, Verifier, unverifiable

_TRANSFORMS: Final = (
    *standard_transformations,
    implicit_multiplication_application,
    convert_xor,
)

# Sampling for counterexample hunting. Small integers first — a sign error shows up at x=2 and a
# reader can check it by hand, which matters when a break gets surfaced to a human.
_PROBE_POINTS: Final[tuple[int, ...]] = (2, 3, 5, 7, -1, -3, 11, 13)
_NUMERIC_TOL: Final = 1e-9

# Guard against pathological input reaching SymPy's slower paths at all.
_MAX_LEN: Final = 400


class ParseFailure(Exception):
    pass


# --- LaTeX -> SymPy -------------------------------------------------------------------------
#
# Deliberately not sympy.parsing.latex.parse_latex: it needs antlr at runtime and it raises on
# handwriting-grade LaTeX far more often than this does. We only need the fragment of LaTeX that
# comes out of the recogniser, and we would rather normalise tolerantly and then let parse_expr
# be the strict gate.

_REPLACEMENTS: Final[tuple[tuple[str, str], ...]] = (
    (r"\left", ""),
    (r"\right", ""),
    (r"\cdot", "*"),
    (r"\times", "*"),
    (r"\div", "/"),
    (r"\pi", "pi"),
    (r"\ ", " "),
    (r"\!", ""),
    (r"\,", " "),
    (r"\;", " "),
    ("{", "("),
    ("}", ")"),
    ("^", "**"),
)

# Named functions we are willing to read. Anything outside this list keeps its backslash and is
# refused by `normalise` — see the comment there on why guessing is worse than abstaining.
_FUNCTIONS: Final[tuple[tuple[str, str], ...]] = (
    (r"\arcsin", "asin"),
    (r"\arccos", "acos"),
    (r"\arctan", "atan"),
    (r"\sinh", "sinh"),
    (r"\cosh", "cosh"),
    (r"\tanh", "tanh"),
    (r"\sin", "sin"),
    (r"\cos", "cos"),
    (r"\tan", "tan"),
    (r"\sec", "sec"),
    (r"\csc", "csc"),
    (r"\cot", "cot"),
    (r"\ln", "log"),
    (r"\log", "log"),
    (r"\exp", "exp"),
    (r"\sqrt", "sqrt"),
    (r"\abs", "Abs"),
)


def _strip_fracs(s: str) -> str:
    r"""Rewrite ``\frac{a}{b}`` as ``((a)/(b))``, innermost first, brace-balanced."""
    while True:
        i = s.find(r"\frac")
        if i == -1:
            return s
        j = i + len(r"\frac")
        parts: list[str] = []
        for _ in range(2):
            while j < len(s) and s[j] == " ":
                j += 1
            if j >= len(s) or s[j] != "{":
                raise ParseFailure(r"malformed \frac")
            depth = 0
            start = j + 1
            while j < len(s):
                if s[j] == "{":
                    depth += 1
                elif s[j] == "}":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            if depth != 0:
                raise ParseFailure(r"unbalanced braces in \frac")
            parts.append(s[start:j])
            j += 1
        s = f"{s[:i]}(({parts[0]})/({parts[1]})){s[j:]}"


def normalise(raw: str) -> str:
    s = raw.strip()
    if not s:
        raise ParseFailure("empty")
    if len(s) > _MAX_LEN:
        raise ParseFailure("too long")
    s = _strip_fracs(s)
    for old, new in _FUNCTIONS:  # longest-first, so \arcsin never becomes (arc)sin
        s = s.replace(old, new)
    for old, new in _REPLACEMENTS:
        s = s.replace(old, new)
    # A stray backslash means a command we do not model. Refuse rather than guess: a silently
    # mangled parse is how a correct line becomes an accusation.
    if "\\" in s:
        raise ParseFailure(f"unhandled LaTeX command in {raw!r}")
    # A subscripted log is a different function from `log`, and parse_expr would silently read
    # `log_2(x)` as a symbol times x. Refuse rather than mis-read.
    if "log_" in s:
        raise ParseFailure(f"subscripted logarithm in {raw!r}")
    return s.strip()


def to_expr(raw: str) -> sympy.Expr:
    text = normalise(raw)
    if "=" in text:
        raise ParseFailure("expression expected, found a relation")
    try:
        expr = parse_expr(text, transformations=_TRANSFORMS, evaluate=True)
    except (SympifyError, SyntaxError, TypeError, AttributeError, TokenError) as exc:
        raise ParseFailure(f"cannot parse {raw!r}: {exc}") from exc
    if not isinstance(expr, sympy.Expr):
        raise ParseFailure(f"not an expression: {raw!r}")
    return expr


def to_equation(raw: str) -> sympy.Eq:
    text = normalise(raw)
    halves = text.split("=")
    if len(halves) != 2:
        raise ParseFailure(f"expected exactly one '=' in {raw!r}")
    lhs, rhs = (to_expr(h) for h in halves)
    return sympy.Eq(lhs, rhs)


def is_relation(raw: str) -> bool:
    try:
        return "=" in normalise(raw)
    except ParseFailure:
        return "=" in raw


# --- comparison -----------------------------------------------------------------------------


def _provably_zero(diff: sympy.Expr) -> bool:
    try:
        if sympy.simplify(diff) == 0:
            return True
        return bool(sympy.expand(sympy.together(diff)) == 0)
    except Exception:  # noqa: BLE001 - SymPy raises a wide and undocumented set here
        return False


def _counterexample(diff: sympy.Expr, symbols: list[sympy.Symbol]) -> dict[str, str] | None:
    """Find a point where `diff` is definitely non-zero.

    Returns the witness, or None. None means "no counterexample found", which is *not* the same
    as "they agree" — the caller must treat it as unverifiable.
    """
    rng = random.Random(0xA7B1)  # fixed: verification must be reproducible for the eval corpus
    candidates = list(_PROBE_POINTS) + [rng.randint(-50, 50) for _ in range(12)]
    for value_seed in candidates:
        subs = {s: sympy.Integer(value_seed + i) for i, s in enumerate(symbols)}
        try:
            at = diff.subs(subs)
            if at.free_symbols:
                continue
            num = sympy.N(at, 20)
            if not num.is_finite:
                continue
            if abs(complex(num)) > _NUMERIC_TOL:
                # Confirm exactly. Floating point must never be the sole basis of an accusation.
                exact = sympy.nsimplify(at, rational=True)
                if sympy.simplify(exact) != 0:
                    return {str(k): str(v) for k, v in subs.items()}
        except Exception:  # noqa: BLE001
            continue
    return None


def _solution_set(eq: sympy.Eq, symbol: sympy.Symbol) -> sympy.Set | None:
    try:
        result = sympy.solveset(eq, symbol, domain=sympy.S.Complexes)
    except Exception:  # noqa: BLE001
        return None
    if isinstance(result, sympy.ConditionSet):
        return None  # solveset gave up; so do we
    return result


class SymbolicVerifier(Verifier):
    tier = Tier.SYMBOLIC

    def verify(self, step: Step) -> Verification:
        if step.is_first_line():
            return unverifiable("no antecedent line", self.tier, step.line_index)

        prev_rel, curr_rel = is_relation(step.prev), is_relation(step.curr)
        if prev_rel != curr_rel:
            # An equation becoming an expression is usually the learner reaching an answer, or the
            # recogniser dropping an '='. Either way tier 1 has nothing certain to say.
            return unverifiable("relation/expression mismatch", self.tier, step.line_index)

        try:
            if prev_rel:
                return self._verify_equation(step)
            return self._verify_expression(step)
        except ParseFailure as exc:
            return unverifiable(str(exc), self.tier, step.line_index)
        except Exception as exc:  # noqa: BLE001 - never let a SymPy internal become a conviction
            return unverifiable(f"tier 1 error: {exc}", self.tier, step.line_index)

    def _verify_expression(self, step: Step) -> Verification:
        prev, curr = to_expr(step.prev), to_expr(step.curr)
        diff = prev - curr

        if _provably_zero(diff):
            return Verification(
                verdict=Verdict.VALID,
                tier=self.tier,
                reason="simplify(prev - curr) == 0",
                line_index=step.line_index,
            )

        symbols = sorted(prev.free_symbols | curr.free_symbols, key=str)
        if not symbols:
            # Both sides closed-form numeric and not equal: that is certain.
            return Verification(
                verdict=Verdict.INVALID,
                tier=self.tier,
                reason=f"{sympy.N(prev, 12)} != {sympy.N(curr, 12)}",
                line_index=step.line_index,
            )

        witness = _counterexample(diff, list(symbols))
        if witness is None:
            return unverifiable(
                "could not prove equal and found no counterexample", self.tier, step.line_index
            )
        at = ", ".join(f"{k}={v}" for k, v in witness.items())
        return Verification(
            verdict=Verdict.INVALID,
            tier=self.tier,
            reason=f"the two lines disagree at {at}",
            line_index=step.line_index,
        )

    def _verify_equation(self, step: Step) -> Verification:
        prev, curr = to_equation(step.prev), to_equation(step.curr)

        prev_syms = prev.free_symbols
        curr_syms = curr.free_symbols
        if curr_syms - prev_syms:
            return unverifiable("new symbol introduced", self.tier, step.line_index)

        symbols = sorted(prev_syms | curr_syms, key=str)
        if len(symbols) != 1:
            # Multivariate solution-set equality is a different problem (SPEC.md §14 defers the
            # subject that needs it). Fall back to the certain half: equal as relations.
            if _provably_zero((prev.lhs - prev.rhs) - (curr.lhs - curr.rhs)):
                return Verification(
                    verdict=Verdict.VALID,
                    tier=self.tier,
                    reason="relations differ by zero",
                    line_index=step.line_index,
                )
            return unverifiable(
                f"{len(symbols)} unknowns; no solution-set comparison", self.tier, step.line_index
            )

        symbol = symbols[0]
        prev_set = _solution_set(prev, symbol)
        curr_set = _solution_set(curr, symbol)
        if prev_set is None or curr_set is None:
            return unverifiable("solveset abstained", self.tier, step.line_index)

        try:
            same = sympy.simplify(prev_set.symmetric_difference(curr_set)) == sympy.S.EmptySet
        except Exception:  # noqa: BLE001
            same = prev_set == curr_set

        if same:
            return Verification(
                verdict=Verdict.VALID,
                tier=self.tier,
                reason=f"same solution set {prev_set}",
                line_index=step.line_index,
            )

        # Positive evidence required even here: a set comparison that merely failed to confirm
        # equality is not a break. Demand that both sets are concrete and genuinely different.
        if isinstance(prev_set, sympy.FiniteSet) and isinstance(curr_set, sympy.FiniteSet):
            return Verification(
                verdict=Verdict.INVALID,
                tier=self.tier,
                reason=f"solution set changed: {prev_set} -> {curr_set}",
                line_index=step.line_index,
            )
        return unverifiable("solution sets not comparably concrete", self.tier, step.line_index)


def infer_kind(step: Step) -> StepKind:
    """Best-effort classification, used to gate tier 3 (which may never convict on algebra)."""
    if is_relation(step.prev) and is_relation(step.curr):
        return StepKind.EQUATION_SOLVE
    if is_relation(step.prev) != is_relation(step.curr):
        return StepKind.UNKNOWN
    return StepKind.ALGEBRAIC
