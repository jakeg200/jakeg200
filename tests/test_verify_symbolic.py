"""Tier 1 must be right, and where it cannot be right it must be silent."""

from __future__ import annotations

import pytest

from warrant.verify.base import StepView, TaskContext
from warrant.verify.mathparse import parse, parse_statement
from warrant.verify.symbolic import SymbolicVerifier

TASK = TaskContext(statement="Solve 7x - 2 = 3x + 10")
verifier = SymbolicVerifier()


def check(prev: str | None, curr: str, ctx: TaskContext = TASK) -> str:
    previous = StepView(0, prev, "algebraic") if prev else None
    return verifier.verify(previous, StepView(1, curr, "algebraic"), ctx).status


@pytest.mark.parametrize(
    "prev,curr",
    [
        (None, "4x = 12"),
        ("4x = 12", "x = 3"),
        ("4x = 12", "x = 3.0"),
        ("4x = 22", "x = 5.5"),  # decimal against an exact rational
        (None, "7x - 3x = 10 + 2"),
        ("7x - 3x = 10 + 2", "4x = 12"),
        (None, "7x take away 3x is 4x"),  # a true lemma, not a chain move
        (None, "-2 add 10 is 8"),  # true arithmetic, in isolation
        ("x = 3", "7(3) - 2 = 19"),  # a check
    ],
)
def test_valid_moves(prev: str | None, curr: str) -> None:
    assert check(prev, curr) == "valid"


@pytest.mark.parametrize(
    "prev,curr",
    [
        (None, "4x = 8"),
        ("4x = 12", "x = 4"),
        (None, "7x - 3x = 5x"),
        (None, "7 - 2 = 3 + 10"),
    ],
)
def test_invalid_moves(prev: str | None, curr: str) -> None:
    assert check(prev, curr) == "invalid"


@pytest.mark.parametrize(
    "curr",
    [
        "subtract 3x from both sides",
        "multiply both sides by 2",
        "now do the same thing again",
        "x is less than 3",
        "",
    ],
)
def test_unparseable_steps_abstain(curr: str) -> None:
    """Not understanding a step is never evidence against the person who wrote it."""
    assert check(None, curr) == "unverifiable"


def test_notation_alone_never_produces_invalid() -> None:
    """The same claim in four notations must be settled the same way."""
    for text in ["x = 11/2", "x = 5.5", "x is 5.5", "x = 22/4"]:
        assert check("4x = 22", text) == "valid"


def test_evidence_names_a_witness() -> None:
    result = verifier.verify(None, StepView(1, "4x = 8", "algebraic"), TASK)
    assert result.status == "invalid"
    assert "satisfies" in result.evidence


def test_lemma_and_chain_readings_are_distinguished() -> None:
    lemma = verifier.verify(None, StepView(0, "7x - 3x = 4x", "algebraic"), TASK)
    move = verifier.verify(None, StepView(0, "4x = 12", "algebraic"), TASK)
    assert lemma.detail["reading"] == "lemma"
    assert lemma.detail["derives"] == "no"
    assert move.detail["reading"] == "chain_move"
    assert move.detail["derives"] == "yes"


def test_parser_refuses_english() -> None:
    for text in ["First I subtract 3x from both sides.", "then add 2 to both sides"]:
        assert not parse(text).ok


def test_statement_parsing_strips_the_instruction() -> None:
    form = parse_statement("Solve 7x - 2 = 3x + 10")
    assert form.kind == "equation"
    assert str(form.lhs) == "7*x - 2"
