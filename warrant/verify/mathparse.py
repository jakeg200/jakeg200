"""Turning a learner's sentence into something SymPy can hold.

This module is the main source of false-accusation risk in the whole system: if we
misread what somebody wrote and then prove the misreading wrong, we have told a
correct person they are incorrect. Every decision here is therefore biased towards
returning nothing. A parse that is merely *probably* right is not good enough — it
must be unambiguous, or we hand the step to a tier that is allowed to be unsure.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

import sympy
from sympy.parsing.sympy_parser import (
    convert_xor,
    implicit_multiplication_application,
    standard_transformations,
)

TRANSFORMS = (*standard_transformations, implicit_multiplication_application, convert_xor)

FormKind = Literal["equation", "expression", "none"]

# Words a learner writes instead of an operator. Replaced only as whole words, and only
# where the surrounding text is otherwise arithmetic. "less" is deliberately absent:
# "x is less than 3" is an inequality, and misreading it as subtraction would be exactly
# the kind of confident misparse this module exists to prevent.
WORD_OPERATORS: list[tuple[str, str]] = [
    (r"\bis\s+equal\s+to\b", "="),
    (r"\bequals\b", "="),
    (r"\bgives\b", "="),
    (r"\bmakes\b", "="),
    (r"\bcomes\s+to\b", "="),
    (r"\bresults\s+in\b", "="),
    # Learners write "4x is 8" far more often than "4x = 8". Reading "is" as equality is
    # safe because a comparative reading ("is less than") leaves the words "less than"
    # in the span, and a span containing long words is refused outright.
    (r"\bis\b", "="),
    (r"\btake\s+away\b", "-"),
    (r"\bsubtract\b", "-"),
    (r"\bminus\b", "-"),
    (r"\bplus\b", "+"),
    (r"\badd\b", "+"),
    (r"\btimes\b", "*"),
    (r"\bmultiplied\s+by\b", "*"),
    (r"\bdivided\s+by\b", "/"),
    (r"\bover\b", "/"),
    (r"\bsquared\b", "^2"),
    (r"\bcubed\b", "^3"),
]

# Text that means the step is not a self-contained mathematical claim. If any of these
# appear inside the span we extracted, we refuse to parse it.
HEDGES = re.compile(
    r"\b(if|unless|assume|suppose|maybe|probably|guess|think|might|should|would|"
    r"either|or|not|isn't|doesn't|cannot|can't|approximately|about|roughly|"
    r"less\s+than|greater\s+than|at\s+most|at\s+least)\b",
    re.IGNORECASE,
)

INEQUALITY = re.compile(r"[<>]|≤|≥|!=|≠")

# A maximal run of characters that could be mathematics.
MATH_SPAN = re.compile(r"[0-9A-Za-z_.^*/+\-()=\s]+")

# Tokens that look like maths characters but are really English.
STOPWORDS = {
    "so",
    "then",
    "and",
    "the",
    "answer",
    "is",
    "we",
    "get",
    "gives",
    "giving",
    "now",
    "therefore",
    "hence",
    "thus",
    "which",
    "that",
    "this",
    "both",
    "sides",
    "side",
    "by",
    "to",
    "from",
    "of",
    "on",
    "in",
    "it",
    "a",
    "an",
    "step",
    "first",
    "next",
    "finally",
    "check",
    "checking",
    "substitute",
    "substituting",
    "sub",
    "back",
    "into",
    "left",
    "right",
    "hand",
    "up",
    "down",
    "out",
    "since",
    "because",
    "also",
    "solve",
    "solving",
    "solution",
    "value",
    "for",
    "with",
    "as",
    "same",
    "result",
    "true",
    "holds",
    "works",
    "correct",
    "yes",
    "no",
    "just",
    "simplify",
    "simplifies",
    "simplifying",
    "collect",
    "collecting",
    "terms",
    "term",
    "like",
    "factor",
    "factorise",
    "factorize",
    "expand",
    "expanding",
    "bracket",
    "brackets",
    "divide",
    "dividing",
    "multiply",
    "multiplying",
    "adding",
    "subtracting",
    "cancel",
    "cancels",
    "cancelling",
    "move",
    "moving",
    "swap",
    "rearrange",
    "rearranging",
    "isolate",
    "start",
    "starting",
    "put",
    "leaves",
    "leaving",
    "means",
    "must",
    "be",
    "have",
    "has",
    "had",
    "let",
    "define",
    "where",
    "when",
    "each",
    "all",
    "every",
    "my",
    "you",
    "your",
    "our",
    "getting",
    "got",
    "give",
    "given",
    "work",
    "working",
    "over",
    "under",
    "again",
    "one",
    "two",
    "three",
}


@dataclass(frozen=True)
class MathForm:
    """A parsed mathematical claim, or the explicit absence of one."""

    kind: FormKind
    lhs: Any = None
    rhs: Any = None
    expr: Any = None
    symbols: frozenset[str] = frozenset()
    source: str = ""
    note: str = ""

    @property
    def ok(self) -> bool:
        return self.kind != "none"

    def relation(self) -> Any:
        """lhs - rhs for an equation; the expression itself otherwise."""
        if self.kind == "equation":
            return sympy.together(self.lhs - self.rhs)
        return self.expr


NONE = MathForm(kind="none")


def _none(note: str) -> MathForm:
    return MathForm(kind="none", note=note)


def _normalise_words(text: str) -> str:
    out = text
    for pattern, replacement in WORD_OPERATORS:
        out = re.sub(pattern, f" {replacement} ", out, flags=re.IGNORECASE)
    # Unicode a learner may paste in.
    out = out.replace("−", "-").replace("×", "*").replace("÷", "/").replace("·", "*")
    out = out.replace("≠", "!=")
    return out


def _span_is_mathematical(span: str) -> bool:
    """True when every word-like token in the span is a number or a short identifier."""
    if not re.search(r"\d|[A-Za-z]", span):
        return False
    for token in re.findall(r"[A-Za-z_][A-Za-z_0-9]*", span):
        if token.lower() in STOPWORDS:
            return False
        # The English pronoun, which SymPy would happily read as the imaginary unit.
        if token == "I":
            return False
        # A bare identifier is a variable only if it is short. "sides" is not a variable.
        if len(token) > 2 and token.lower() not in ("pi", "sqrt", "abs"):
            return False
    return True


def _candidate_spans(text: str) -> list[str]:
    spans: list[str] = []
    for raw in MATH_SPAN.findall(text):
        span = raw.strip(" \t")
        if not span:
            continue
        # Trim leading/trailing English words off the edge of the span.
        words = span.split()
        while words and words[0].lower().strip("().,") in STOPWORDS:
            words.pop(0)
        while words and words[-1].lower().strip("().,") in STOPWORDS:
            words.pop()
        # A dangling relation sign is the residue of stripped English ("the answer is
        # x = 3" leaves "= x = 3"). It is never part of the claim.
        span = " ".join(words).strip(" .,;:").strip("= \t")
        if span and _span_is_mathematical(span):
            spans.append(span)
    return spans


def _rationalise(expr: Any) -> Any:
    """Replace decimal literals with exact rationals.

    Without this, a learner who writes 5.5 where the previous line implies 11/2 is
    compared Float-against-Rational, the two sets fail to match, and we accuse somebody
    who is exactly right of being wrong. Notation is not error.
    """
    floats = expr.atoms(sympy.Float)
    if not floats:
        return expr
    return expr.xreplace({f: sympy.Rational(str(f)) for f in floats})


def _sympify(source: str) -> Any | None:
    try:
        parsed = sympy.parse_expr(
            source,
            transformations=TRANSFORMS,
            evaluate=True,
        )
    except Exception:
        return None
    if parsed is None:
        return None
    if isinstance(parsed, sympy.logic.boolalg.BooleanAtom):
        # "2 = 2" parses to True and loses its content; handled by the caller instead.
        return None
    try:
        return _rationalise(parsed)
    except Exception:
        return parsed


def parse(text: str) -> MathForm:
    """Parse a learner's step into an equation or an expression, or return nothing.

    Never raises. Returns MathForm(kind="none") whenever the reading is not forced.
    """
    if not text or not text.strip():
        return _none("empty")

    normalised = _normalise_words(text)

    if INEQUALITY.search(normalised):
        return _none("inequality: outside the v0 symbolic tier")

    spans = _candidate_spans(normalised)
    if not spans:
        return _none("no mathematical span found")

    # Prefer a span that asserts something (contains "="), then the longest.
    spans.sort(key=lambda s: ("=" not in s, -len(s)))
    span = spans[0]

    if HEDGES.search(span):
        return _none("hedged or conditional claim")

    if span.count("=") > 1:
        # A chain like "4x = 8 = 2" is ambiguous about what is being claimed.
        return _none("multiple relations in one step")

    if "=" in span:
        left, right = span.split("=", 1)
        lhs = _sympify(left.strip())
        rhs = _sympify(right.strip())
        if lhs is None or rhs is None:
            return _none("equation side did not parse")
        syms = {str(s) for s in (lhs.free_symbols | rhs.free_symbols)}
        return MathForm(kind="equation", lhs=lhs, rhs=rhs, symbols=frozenset(syms), source=span)

    expr = _sympify(span.strip())
    if expr is None:
        return _none("expression did not parse")
    if not re.search(r"[+\-*/^]", span) or not expr.free_symbols:
        # A step with no relation only says something if it is an open expression being
        # rewritten. "multiply by 2" must not become the claim "2", "x is a solution"
        # must not become the claim "x", and "add 2 to both sides" must not become "2".
        return _none("bare term carries no claim")
    return MathForm(
        kind="expression",
        expr=expr,
        symbols=frozenset(str(s) for s in expr.free_symbols),
        source=span,
    )


def parse_statement(statement: str) -> MathForm:
    """Parse a task statement such as 'Solve 7x - 2 = 3x + 10' into its equation."""
    stripped = re.sub(
        r"^\s*(solve|find|work\s+out|calculate|determine|evaluate)\b[^0-9A-Za-z]*",
        "",
        statement,
        flags=re.IGNORECASE,
    )
    stripped = re.sub(r"\bfor\s+[a-z]\s*[:.]?\s*$", "", stripped, flags=re.IGNORECASE)
    return parse(stripped)


def carries_state(form: MathForm) -> bool:
    """True when the step restates the equation being solved, rather than a side fact.

    "4x = 12" carries the state of the problem forward. "-2 + 10 = 8" and "7x - 3x = 4x"
    are true remarks about arithmetic that leave the problem exactly where it was. The
    next step has to be judged against the last line that actually moved.
    """
    return form.kind == "equation" and bool(form.symbols)


def is_solved_form(form: MathForm) -> bool:
    """True for 'x = 3' and '3 = x' — an answer, stated."""
    if form.kind != "equation" or len(form.symbols) != 1:
        return False
    for side, other in ((form.lhs, form.rhs), (form.rhs, form.lhs)):
        if side.is_Symbol and getattr(other, "is_number", False):
            return True
    return False


def is_trivial_identity(form: MathForm) -> bool:
    """True for a closed numeric identity such as 19 = 19.

    Such a statement is *true*, and verifying it is a legitimate act, but it derives
    nothing. The claims layer needs to be able to tell the difference.
    """
    if form.kind != "equation" or form.symbols:
        return False
    try:
        return bool(sympy.simplify(form.lhs - form.rhs) == 0)
    except Exception:
        return False
