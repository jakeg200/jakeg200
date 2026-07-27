"""The pipeline, end to end, with no database in sight.

Keeping this pure is what lets the eval harness run the real thing rather than a
lookalike. The API layer below it does nothing but persist what comes out.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field, replace

from warrant.pipeline.diagnose import DiagnosisResult, diagnose
from warrant.pipeline.formalise import formalise
from warrant.pipeline.probe import probe as make_probe
from warrant.pipeline.segment import Segment, segment
from warrant.verify.base import StepView, TaskContext, VerificationResult
from warrant.verify.ladder import VerifierLadder, tier_coverage
from warrant.verify.mathparse import carries_state, is_solved_form, parse


@dataclass
class AnalysedStep:
    view: StepView
    verification: VerificationResult


@dataclass
class AttemptAnalysis:
    statement: str
    steps: list[AnalysedStep]
    diagnosis: DiagnosisResult
    probe: str
    coverage: dict[str, float | int] = field(default_factory=dict)
    elapsed_ms: int = 0

    @property
    def views(self) -> list[StepView]:
        return [s.view for s in self.steps]

    @property
    def verifications(self) -> list[VerificationResult]:
        return [s.verification for s in self.steps]


def _mark_derivation(
    result: VerificationResult,
    kind: str,
    form: object,
    first_state_step: bool,
) -> VerificationResult:
    """Decide whether this step derived anything, as opposed to merely being true.

    Stating the answer is not deriving it, and neither is stating it and then checking
    it. If the very first line that carries the equation is already the solved form,
    nothing has been shown — however true it is. This is the distinction the whole
    capability record rests on, so it is applied here, once, for every step.
    """
    if result.detail.get("derives") != "yes":
        return result
    asserted = kind == "assertion" or (first_state_step and is_solved_form(form))  # type: ignore[arg-type]
    if not asserted:
        return result
    detail = dict(result.detail)
    detail["derives"] = "no"
    detail["asserted"] = "yes"
    return replace(result, detail=detail)


def analyse(
    raw_text: str,
    statement: str,
    canonical_answer: str = "",
    *,
    ladder: VerifierLadder | None = None,
    segments: list[Segment] | None = None,
) -> AttemptAnalysis:
    started = time.perf_counter()
    ladder = ladder or VerifierLadder()
    ctx = TaskContext(statement=statement)

    parts = segments if segments is not None else segment(raw_text, statement)

    analysed: list[AnalysedStep] = []
    previous: StepView | None = None
    # The line the next step has to follow from. This is the learner's most recent line
    # that actually carries the equation forward — not necessarily the line immediately
    # above, because people interleave working with true side remarks, and not the line
    # they *should* have written, because after a slip we keep assessing their reasoning
    # from where they actually are.
    antecedent: StepView | None = None
    first_state_step = True

    for part in parts:
        formalisation = formalise(part.raw_text, part.kind, previous.raw_text if previous else None)
        view = StepView(
            index=part.index,
            raw_text=part.raw_text,
            kind=part.kind,
            formalised=formalisation.formalised,
            formaliser_confidence=formalisation.confidence,
        )
        outcome = ladder.verify(antecedent, view, ctx)
        form = parse(part.raw_text)
        result = _mark_derivation(outcome.result, part.kind, form, first_state_step)

        analysed.append(AnalysedStep(view=view, verification=result))
        previous = view
        # A line that tier 1 read as a lemma or a piece of arithmetic is true but inert:
        # it must not become the line the next step is judged against, or we would be
        # checking the learner's algebra against their scratch working.
        inert = result.detail.get("reading") in ("lemma", "closed_identity")
        if carries_state(form) and not inert:
            antecedent = view
            first_state_step = False

    views = [a.view for a in analysed]
    results = [a.verification for a in analysed]

    diagnosis = diagnose(views, results, statement, canonical_answer)

    break_text = (
        views[diagnosis.first_break_index].raw_text
        if diagnosis.first_break_index is not None
        else None
    )
    probe_text = make_probe(diagnosis, break_text, statement, canonical_answer)

    return AttemptAnalysis(
        statement=statement,
        steps=analysed,
        diagnosis=diagnosis,
        probe=probe_text,
        coverage=tier_coverage(results),
        elapsed_ms=int((time.perf_counter() - started) * 1000),
    )
