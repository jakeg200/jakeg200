"""The pipeline's behavioural commitments, including the three demo moments."""

from __future__ import annotations

from warrant.pipeline.diagnose import attribute_break, has_derivation
from warrant.pipeline.leakage import leaks, redact
from warrant.pipeline.run import analyse
from warrant.pipeline.segment import deterministic_segments

SEVEN = "Solve 7x - 2 = 3x + 10"
ANSWER = "x = 3"


def test_segmentation_is_verbatim() -> None:
    text = "7x take away 3x is 4x, and -2 add 10 is 8, so 4x = 8"
    for step in deterministic_segments(text):
        assert step.raw_text in text


def test_segmentation_does_not_repair_notation() -> None:
    text = "4x  =  12\nx=3"
    steps = deterministic_segments(text)
    assert steps[0].raw_text == "4x  =  12"
    assert steps[1].raw_text == "x=3"


# -- demo moment 1: a sign error at step two ---------------------------------


def test_locates_the_break_and_names_it() -> None:
    analysis = analyse(
        "7x take away 3x is 4x, and -2 add 10 is 8, so 4x = 8 and x = 2", SEVEN, ANSWER
    )
    assert analysis.diagnosis.first_break_index == 1
    assert analysis.diagnosis.error_class == "sign_error_across_equals"
    assert analysis.probe
    assert not leaks(analysis.probe, ANSWER)
    assert not leaks(analysis.diagnosis.summary, ANSWER)


def test_reasoning_after_a_slip_is_judged_from_where_they_are() -> None:
    """One slip then perfect reasoning should be reported as exactly that."""
    analysis = analyse("4x + 5 = 17\n4x = 22\nx = 5.5", "Solve 4x + 5 = 17", "x = 3")
    statuses = [s.verification.status for s in analysis.steps]
    assert statuses == ["valid", "invalid", "valid"]
    assert analysis.diagnosis.first_break_index == 1


# -- demo moment 2: a correct derivation in an unusual order -----------------


def test_correct_but_unusual_order_marks_nothing() -> None:
    for text in [
        "7x - 3x = 10 + 2\n4x = 12\nx = 3",
        "7 - 3 = 4 and 10 + 2 = 12\n4x = 12\nx = 3",
        "7x - 2 = 3x + 10\nsubtract 3x from both sides\n4x - 2 = 10\n4x = 12\nx = 3",
    ]:
        analysis = analyse(text, SEVEN, ANSWER)
        assert analysis.diagnosis.first_break_index is None, text
        assert analysis.probe == ""


def test_decimal_and_fraction_are_the_same_answer() -> None:
    analysis = analyse("4x + 5 = 17\n4x = 12\nx = 12/4", "Solve 4x + 5 = 17", "x = 3")
    assert analysis.diagnosis.first_break_index is None


# -- demo moment 3: checking is not deriving ---------------------------------


def test_asserted_answer_verifies_but_derives_nothing() -> None:
    analysis = analyse("the answer is x = 3, substituting gives 19 = 19", SEVEN, ANSWER)
    assert analysis.diagnosis.first_break_index is None
    assert all(s.verification.status == "valid" for s in analysis.steps)
    assert analysis.diagnosis.derivation_present is False
    assert analysis.diagnosis.error_class == "no_derivation"


def test_a_real_derivation_does_derive() -> None:
    analysis = analyse("7x - 2 = 3x + 10\n4x = 12\nx = 3", SEVEN, ANSWER)
    assert analysis.diagnosis.derivation_present is True


def test_has_derivation_ignores_closed_identities() -> None:
    analysis = analyse("19 = 19", SEVEN, ANSWER)
    assert has_derivation(analysis.verifications) is False


# -- abstention --------------------------------------------------------------


def test_unverifiable_steps_do_not_break_the_chain() -> None:
    analysis = analyse("7x - 2 = 3x + 10\nnow I do the clever bit\n4x = 12\nx = 3", SEVEN, ANSWER)
    statuses = [s.verification.status for s in analysis.steps]
    assert "unverifiable" in statuses
    assert analysis.diagnosis.first_break_index is None


# -- blame attribution -------------------------------------------------------


def test_attribution_never_invents_a_break() -> None:
    """Attribution may only move an existing break earlier, never create one."""
    analysis = analyse(
        "7x take away 3x is 4x, and -2 add 10 is 8, so 4x = 8 and x = 2", SEVEN, ANSWER
    )
    proved_at = int(analysis.diagnosis.detail["proved_at_index"])
    attributed = int(analysis.diagnosis.detail["attributed_to_index"])
    assert attributed <= proved_at
    assert analysis.steps[proved_at].verification.status == "invalid"


def test_attribution_stops_at_a_real_chain_move() -> None:
    views = [s.view for s in analyse("4x + 5 = 17\n4x = 22\nx = 5.5", "Solve 4x + 5 = 17").steps]
    results = [
        s.verification for s in analyse("4x + 5 = 17\n4x = 22\nx = 5.5", "Solve 4x + 5 = 17").steps
    ]
    assert attribute_break(1, views, results) == 1


# -- leakage -----------------------------------------------------------------


def test_leakage_catches_many_notations() -> None:
    for text in [
        "x = 3",
        "x=3",
        "so x is 3",
        "3 = x",
        "the answer is 3",
        "x is three",
        "$x = 3$",
        "x -> 3",
        "the solution is 3",
    ]:
        assert leaks(text, "x = 3"), text


def test_leakage_permits_ordinary_arithmetic_mentions() -> None:
    for text in [
        "What do you get if you divide both sides by 4?",
        "There are 3 terms on the left.",
        "Try substituting a value and see.",
    ]:
        assert not leaks(text, "x = 3"), text


def test_redaction_keeps_the_rest_of_the_sentence() -> None:
    out = redact("x = 3 satisfies '7x - 2 = 3x + 10' but not '4x = 8'", "x = 3")
    assert "x = 3 satisfies" not in out
    assert "4x = 8" in out
