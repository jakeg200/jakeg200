"""The struggle log and spaced resurfacing. SPEC.md §8.4.

Append-only: topic, first-break line, error class, resolution move, elapsed.

Its job is not analytics, it is the opening of the next session. The room reopens an old sticking
point at the right interval *without announcing it as revision* — no "let's review", no badge, no
streak. The learner meets the thing again in the ordinary course of working, which is the only way
spacing works on someone who does not want to be revising.

This is also what makes M5's acceptance test pass: session two opens on what session one got stuck
on, without being told.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import Enum
from typing import Final

from pydantic import BaseModel, Field

from ..policy.moves import MoveType


class ErrorClass(str, Enum):
    SIGN = "sign"
    ARITHMETIC = "arithmetic"
    DISTRIBUTION = "distribution"
    TRANSPOSITION = "transposition"  # moving a term across the equals
    NOTATION = "notation"
    PREREQUISITE = "prerequisite"
    UNKNOWN = "unknown"


class StruggleEntry(BaseModel):
    learner_id: str
    topic_id: str
    skill_id: str = ""
    problem_id: str = ""
    first_break_line: int = 0
    first_break_latex: str = ""
    error_class: ErrorClass = ErrorClass.UNKNOWN
    resolution_move: MoveType | None = None
    elapsed_s: int = 0
    at: datetime = Field(default_factory=datetime.utcnow)
    resolved: bool = False


#: Expanding intervals, in days. Standard spacing, deliberately unsurprising — the innovation in
#: §8.4 is *not announcing it*, not the schedule.
INTERVALS: Final[tuple[int, ...]] = (1, 3, 7, 16, 35)


def due_at(entry: StruggleEntry, resurfaced_count: int) -> datetime:
    index = min(resurfaced_count, len(INTERVALS) - 1)
    return entry.at + timedelta(days=INTERVALS[index])


def due_now(
    entries: list[StruggleEntry],
    resurfaced: dict[str, int] | None = None,
    now: datetime | None = None,
) -> list[StruggleEntry]:
    """Sticking points ready to be reopened, oldest debt first.

    Unresolved entries come first regardless of interval: something the learner never got past is
    not waiting for a schedule.
    """
    now = now or datetime.utcnow()
    resurfaced = resurfaced or {}
    ready = [
        entry
        for entry in entries
        if not entry.resolved or due_at(entry, resurfaced.get(entry.skill_id, 0)) <= now
    ]
    return sorted(ready, key=lambda e: (e.resolved, e.at))


def opening_topic(entries: list[StruggleEntry], now: datetime | None = None) -> str | None:
    """What the room should open on. M5's acceptance test, in one function."""
    ready = due_now(entries, now=now)
    return ready[0].topic_id if ready else None


def _sign_flip(previous: str, current: str) -> bool:
    r"""Do the two lines differ by the sign of exactly one term?

    This is the error §8.2 holds up as the example worth naming — "reliably drops a sign when a
    negative term crosses the equals" — so it is worth detecting properly rather than guessing from
    how many minus signs are on the page.

    Both sides are reduced to `lhs - rhs` and normalised by the leading coefficient, so a sign
    error survives being scaled: `3x + 8 = 23` -> `3x = -15` and `x + 8 = 23` -> `x = -15` are the
    same mistake and classify the same way.
    """
    try:
        import sympy

        from ..verify.symbolic import to_equation

        pe, ce = to_equation(previous), to_equation(current)
        symbols = sorted(pe.free_symbols | ce.free_symbols, key=str)
        if len(symbols) != 1:
            return False
        var = symbols[0]
        pa = sympy.Poly(sympy.expand(pe.lhs - pe.rhs), var).all_coeffs()
        cb = sympy.Poly(sympy.expand(ce.lhs - ce.rhs), var).all_coeffs()
    except Exception:  # noqa: BLE001
        return False

    if len(pa) != len(cb) or not pa or not cb:
        return False
    if pa[0] == 0 or cb[0] == 0:
        return False
    left = [c / pa[0] for c in pa]
    right = [c / cb[0] for c in cb]
    flipped = [i for i, (a, b) in enumerate(zip(left, right, strict=True)) if a != b]
    return len(flipped) == 1 and left[flipped[0]] == -right[flipped[0]]


def classify(previous: str, current: str) -> ErrorClass:
    """Cheap classification of a break. Good enough to group the struggle log by.

    Not a full diagnosis — that is a model call at session end. This exists so the log is groupable
    without one, and so a session that never reaches the model still deposits something in the
    learner model (§1).
    """
    if _sign_flip(previous, current):
        return ErrorClass.SIGN

    prev_signs = previous.count("-")
    curr_signs = current.count("-")
    if prev_signs != curr_signs and _digits(previous) == _digits(current):
        return ErrorClass.SIGN
    if "(" in previous and "(" not in current:
        return ErrorClass.DISTRIBUTION
    if _digits(previous) != _digits(current) and len(_digits(previous)) == len(_digits(current)):
        return ErrorClass.ARITHMETIC
    if previous.count("=") == current.count("=") == 1:
        left_before = previous.split("=")[0]
        left_after = current.split("=")[0]
        if len(left_after) < len(left_before):
            return ErrorClass.TRANSPOSITION
    return ErrorClass.UNKNOWN


def _digits(text: str) -> list[str]:
    return [c for c in text if c.isdigit()]
