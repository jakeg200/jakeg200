"""Persistence model.

The schema encodes two commitments that the rest of the system depends on:

1. A Verification carries its *tier* and may say "unverifiable". Absence of proof is
   recorded as absence of proof, never as a negative judgement.
2. An Attempt carries its assistance *mode*, and only unassisted attempts may raise a
   Claim level. That rule lives in warrant/records/claims.py but it is meaningless
   without this column, so the column is not nullable and has no default.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import JSON, Column, Text, UniqueConstraint
from sqlmodel import Field, SQLModel

AssistanceMode = Literal["unassisted", "assisted", "unknown"]
StepKind = Literal["algebraic", "inference", "definition", "assertion", "restatement"]
VerificationStatus = Literal["valid", "invalid", "unverifiable"]
ClaimLevel = Literal["not_evidenced", "emerging", "secure"]


def new_id() -> str:
    return uuid.uuid4().hex


def utcnow() -> datetime:
    return datetime.now(UTC)


def json_field(default: Any = None) -> Any:
    return Field(
        default_factory=list if default is None else lambda: default, sa_column=Column(JSON)
    )


class Learner(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    handle: str = Field(index=True, unique=True)
    created_at: datetime = Field(default_factory=utcnow)


class Skill(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    code: str = Field(index=True, unique=True)
    name: str
    domain: str = "maths"
    prerequisite_ids: list[str] = json_field()


class Task(SQLModel, table=True):
    id: str = Field(primary_key=True)
    domain: str = "maths"
    statement: str = Field(sa_column=Column(Text))
    notation: str = "text"
    canonical_answer: str = ""
    skill_ids: list[str] = json_field()
    difficulty_b: float = 0.0


class Attempt(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    learner_id: str = Field(index=True, foreign_key="learner.id")
    task_id: str = Field(index=True, foreign_key="task.id")
    mode: str
    # Mode is self-declared behind an explicit attestation (SPEC section 13). We record
    # what the learner attested to so the record page can say so rather than imply more.
    mode_source: str = "self_declared"
    raw_text: str = Field(sa_column=Column(Text))
    submitted_at: datetime = Field(default_factory=utcnow)
    elapsed_ms: int = 0


class Step(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    attempt_id: str = Field(index=True, foreign_key="attempt.id")
    index: int
    raw_text: str = Field(sa_column=Column(Text))
    kind: str
    formalised: str | None = None
    formaliser_confidence: float | None = None


class Verification(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    step_id: str = Field(index=True, foreign_key="step.id")
    tier: int
    status: str
    evidence: str = Field(default="", sa_column=Column(Text))
    confidence: float | None = None
    latency_ms: int = 0


class Diagnosis(SQLModel, table=True):
    attempt_id: str = Field(primary_key=True, foreign_key="attempt.id")
    first_break_index: int | None = None
    error_class: str = "none"
    misconception_id: str | None = None
    confidence: float = 0.0
    summary: str = Field(default="", sa_column=Column(Text))
    probe: str = Field(default="", sa_column=Column(Text))


class Claim(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("learner_id", "skill_id", name="uq_claim_learner_skill"),)

    id: str = Field(default_factory=new_id, primary_key=True)
    learner_id: str = Field(index=True, foreign_key="learner.id")
    skill_id: str = Field(index=True, foreign_key="skill.id")
    level: str = "not_evidenced"
    n_unassisted: int = 0
    n_assisted: int = 0
    last_evidence_attempt_id: str | None = None
    first_evidence_at: datetime | None = None
    last_evidence_at: datetime | None = None
    evidence_task_ids: list[str] = json_field()
    evidence_attempt_ids: list[str] = json_field()
    updated_at: datetime = Field(default_factory=utcnow)
