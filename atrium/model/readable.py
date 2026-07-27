"""Readable state: the 120-word description regenerated at session end. SPEC.md §8.2.

The primary artefact for a human — teacher, tutor, parent, or the learner. It is also the
compression that carries months of history into a prompt without carrying months of transcript.

Two rules it must obey, both enforced here rather than asked for in the prompt:

* **120 words, hard.** Truncated at a sentence boundary if the model overruns.
* **Nothing that is not in the ledger.** The prompt is built only from claim levels, error classes,
  and representation weights. A readable state that says something flattering the evidence does not
  support is worse than no readable state, because a human will act on it.
"""

from __future__ import annotations

import re
from typing import Final

from pydantic import BaseModel

from ..llm import LLM
from .representations import RepresentationPreferences
from .skills import ClaimLevel, SkillView
from .struggle import StruggleEntry

WORD_CAP: Final = 120

_SYSTEM: Final = """You write a short description of what a learner can currently do, for a human
who has not watched the sessions.

Rules:
- At most 120 words. Prose, no bullets, no headings.
- Only say what the supplied evidence supports. Do not infer, encourage, or soften.
- Name specific recurring errors plainly. "Reliably drops a sign when a negative term crosses the
  equals" is useful; "sometimes makes small mistakes" is not.
- If a representation gets them unstuck faster, say so.
- Say what they have not met yet, if you know.
- No praise, no advice, no next steps. This is a description, not a report card."""


class ReadableState(BaseModel):
    learner_id: str
    text: str
    word_count: int

    @property
    def within_cap(self) -> bool:
        return self.word_count <= WORD_CAP


class Summary(BaseModel):
    text: str


def cap_words(text: str, cap: int = WORD_CAP) -> str:
    """Truncate at a sentence boundary rather than mid-clause."""
    words = text.split()
    if len(words) <= cap:
        return text.strip()
    truncated = " ".join(words[:cap])
    sentences = re.split(r"(?<=[.!?])\s+", truncated)
    if len(sentences) > 1:
        return " ".join(sentences[:-1]).strip()
    return truncated.rstrip(",;:") + "."


def build_prompt(
    skills: list[SkillView],
    struggles: list[StruggleEntry],
    preferences: RepresentationPreferences | None,
) -> str:
    parts: list[str] = []

    for level, label in (
        (ClaimLevel.SECURE, "Secure"),
        (ClaimLevel.EMERGING, "Emerging"),
        (ClaimLevel.NOT_EVIDENCED, "Not yet evidenced"),
    ):
        named = [s.skill_id for s in skills if s.level is level]
        if named:
            parts.append(f"{label}: {', '.join(named)}")

    recurring: dict[str, int] = {}
    for entry in struggles:
        key = entry.error_class.value
        recurring[key] = recurring.get(key, 0) + 1
    if recurring:
        ranked = sorted(recurring.items(), key=lambda kv: -kv[1])
        parts.append(
            "Recurring errors: "
            + ", ".join(f"{name} ({count}x)" for name, count in ranked if count > 1)
        )

    if preferences is not None:
        seen = {
            name: round(weight, 2)
            for name, weight in preferences.weights.items()
            if preferences.evidence_for(name)  # type: ignore[arg-type]
        }
        if seen:
            parts.append(f"Unstuck rate by representation: {seen}")

    unresolved = [e.topic_id for e in struggles if not e.resolved]
    if unresolved:
        parts.append(f"Left unresolved: {', '.join(sorted(set(unresolved)))}")

    return "\n".join(parts) if parts else "No evidence yet."


def generate(
    learner_id: str,
    skills: list[SkillView],
    struggles: list[StruggleEntry],
    preferences: RepresentationPreferences | None = None,
    llm: LLM | None = None,
) -> ReadableState:
    prompt = build_prompt(skills, struggles, preferences)
    if prompt == "No evidence yet.":
        return ReadableState(
            learner_id=learner_id, text="No sessions yet.", word_count=3
        )

    try:
        summary = (llm or LLM()).structured(
            system=_SYSTEM, prompt=prompt, schema=Summary, max_tokens=400
        )
        text = cap_words(summary.text)
    except Exception:  # noqa: BLE001 - a missing summary must not lose the session's evidence
        text = _fallback(skills, struggles)

    return ReadableState(learner_id=learner_id, text=text, word_count=len(text.split()))


def _fallback(skills: list[SkillView], struggles: list[StruggleEntry]) -> str:
    """Deterministic prose when the model is unavailable. Duller, still true."""
    secure = [s.skill_id for s in skills if s.level is ClaimLevel.SECURE]
    emerging = [s.skill_id for s in skills if s.level is ClaimLevel.EMERGING]
    bits: list[str] = []
    if secure:
        bits.append(f"Secure on {', '.join(secure)}.")
    if emerging:
        bits.append(f"Emerging on {', '.join(emerging)}.")
    unresolved = sorted({e.topic_id for e in struggles if not e.resolved})
    if unresolved:
        bits.append(f"Left unresolved: {', '.join(unresolved)}.")
    return cap_words(" ".join(bits) or "No evidence yet.")
