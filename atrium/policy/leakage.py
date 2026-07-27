"""The leakage guard. Safety-critical, blocking, and the last thing between a realised move and
the learner. SPEC.md §6, §10.

Nothing the tutor says may contain the next line of the learner's working, the final answer, or the
procedure that produces them — in any notation, including words, LaTeX, and code. The target is
zero and a single failure fails the build.

This is a *filter on rendered output*, not a prompt instruction, and that distinction is the whole
design. Prompts are advisory; a learner who claims to be the teacher, or says it is an emergency,
or simply asks nine times, is applying exactly the pressure that prompts fold under. A regex and a
computer-algebra system do not fold.

Deliberate asymmetry, the mirror of the verifier's: here we would rather block a harmless sentence
than let one answer through. A false block costs one rephrase; a false pass costs the learner the
thing they came for.
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Final

import sympy
from pydantic import BaseModel, Field

from ..verify.symbolic import ParseFailure, is_relation, to_equation, to_expr


class LeakKind(str, Enum):
    FINAL_ANSWER = "final_answer"
    NEXT_LINE = "next_line"
    PROCEDURE = "procedure"
    ANALOGUE_TOO_CLOSE = "analogue_too_close"


class Leak(BaseModel):
    kind: LeakKind
    evidence: str
    detail: str = ""


class LeakageBlocked(Exception):
    def __init__(self, leak: Leak) -> None:
        super().__init__(f"{leak.kind.value}: {leak.evidence} ({leak.detail})")
        self.leak = leak


class LeakageContext(BaseModel):
    """What must not appear in tutor output for this learner, right now."""

    live_problem: str = ""
    #: Lines the learner has already written. Quoting these back is legitimate and expected —
    #: an ASK_PROBE has to be able to name the line it is about.
    learner_lines: list[str] = Field(default_factory=list)
    #: Canonical continuation the learner has *not* yet written. Every one of these is forbidden.
    remaining: list[str] = Field(default_factory=list)
    final_answer: str = ""
    variable: str = "x"


# --- normalisation --------------------------------------------------------------------------

_NUMBER_WORDS: Final[dict[str, int]] = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
    "seventy": 70, "eighty": 80, "ninety": 90, "hundred": 100,
}

_TENS_THEN_UNIT = re.compile(
    r"\b(twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)[\s-]"
    r"(one|two|three|four|five|six|seven|eight|nine)\b",
    re.I,
)


def _words_to_digits(text: str) -> str:
    """`twenty-three` -> `23`, `five` -> `5`, `minus four` -> `-4`.

    Spelling the answer out is the oldest way round a substring check, so it is normalised away
    before anything else looks at the text.
    """

    def _pair(m: re.Match[str]) -> str:
        return str(_NUMBER_WORDS[m.group(1).lower()] + _NUMBER_WORDS[m.group(2).lower()])

    out = _TENS_THEN_UNIT.sub(_pair, text)
    for word, value in sorted(_NUMBER_WORDS.items(), key=lambda kv: -len(kv[0])):
        out = re.sub(rf"\b{word}\b", str(value), out, flags=re.I)
    out = re.sub(r"\b(?:minus|negative)\s+(\d)", r"-\1", out, flags=re.I)
    return out


def _strip_markup(text: str) -> str:
    out = text
    for pattern in (r"\$\$", r"\$", r"\\\(", r"\\\)", r"\\\[", r"\\\]", r"`{1,3}"):
        out = re.sub(pattern, " ", out)
    out = re.sub(r"^\s*(?:python|latex|text)\s*$", " ", out, flags=re.M)
    return out


def _prepare(text: str) -> str:
    return _words_to_digits(_strip_markup(text))


# --- candidate extraction -------------------------------------------------------------------

# The separator is a mandatory space and the atom class excludes spaces, so there is exactly one
# way to match any given run. Written as `+(?:\s*...+)*` this backtracks catastrophically on
# ordinary English — "How did you get from the first line to the second?" hangs the process.
_ATOM: Final = r"[A-Za-z0-9_^*/+\-().\\{}]+"
_MATH_RUN: Final = rf"{_ATOM}(?:[ \t]{_ATOM})*"

_RELATION = re.compile(rf"({_MATH_RUN})\s*=\s*({_MATH_RUN})")

#: `x is 5`, `x equals -3`, `x comes out to 7/2`.
_IS_VALUE = re.compile(
    r"\b([a-zA-Z])\s*(?:is|equals|equal to|comes out to|works out to|becomes|will be|"
    r"turns out to be)\s*(?:equal to\s*)?(-?\d+(?:\.\d+)?(?:\s*/\s*\d+)?)\b",
    re.I,
)

#: `the answer is 5`, `the solution is -3`.
_ANSWER_IS = re.compile(
    r"\b(?:answer|solution|result|value)\b[^.\n]{0,24}?(-?\d+(?:\.\d+)?(?:\s*/\s*\d+)?)\b",
    re.I,
)

#: `it comes out to 5`, `that's 5`, `this works out to -3`. The answer referred to rather than
#: named — there is no variable to key on, so the pronoun has to be the hook.
_IT_IS_VALUE = re.compile(
    r"\b(?:it|that|this|the whole thing)\s*(?:'s|is|equals|comes out to|works out to|becomes|"
    r"will be|turns out to be)\s*(?:equal to\s*)?(-?\d+(?:\.\d+)?(?:\s*/\s*\d+)?)\b",
    re.I,
)

_TRAILING_MATH = re.compile(rf"({_MATH_RUN})\s*$")
_LEADING_MATH = re.compile(rf"^\s*({_MATH_RUN})")


def _trim_side(text: str, *, leading: bool) -> str:
    """Cut an English sentence down to the maths adjacent to the `=`."""
    chunk = re.split(r"[,;:!?\n]", text)[0 if leading else -1]
    match = (_LEADING_MATH if leading else _TRAILING_MATH).search(chunk)
    if not match:
        return ""
    side = match.group(1).strip()
    words = side.split()
    # Keep only the trailing (or leading) run of tokens that look like maths rather than prose.
    keep: list[str] = []
    for token in reversed(words) if not leading else words:
        # Variables are single letters. Any bare multi-letter alphabetic token is prose —
        # without this, "So x = 5" trims to "So x" and then fails to parse, and the leak walks.
        # The trailing punctuation class is not cosmetic: "3x = 15 here." kept "here." because a
        # word with a full stop attached is not a bare alphabetic token, and the leak walked.
        if re.fullmatch(r"[A-Za-z]{2,}[.,;:!?)]*", token):
            break
        keep.append(token)
    if not keep:
        return ""
    if not leading:
        keep.reverse()
    return " ".join(keep).strip(" .,;:")


def candidate_relations(text: str) -> list[str]:
    """Every `lhs = rhs` the text could be read as asserting."""
    prepared = _prepare(text)
    out: list[str] = []
    for match in _RELATION.finditer(prepared):
        lhs = _trim_side(match.group(1), leading=False)
        rhs = _trim_side(match.group(2), leading=True)
        if lhs and rhs:
            out.append(f"{lhs} = {rhs}")
    for match in _IS_VALUE.finditer(prepared):
        out.append(f"{match.group(1)} = {match.group(2).replace(' ', '')}")
    for pattern in (_ANSWER_IS, _IT_IS_VALUE):
        for match in pattern.finditer(prepared):
            out.append(f"__answer__ = {match.group(1).replace(' ', '')}")
    return out


# --- mathematical comparison ----------------------------------------------------------------


def _solutions(relation: str, variable: sympy.Symbol) -> sympy.Set | None:
    try:
        eq = to_equation(relation)
    except (ParseFailure, Exception):  # noqa: B014
        return None
    try:
        result = sympy.solveset(eq, variable, domain=sympy.S.Complexes)
    except Exception:  # noqa: BLE001
        return None
    return None if isinstance(result, sympy.ConditionSet) else result


def _same_expression(a: str, b: str) -> bool:
    try:
        return bool(sympy.simplify(to_expr(a) - to_expr(b)) == 0)
    except (ParseFailure, Exception):  # noqa: B014
        return False


def _same_line(a: str, b: str) -> bool:
    """Are these the *same line of working*, allowing for rewriting and side-swap?

    Not solution-set equality — that is the verifier's question, and it is the wrong one here.
    Every line of a correct derivation has the same solution set, so a solution-set test flags the
    tutor for quoting the problem back and calls it a leak. Two lines are the same line when their
    sides match, in either order.
    """
    try:
        ea, eb = to_equation(a), to_equation(b)
    except (ParseFailure, Exception):  # noqa: B014
        return False
    try:
        direct = sympy.simplify(ea.lhs - eb.lhs) == 0 and sympy.simplify(ea.rhs - eb.rhs) == 0
        swapped = sympy.simplify(ea.lhs - eb.rhs) == 0 and sympy.simplify(ea.rhs - eb.lhs) == 0
        return bool(direct or swapped)
    except Exception:  # noqa: BLE001
        return False


def _written_complexity(relation: str) -> int | None:
    """How much work is left in a line, as written.

    Counts operations on the *unexpanded* sides, so `3x + 8 = 23` (2) is heavier than `3x = 15`
    (1), which is heavier than `x = 5` (0). Expanding first would collapse all three to the same
    thing, which is exactly what makes this measure work: it reads the writing, not the maths.
    """
    try:
        eq = to_equation(relation)
    except (ParseFailure, Exception):  # noqa: B014
        return None
    try:
        return int(sympy.count_ops(eq.lhs) + sympy.count_ops(eq.rhs))
    except Exception:  # noqa: BLE001
        return None


def _written_same(a: str, b: str) -> bool:
    """Are these the same line *as written*? Textual, not mathematical — and that is the point.

    `2(x + 3) = 14` and `2x + 6 = 14` are equal as maths and different as writing. The first is
    what the learner has on the page; the second is the step they have not taken yet. A
    mathematical comparator cannot tell those apart, so quoting the problem back reads as handing
    over the next line. This one reads the writing.
    """
    def canon(text: str) -> str:
        out = re.sub(r"\s+", "", text.strip().rstrip(".,;:!?"))
        for junk in (r"\left", r"\right", r"\,", r"\!", "{", "}"):
            out = out.replace(junk, "")
        return out

    return bool(a and b and canon(a) == canon(b))


def _is_solved_form(line: str, var: sympy.Symbol) -> bool:
    """`x = 5` or `5 = x` — the learner has actually written the answer down."""
    try:
        eq = to_equation(line)
    except (ParseFailure, Exception):  # noqa: B014
        return False
    for side, other in ((eq.lhs, eq.rhs), (eq.rhs, eq.lhs)):
        if side == var and not other.free_symbols:
            return True
    return False


def _answer_value(ctx: LeakageContext) -> sympy.Expr | None:
    """The number the learner is trying to reach, if the final answer pins one down."""
    if not ctx.final_answer:
        return None
    var = sympy.Symbol(ctx.variable)
    if is_relation(ctx.final_answer):
        sols = _solutions(ctx.final_answer, var)
        if isinstance(sols, sympy.FiniteSet) and len(sols.args) == 1:
            return sympy.sympify(sols.args[0])
        return None
    try:
        return to_expr(ctx.final_answer)
    except ParseFailure:
        return None


# --- procedure supply -----------------------------------------------------------------------

_OPERATION_VERB = (
    r"(?:divid\w*|multipl\w*|subtract\w*|add\w*|take\w+|factoris\w*|factoriz\w*|factor\w*|"
    r"expand\w*|substitut\w*|square\w*|cube\w*|cancel\w*|collect\w*|move\w*|bring\w*)"
)

#: An operation verb with a concrete operand is the next line in words. `divide both sides by 3`
#: is not a hint, it is the step.
_OPERAND = r"[^.\n]{0,30}?\b(?:by|from|to|out|off)?\s*\(?-?\d+"

#: ...but only when it is *instructing*. "What's the opposite of adding 8?" names the same verb and
#: the same number while supplying nothing — it points at an operation already on the page. So the
#: verb has to sit in an imperative or suggestive frame before it counts.
_FRAME = (
    r"(?:^|[.!?]\s+|\n\s*|\b(?:you|your|let'?s|just|now|then|next|try|can|could|should|would|"
    r"must|need to|have to|want to|start by|begin by|first|why not|why don'?t you|"
    r"all you (?:need|have) to do is)\s+(?:\w+\s+){0,2})"
)

_PROCEDURE = re.compile(rf"{_FRAME}{_OPERATION_VERB}\b{_OPERAND}", re.I)

#: `both sides` is instruction-shaped whatever the frame: nobody says it descriptively.
_PROCEDURE_SIDES = re.compile(
    rf"\b{_OPERATION_VERB}\b[^.\n]{{0,20}}?\b(?:both|each|either)\s+sides?\b[^.\n]{{0,12}}?"
    rf"\b(?:by|from|to)\s*\(?-?\d*[a-z0-9]",
    re.I,
)

#: Named rather than numeric operands: `subtract the 8`, `move the 3x across`.
_PROCEDURE_TERM = re.compile(rf"{_FRAME}{_OPERATION_VERB}\b\s+(?:the\s+)?-?\d*[a-z]\b", re.I)


def supplies_procedure(text: str) -> str | None:
    """The next line stated as an instruction rather than as maths."""
    prepared = _prepare(text)
    for pattern in (_PROCEDURE, _PROCEDURE_SIDES, _PROCEDURE_TERM):
        match = pattern.search(prepared)
        if match:
            return match.group(0).strip()
    return None


# --- the guard ------------------------------------------------------------------------------


def check(text: str, ctx: LeakageContext) -> Leak | None:
    """Return the leak, or None if the text is safe to say."""
    if not text.strip():
        return None

    var = sympy.Symbol(ctx.variable)

    procedure = supplies_procedure(text)
    if procedure is not None:
        return Leak(
            kind=LeakKind.PROCEDURE,
            evidence=procedure,
            detail="names the operation and its operand; that is the next line in words",
        )

    answer_value = _answer_value(ctx)
    # If the learner has already got to `x = 5` themselves, saying it back is not a leak. Note
    # this asks whether they wrote the answer *in solved form* — the original problem shares the
    # answer's solution set, so a solution-set test here would silence the guard entirely.
    answer_on_screen = any(
        _is_solved_form(line, var) and _same_line(line, ctx.final_answer)
        for line in ctx.learner_lines
        if ctx.final_answer
    )
    # The lightest line the learner has actually written. Anything lighter that still pins the
    # same answer is work we did for them.
    written = [
        c for c in (_written_complexity(line) for line in ctx.learner_lines) if c is not None
    ]
    floor = min(written) if written else None

    for candidate in candidate_relations(text):
        if candidate.startswith("__answer__"):
            if answer_value is not None and not answer_on_screen:
                stated = candidate.split("=", 1)[1].strip()
                if _same_expression(stated, str(answer_value)):
                    return Leak(
                        kind=LeakKind.FINAL_ANSWER,
                        evidence=candidate.replace("__answer__ = ", ""),
                        detail="states the final answer outright",
                    )
            continue

        # Quoting a line the learner has already written supplies nothing, and an ASK_PROBE has
        # to be able to name the line it is about. Checked first and textually, so that quoting
        # `2(x + 3) = 14` is not mistaken for handing over `2x + 6 = 14`.
        if any(_written_same(candidate, line) for line in ctx.learner_lines):
            continue

        if ctx.final_answer and not answer_on_screen and _same_line(candidate, ctx.final_answer):
            return Leak(
                kind=LeakKind.FINAL_ANSWER,
                evidence=candidate,
                detail=f"states the final answer {ctx.final_answer!r}",
            )

        for line in ctx.remaining:
            if _same_line(candidate, line):
                return Leak(
                    kind=LeakKind.NEXT_LINE,
                    evidence=candidate,
                    detail=f"states the learner's next line {line!r}",
                )

        # Catch the paraphrase that is not literally any canonical line but still advances the
        # derivation — `2x = 10` when they are at `3x + 8 = 23`. Same answer, less work left.
        complexity = _written_complexity(candidate)
        if (
            floor is not None
            and complexity is not None
            and complexity < floor
            and not answer_on_screen
            and _relations_agree(candidate, ctx.final_answer, var)
        ):
            return Leak(
                kind=LeakKind.NEXT_LINE,
                evidence=candidate,
                detail=(
                    "advances the derivation: same answer, "
                    "fewer steps left than the learner has"
                ),
            )

    # Bare expressions matching a line the learner has not written yet.
    prepared = _prepare(text)
    for line in ctx.remaining:
        if is_relation(line):
            continue
        for chunk in re.findall(_MATH_RUN, prepared):
            if len(chunk.strip()) < 3 or not any(c.isalpha() for c in chunk):
                continue
            if _same_expression(chunk, line):
                return Leak(
                    kind=LeakKind.NEXT_LINE,
                    evidence=chunk.strip(),
                    detail=f"equivalent to the learner's next line {line!r}",
                )
    return None


def _relations_agree(a: str, b: str, var: sympy.Symbol) -> bool:
    if not a or not b:
        return False
    sa, sb = _solutions(a, var), _solutions(b, var)
    if sa is None or sb is None:
        return False
    if sa is sympy.S.Complexes or sb is sympy.S.Complexes:
        return False  # a tautology like `x = x` pins nothing down
    try:
        return bool(sympy.simplify(sa.symmetric_difference(sb)) == sympy.S.EmptySet)
    except Exception:  # noqa: BLE001
        return bool(sa == sb)


def guard(text: str, ctx: LeakageContext) -> str:
    """Return the text, or raise. Every realised move passes through this."""
    leak = check(text, ctx)
    if leak is not None:
        raise LeakageBlocked(leak)
    return text


# --- D1: the analogue distance guard ---------------------------------------------------------


class DistanceReport(BaseModel):
    differs: list[str] = Field(default_factory=list)
    solutions_differ: bool = False

    @property
    def ok(self) -> bool:
        return len(self.differs) >= 2 and self.solutions_differ


def _own_variable(problem: str, fallback: sympy.Symbol) -> sympy.Symbol:
    """Each problem is measured in its own unknown.

    An analogue almost always renames the variable, so forcing both through `x` makes
    `variable_side` differ for free and inflates every distance by one — which would let
    `3x + 7 = 22` through against `3x + 8 = 23` merely by calling it `y`.
    """
    try:
        eq = to_equation(problem)
    except (ParseFailure, Exception):  # noqa: B014
        return fallback
    symbols = sorted(eq.free_symbols, key=str)
    return symbols[0] if len(symbols) == 1 else fallback


def _features(problem: str, var: sympy.Symbol) -> dict[str, object] | None:
    try:
        eq = to_equation(problem)
    except (ParseFailure, Exception):  # noqa: B014
        return None
    var = _own_variable(problem, var)
    try:
        poly = sympy.Poly(sympy.expand(eq.lhs - eq.rhs), var)
        coeffs = tuple(poly.all_coeffs())
    except Exception:  # noqa: BLE001
        coeffs = ()
    return {
        "coefficients": tuple(sorted(map(str, coeffs))),
        # Brackets count: `2(x+1) = 14` is a structurally different problem from `3x + 8 = 23`
        # even though both contain exactly one `+`.
        "operation_order": tuple(c for c in problem if c in "+-*/()"),
        "variable_side": var in eq.lhs.free_symbols,
        "sign_pattern": tuple(sympy.sign(c) if c.is_number else 0 for c in coeffs),
    }


def analogue_distance(live_problem: str, analogue: str, variable: str = "x") -> DistanceReport:
    """DECISIONS.md D1.

    A fully worked analogue is only allowed if it is genuinely a different problem: it must differ
    in at least two of {coefficients, operation order, variable side, sign pattern} *and* have a
    different solution. `3x + 7 = 22` against a live `3x + 8 = 23` is the answer with a coat on.

    Anything we cannot parse scores zero and is refused, because an unreadable analogue is one we
    cannot certify as distant.
    """
    var = sympy.Symbol(variable)
    live, other = _features(live_problem, var), _features(analogue, var)
    if live is None or other is None:
        return DistanceReport()

    differs = [key for key in live if live[key] != other[key]]
    live_sol = _solutions(live_problem, _own_variable(live_problem, var))
    other_sol = _solutions(analogue, _own_variable(analogue, var))
    solutions_differ = bool(
        live_sol is not None and other_sol is not None and live_sol != other_sol
    )
    return DistanceReport(differs=differs, solutions_differ=solutions_differ)
