"""Recognition accuracy eval. SPEC.md §10, M1 acceptance.

Skips until handwriting fixtures exist. The diffing logic — which is what turns a reading into the
events the policy consumes — is tested unconditionally, because it is pure and it is where M1's
"correctly identifies which line you just added" actually lives.
"""

from __future__ import annotations

import pytest

from atrium.observe.recognise import (
    CanvasEventType,
    Reading,
    RecognisedLine,
    diff,
)
from evals.recognition.score import (
    FIXTURES,
    STRUCTURAL_TARGET,
    RecognitionScore,
    load_samples,
    score_sample,
    structural,
)


def _reading(*latex: str) -> Reading:
    return Reading(lines=[RecognisedLine(latex=item) for item in latex])


def test_samples_present() -> None:
    if not load_samples():
        pytest.skip(f"no handwriting fixtures in {FIXTURES}")


def test_structural_accuracy() -> None:
    samples = load_samples()
    if not samples:
        pytest.skip("no handwriting fixtures yet")
    pytest.importorskip("anthropic")
    from atrium.observe.recognise import VisionRecogniser

    recogniser = VisionRecogniser()
    total = RecognitionScore()
    for sample in samples:
        png = (FIXTURES / sample.image).read_bytes()
        read = [line.latex for line in recogniser.read(png, Reading()).lines]
        score = score_sample(sample.truth, read)
        total = RecognitionScore(
            lines=total.lines + score.lines,
            exact=total.exact + score.exact,
            structural=total.structural + score.structural,
        )
    assert total.structural_rate >= STRUCTURAL_TARGET, (
        f"structural {total.structural_rate:.1%} < {STRUCTURAL_TARGET:.0%} "
        f"(exact {total.exact_rate:.1%})"
    )


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("3x", r"3 \cdot x"),
        ("3x", r"3\,x"),
        (r"\left(x+1\right)", "(x+1)"),
        ("2x + 6 = 14", "2x+6=14"),
        (r"\frac{x}{2}", "(x/2)"),
    ],
)
def test_cosmetic_differences_are_ignored(a: str, b: str) -> None:
    assert structural(a) == structural(b)


def test_diff_identifies_the_new_line() -> None:
    """M1's acceptance criterion, as a unit test."""
    before = _reading("3x + 8 = 23", "3x = 15")
    after = _reading("3x + 8 = 23", "3x = 15", "x = 5")
    events = diff(before, after)
    assert len(events) == 1
    assert events[0].type is CanvasEventType.LINE_ADDED
    assert events[0].line_index == 2
    assert events[0].latex == "x = 5"


def test_diff_reports_an_edit_not_an_erase_and_add() -> None:
    events = diff(_reading("3x = 31"), _reading("3x = 15"))
    assert [e.type for e in events] == [CanvasEventType.LINE_EDITED]
    assert events[0].previous_latex == "3x = 31"


def test_diff_ignores_cosmetic_rewrites() -> None:
    assert diff(_reading("3x + 8 = 23"), _reading(r"3x+8 = 23")) == []


def test_erasure_is_signal() -> None:
    """§5: erasures and strike-throughs are signal, not noise — they must survive the diff."""
    events = diff(_reading("3x = 15", "x = 3"), _reading("3x = 15"))
    assert [e.type for e in events] == [CanvasEventType.LINE_ERASED]
    assert events[0].previous_latex == "x = 3"


def test_strike_through_is_its_own_event() -> None:
    before = Reading(lines=[RecognisedLine(latex="x = 3")])
    after = Reading(lines=[RecognisedLine(latex="x = 3", is_struck_through=True)])
    events = diff(before, after)
    assert [e.type for e in events] == [CanvasEventType.LINE_STRUCK_THROUGH]
