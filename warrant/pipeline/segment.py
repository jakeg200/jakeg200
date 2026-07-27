"""Splitting a person's working into atomic steps.

The hard constraint: `raw_text` is a verbatim slice of what the learner wrote. Not
tidied, not renotated, not spell-corrected. If we repair a typo before verifying, we are
no longer assessing their reasoning, and the moment we show the step back to them it
will not be the sentence they wrote.

The model does this when it is available; a deterministic splitter does it when it is
not, and the model's output is rejected outright if it fails the verbatim check.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal, cast

from pydantic import BaseModel

from warrant import llm
from warrant.verify.base import StepKind
from warrant.verify.mathparse import parse

# Connectives that separate one move from the next. Consumed, not kept: "so 4x = 12"
# is the step "4x = 12".
SEPARATORS = re.compile(
    r"(?:\s*\n+\s*"
    r"|\s*;\s*"
    r"|(?<=[.!?])\s+"
    r"|\s*,?\s+(?:so|then|therefore|hence|thus|next|finally|giving|"
    r"which\s+gives|so\s+that|leaving|leaves)\b\s*"
    r"|\s*,\s*)",
    re.IGNORECASE,
)

# A connective at the head of a fragment belongs to the join, not to the step. Removing
# it leaves the step a contiguous verbatim slice of what the learner wrote.
LEADING_CONNECTIVE = re.compile(
    r"^(?:and|so|then|therefore|hence|thus|next|finally|now|which\s+gives|giving)\b[\s,]*",
    re.IGNORECASE,
)

DEFINITION = re.compile(r"^\s*(let|define|set|call|write)\b", re.IGNORECASE)
ASSERTION = re.compile(
    r"\b(the\s+)?(answer|solution|result)\b|\bx\s*(=|is)\b.*\b(is\s+the\s+answer)\b",
    re.IGNORECASE,
)
INFERENCE = re.compile(
    r"\b(because|since|as|it\s+follows|must\s+be|implies|means\s+that|by\b.*\brule|"
    r"substituting|substitute|checking|check)\b",
    re.IGNORECASE,
)

SYSTEM = """You split a person's mathematical working into atomic steps.

Absolute rules:
- Every step's text must be an exact, contiguous substring of the input. Copy characters \
verbatim. Do not fix spelling, do not standardise notation, do not insert symbols the \
person did not write, do not reorder.
- One step is one move: one rearrangement, one calculation, one claim.
- Do not add steps the person did not write, and do not merge two moves into one step.
- Do not judge whether any step is correct. That is not your job here.

Classify each step:
- algebraic: a manipulation or a stated equation or expression
- inference: a claim that something follows, including substitution checks
- definition: introducing or naming something
- assertion: stating an answer or result without working
- restatement: repeating or paraphrasing something already present
"""


class SegmentedStep(BaseModel):
    raw_text: str
    kind: Literal["algebraic", "inference", "definition", "assertion", "restatement"]


class Segmentation(BaseModel):
    steps: list[SegmentedStep]


@dataclass(frozen=True)
class Segment:
    index: int
    raw_text: str
    kind: StepKind


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def classify(text: str) -> StepKind:
    if DEFINITION.search(text):
        return "definition"
    form = parse(text)
    mathematical = form.ok
    if ASSERTION.search(text) and not mathematical:
        return "assertion"
    if ASSERTION.search(text) and mathematical and not INFERENCE.search(text):
        return "assertion"
    if mathematical and not INFERENCE.search(text):
        return "algebraic"
    if INFERENCE.search(text):
        return "inference"
    if mathematical:
        return "algebraic"
    return "restatement"


def _split_conjunctions(fragment: str) -> list[str]:
    """Split "4x = 8 and x = 2" but not "3 and 4"."""
    parts = re.split(r"\s+and\s+", fragment, flags=re.IGNORECASE)
    if len(parts) < 2:
        return [fragment]
    if all(parse(part).ok for part in parts):
        return [p for p in (part.strip() for part in parts) if p]
    return [fragment]


def deterministic_segments(raw_text: str) -> list[Segment]:
    """The offline splitter. Fully determined by the input, so CI is reproducible."""
    fragments: list[str] = []
    for chunk in SEPARATORS.split(raw_text):
        if chunk is None:
            continue
        stripped = chunk.strip()
        if not stripped:
            continue
        fragments.extend(_split_conjunctions(stripped))

    steps: list[Segment] = []
    for fragment in fragments:
        text = LEADING_CONNECTIVE.sub("", fragment.strip()).strip().strip(",;")
        if not text:
            continue
        steps.append(Segment(index=len(steps), raw_text=text, kind=classify(text)))
    return steps


def _verbatim(steps: list[SegmentedStep], raw_text: str) -> bool:
    haystack = _normalise(raw_text)
    return all(_normalise(step.raw_text) in haystack for step in steps if step.raw_text.strip())


def segment(raw_text: str, statement: str = "") -> list[Segment]:
    """Split working into steps, preferring the model and checking its work."""
    result = llm.complete(
        purpose="segment",
        system=SYSTEM,
        prompt=f"Task: {statement}\n\nWorking:\n{raw_text}",
        schema=Segmentation,
    )
    if result is not None and result.steps and _verbatim(result.steps, raw_text):
        return [
            Segment(index=i, raw_text=s.raw_text.strip(), kind=cast(StepKind, s.kind))
            for i, s in enumerate(result.steps)
            if s.raw_text.strip()
        ]
    return deterministic_segments(raw_text)
