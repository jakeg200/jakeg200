"""Recognition accuracy. SPEC.md §10.

Line-level exact match, and **structural match ignoring cosmetic differences**. Target > 92%
structural on your own cohort's handwriting.

Structural match is the number to optimise. `3x` and `3 \cdot x` and `3\,x` are the same line of
working; a system that scores them as misses will send you chasing formatting instead of reading.
Exact match is reported alongside because a collapsing gap between the two means the recogniser has
started normalising away things that matter.

Fixtures are images of real handwriting with hand-typed ground truth, so they live outside the
repo. M1's acceptance test is a human writing five lines and looking at the result; this is how
that becomes a number once there are enough of them.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from pydantic import BaseModel

FIXTURES = Path(__file__).parent / "fixtures"
STRUCTURAL_TARGET = 0.92


class Sample(BaseModel):
    id: str
    image: str  # path relative to FIXTURES
    truth: list[str]  # one LaTeX string per line of working


class RecognitionScore(BaseModel):
    lines: int = 0
    exact: int = 0
    structural: int = 0

    @property
    def exact_rate(self) -> float:
        return self.exact / self.lines if self.lines else 0.0

    @property
    def structural_rate(self) -> float:
        return self.structural / self.lines if self.lines else 0.0


_COSMETIC = (
    (r"\left", ""),
    (r"\right", ""),
    (r"\,", ""),
    (r"\;", ""),
    (r"\!", ""),
    # Multiplication is implicit in handwriting. `3x`, `3 \cdot x` and `3 \times x` are one line
    # written three ways, so the operator dissolves rather than normalising to a symbol.
    (r"\cdot", ""),
    (r"\times", ""),
    ("*", ""),
    ("{", ""),
    ("}", ""),
    (" ", ""),
)


def structural(latex: str) -> str:
    """Strip the differences that do not change what the line says."""
    out = latex.strip()
    for old, new in _COSMETIC:
        out = out.replace(old, new)
    out = re.sub(r"\\frac(\w)(\w)", r"(\1/\2)", out)
    return out.lower()


def score_sample(truth: list[str], read: list[str]) -> RecognitionScore:
    """Line-aligned by position, which is how the diff in `observe/recognise.py` aligns them.

    A missing line counts against every line after it, and that is correct: a recogniser that
    drops line 2 has misread the working, not just one line of it.
    """
    score = RecognitionScore(lines=max(len(truth), len(read)))
    for index in range(min(len(truth), len(read))):
        if truth[index].strip() == read[index].strip():
            score.exact += 1
        if structural(truth[index]) == structural(read[index]):
            score.structural += 1
    return score


def load_samples(directory: Path = FIXTURES) -> list[Sample]:
    manifest = directory / "manifest.json"
    if not manifest.exists():
        return []
    return [Sample.model_validate(item) for item in json.loads(manifest.read_text("utf-8"))]
