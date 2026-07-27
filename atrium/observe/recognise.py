"""Reading the canvas. SPEC.md §5.

Not live stroke-level recognition — that is a research project and it is not the one we are doing.
The loop is: buffer strokes, wait for a stroke-idle boundary, snapshot the region, ask a vision
model for a structured reading of the *whole affected region*, then diff against the previous
reading to produce events.

The diff is the point. A full re-read every 900ms tells you what is on the canvas; the diff tells
you what the learner just *did*, which is what the policy actually consumes. Erasures and
strike-throughs come out of the diff as first-class events, and repeated erasure of one line is
the strongest stall signal in the system (§5).

`Recogniser` is the seam. MathPix is the fallback if vision accuracy on handwriting proves
inadequate; swapping it must not touch anything outside this file.
"""

from __future__ import annotations

from enum import Enum
from typing import Protocol

from pydantic import BaseModel, Field

from ..llm import LLM, VISION_MODEL


class BBox(BaseModel):
    x: float
    y: float
    w: float
    h: float

    def overlaps(self, other: BBox, pad: float = 8.0) -> bool:
        return not (
            self.x + self.w + pad < other.x
            or other.x + other.w + pad < self.x
            or self.y + self.h + pad < other.y
            or other.y + other.h + pad < self.y
        )


class RecognisedLine(BaseModel):
    latex: str
    bbox: BBox | None = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    is_new: bool = False
    is_struck_through: bool = False


class Reading(BaseModel):
    lines: list[RecognisedLine] = Field(default_factory=list)


class CanvasEventType(str, Enum):
    LINE_ADDED = "line_added"
    LINE_EDITED = "line_edited"
    LINE_ERASED = "line_erased"
    LINE_STRUCK_THROUGH = "line_struck_through"


class CanvasEvent(BaseModel):
    type: CanvasEventType
    line_index: int
    latex: str = ""
    previous_latex: str = ""


class Recogniser(Protocol):
    def read(self, png: bytes, previous: Reading) -> Reading: ...


_SYSTEM = """You are reading a region of a learner's handwritten mathematical working.

Return one entry per line of working, top to bottom. Transcribe what is actually written, not what
you think it should say — a learner's error is the most important thing on the page and silently
correcting it destroys the signal this whole system runs on. If a line reads 3x = 31, return
3x = 31.

Mark `is_struck_through` for anything crossed out; keep it in the list rather than dropping it.
Set `confidence` below 0.5 for anything you are guessing at.

You are given the previous reading. Use it for consistency of notation only — if a line is
unchanged, transcribe it the same way you did before. Do not carry over a line that is no longer
on the canvas."""


class VisionRecogniser:
    """The default. Anthropic vision, structured output, via `llm.py` so it replays in evals."""

    def __init__(self, llm: LLM | None = None) -> None:
        self.llm = llm or LLM(model=VISION_MODEL)

    def read(self, png: bytes, previous: Reading) -> Reading:
        prior = "\n".join(f"{i}: {ln.latex}" for i, ln in enumerate(previous.lines)) or "(empty)"
        return self.llm.structured(
            system=_SYSTEM,
            prompt=f"Previous reading:\n{prior}\n\nRead the attached region.",
            schema=Reading,
            images=[png],
            max_tokens=1500,
        )


class NullRecogniser:
    """Returns the previous reading unchanged. Used by tests and by the M0 runtime, which has a
    canvas but no recognition yet."""

    def read(self, png: bytes, previous: Reading) -> Reading:  # noqa: ARG002
        return previous


# --- diffing --------------------------------------------------------------------------------


def _normalise(latex: str) -> str:
    """Cosmetic differences that must not register as an edit."""
    out = latex.strip().replace(" ", "").replace(r"\,", "").replace(r"\ ", "")
    out = out.replace(r"\cdot", "*").replace(r"\times", "*").replace("{", "").replace("}", "")
    return out.replace(r"\left", "").replace(r"\right", "")


def diff(previous: Reading, current: Reading) -> list[CanvasEvent]:
    """Produce events, not a full re-read.

    Lines are matched by position in the list rather than by content, because a learner editing
    line 2 should read as `line_edited` at index 2 — not as an erase of the old line 2 and an add
    of a new one. Trailing lines that disappear are erasures.
    """
    events: list[CanvasEvent] = []
    prev_lines, curr_lines = previous.lines, current.lines

    for i, curr in enumerate(curr_lines):
        if i >= len(prev_lines):
            events.append(
                CanvasEvent(type=CanvasEventType.LINE_ADDED, line_index=i, latex=curr.latex)
            )
            continue
        prev = prev_lines[i]
        if curr.is_struck_through and not prev.is_struck_through:
            events.append(
                CanvasEvent(
                    type=CanvasEventType.LINE_STRUCK_THROUGH, line_index=i, latex=curr.latex
                )
            )
            continue
        if _normalise(prev.latex) != _normalise(curr.latex):
            events.append(
                CanvasEvent(
                    type=CanvasEventType.LINE_EDITED,
                    line_index=i,
                    latex=curr.latex,
                    previous_latex=prev.latex,
                )
            )

    for i in range(len(curr_lines), len(prev_lines)):
        events.append(
            CanvasEvent(
                type=CanvasEventType.LINE_ERASED,
                line_index=i,
                previous_latex=prev_lines[i].latex,
            )
        )
    return events
