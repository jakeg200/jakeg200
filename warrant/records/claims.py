"""Claims: what we are prepared to say about a person, and what it took to say it.

The rules, in one place because they are the product:

* Evidence counts only if the derivation was **valid** (no break) and was actually a
  **derivation** (not an answer stated and checked).
* Only an **unassisted** attempt may raise a level. Assisted attempts are counted, shown,
  and never promote. That gap between the two counts is the learning-debt instrument;
  softening it would make the record mean nothing.
* `secure` needs three unassisted derivations, across at least two distinct tasks, spread
  over at least seven days. Three in one sitting is fluency with a worked example, not a
  secure skill.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlmodel import Session, select

from warrant.config import settings
from warrant.models import Attempt, Claim, ClaimLevel, Task, utcnow
from warrant.pipeline.run import AttemptAnalysis


@dataclass(frozen=True)
class Evidence:
    """Whether an attempt is admissible as evidence, and why not when it is not."""

    valid: bool
    derivation: bool
    reason: str

    @property
    def admissible(self) -> bool:
        return self.valid and self.derivation


def assess_evidence(analysis: AttemptAnalysis) -> Evidence:
    diagnosis = analysis.diagnosis
    if diagnosis.first_break_index is not None:
        return Evidence(False, diagnosis.derivation_present, "the chain has a break")
    if not diagnosis.derivation_present:
        return Evidence(True, False, "nothing was derived: the answer was stated or checked")
    return Evidence(True, True, "a complete derivation with no break")


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def level_for(claim: Claim, now: datetime | None = None) -> ClaimLevel:
    """Recompute a claim's level from its evidence. Pure, so it can be tested directly."""
    if claim.n_unassisted <= 0:
        return "not_evidenced"

    distinct_tasks = len(set(claim.evidence_task_ids))
    first = _aware(claim.first_evidence_at)
    last = _aware(claim.last_evidence_at)
    spaced = bool(first and last and (last - first) >= timedelta(days=settings.secure_spacing_days))

    if (
        claim.n_unassisted >= settings.secure_threshold
        and distinct_tasks >= settings.secure_min_distinct_tasks
        and spaced
    ):
        return "secure"
    return "emerging"


def _claim_for(session: Session, learner_id: str, skill_id: str) -> Claim:
    claim = session.exec(
        select(Claim).where(Claim.learner_id == learner_id, Claim.skill_id == skill_id)
    ).first()
    if claim is None:
        claim = Claim(learner_id=learner_id, skill_id=skill_id)
        session.add(claim)
    return claim


def update_claims(
    session: Session,
    attempt: Attempt,
    task: Task,
    analysis: AttemptAnalysis,
) -> list[Claim]:
    evidence = assess_evidence(analysis)
    now = utcnow()
    updated: list[Claim] = []

    for skill_id in task.skill_ids:
        claim = _claim_for(session, attempt.learner_id, skill_id)

        if evidence.admissible:
            if attempt.mode == "unassisted":
                claim.n_unassisted += 1
                claim.evidence_task_ids = [*claim.evidence_task_ids, task.id]
                claim.evidence_attempt_ids = [*claim.evidence_attempt_ids, attempt.id]
                claim.last_evidence_attempt_id = attempt.id
                if claim.first_evidence_at is None:
                    claim.first_evidence_at = attempt.submitted_at
                claim.last_evidence_at = attempt.submitted_at
                claim.level = level_for(claim, now)
            else:
                # Recorded, visible, and deliberately inert.
                claim.n_assisted += 1

        claim.updated_at = now
        session.add(claim)
        updated.append(claim)

    session.commit()
    for claim in updated:
        session.refresh(claim)
    return updated
