"""Decay: a claim about a person is a claim about now.

A skill demonstrated three times last spring and never since is not a skill we can still
vouch for. `secure` falls back to `emerging` after ninety days without supporting
evidence. Nothing ever decays to `not_evidenced` — the evidence happened, and the record
keeps saying so.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlmodel import Session, select

from warrant.config import settings
from warrant.models import Claim, utcnow


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def is_stale(claim: Claim, now: datetime | None = None) -> bool:
    if claim.level != "secure":
        return False
    reference = _aware(claim.last_evidence_at) or _aware(claim.updated_at)
    if reference is None:
        return False
    return (now or utcnow()) - reference > timedelta(days=settings.decay_days)


def apply_decay(session: Session, now: datetime | None = None) -> list[Claim]:
    """Demote every stale claim. Safe to run repeatedly."""
    now = now or utcnow()
    decayed: list[Claim] = []
    for claim in session.exec(select(Claim).where(Claim.level == "secure")).all():
        if is_stale(claim, now):
            claim.level = "emerging"
            claim.updated_at = now
            session.add(claim)
            decayed.append(claim)
    if decayed:
        session.commit()
    return decayed
