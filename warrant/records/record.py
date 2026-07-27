"""Assembling the capability record.

Every claim carries links to the actual derivations that produced it. That is not a nice
extra: a credential whose evidence cannot be inspected is worth exactly as much as the
reader's trust in the issuer, which is what the current system already does badly.
"""

from __future__ import annotations

from typing import Any

from sqlmodel import Session, select

from warrant.models import Attempt, Claim, Learner, Skill, Task, utcnow
from warrant.records import sign
from warrant.records.decay import apply_decay


def build_record(session: Session, learner_id: str) -> dict[str, Any]:
    learner = session.get(Learner, learner_id)
    if learner is None:
        raise KeyError(learner_id)

    apply_decay(session)

    skills = {skill.id: skill for skill in session.exec(select(Skill)).all()}
    claims = session.exec(select(Claim).where(Claim.learner_id == learner_id)).all()
    claimed = {claim.skill_id for claim in claims}

    entries: list[dict[str, Any]] = []
    for claim in claims:
        skill = skills.get(claim.skill_id)
        entries.append(
            {
                "skill_id": claim.skill_id,
                "skill_code": skill.code if skill else claim.skill_id,
                "skill_name": skill.name if skill else "unknown skill",
                "level": claim.level,
                "unaided_demonstrations": claim.n_unassisted,
                "assisted_demonstrations": claim.n_assisted,
                "first_evidence_at": claim.first_evidence_at,
                "last_evidence_at": claim.last_evidence_at,
                "evidence": _evidence(session, claim),
            }
        )

    # A skill with no evidence is part of the record. Saying "we have never seen this"
    # is a claim, and a more useful one than silence.
    for skill_id, skill in skills.items():
        if skill_id not in claimed:
            entries.append(
                {
                    "skill_id": skill_id,
                    "skill_code": skill.code,
                    "skill_name": skill.name,
                    "level": "not_evidenced",
                    "unaided_demonstrations": 0,
                    "assisted_demonstrations": 0,
                    "first_evidence_at": None,
                    "last_evidence_at": None,
                    "evidence": [],
                }
            )

    order = {"secure": 0, "emerging": 1, "not_evidenced": 2}
    entries.sort(key=lambda e: (order[str(e["level"])], str(e["skill_code"])))

    payload: dict[str, Any] = {
        "learner": {"id": learner.id, "handle": learner.handle},
        "claims": entries,
        "generated_at": utcnow(),
        "mode_provenance": "self_declared",
        "notes": (
            "Levels are raised only by unassisted attempts. Assisted attempts are "
            "counted and shown but never promote. Assistance mode is declared by the "
            "learner at submission."
        ),
    }
    payload["signature"] = sign.sign(payload)
    return payload


def _evidence(session: Session, claim: Claim) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for attempt_id in claim.evidence_attempt_ids:
        attempt = session.get(Attempt, attempt_id)
        if attempt is None:
            continue
        task = session.get(Task, attempt.task_id)
        out.append(
            {
                "attempt_id": attempt.id,
                "task_id": attempt.task_id,
                "statement": task.statement if task else "",
                "mode": attempt.mode,
                "submitted_at": attempt.submitted_at,
                "href": f"/attempts/{attempt.id}",
            }
        )
    return out
