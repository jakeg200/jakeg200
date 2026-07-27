"""One question, generated from the diagnosis, that does not give the answer away.

The probe is the only thing the system says to a learner about their error, and it is
deliberately a question. A statement would do the reasoning for them; a question makes
them do it. Every probe is checked for answer leakage before it leaves this module, and
a probe that leaks is discarded rather than repaired — the taxonomy's own question is
always available as a safe fallback.
"""

from __future__ import annotations

from pydantic import BaseModel

from warrant import llm, taxonomy
from warrant.pipeline import leakage
from warrant.pipeline.diagnose import DiagnosisResult

SYSTEM = """You write a single Socratic question for somebody who has made a specific \
mistake in their mathematical working.

Hard rules:
- One question. No preamble, no praise, no explanation of the error.
- Never state the answer to the problem, in any notation, in any form, and never state \
the corrected line. If your question would let them read the answer off it, write a \
different question.
- Do not tell them what to do next. Ask them something that makes them look at the step \
again.
- Speak plainly. No jargon they have not used themselves.
"""


class ProbeText(BaseModel):
    question: str


def probe(
    diagnosis: DiagnosisResult,
    step_text: str | None = None,
    statement: str = "",
    canonical_answer: str = "",
) -> str:
    """Generate the probe. Falls back to the taxonomy's question whenever it must."""
    if diagnosis.first_break_index is None and diagnosis.error_class == "none":
        return ""

    fallback = taxonomy.get(diagnosis.misconception_id).probe or taxonomy.GENERIC_PROBE
    if leakage.leaks(fallback, canonical_answer):  # pragma: no cover - taxonomy is static
        fallback = taxonomy.GENERIC_PROBE

    misconception = taxonomy.get(diagnosis.misconception_id)
    generated = llm.complete(
        purpose="probe",
        system=SYSTEM,
        prompt=(
            f"Task: {statement}\n"
            f"The line they wrote: {step_text or '(unknown)'}\n"
            f"What went wrong: {misconception.description}\n"
            f"Our summary: {diagnosis.summary}\n\n"
            "Write the question."
        ),
        schema=ProbeText,
    )

    if generated is None:
        return fallback

    question = generated.question.strip()
    if not question or leakage.leaks(question, canonical_answer):
        return fallback
    return question


def is_safe(text: str, canonical_answer: str) -> bool:
    """Used by the adversarial test in the eval harness."""
    return not leakage.leaks(text, canonical_answer)
