from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class LearnerIn(BaseModel):
    handle: str = Field(min_length=1, max_length=64)


class LearnerOut(BaseModel):
    id: str
    handle: str
    created_at: datetime


class TaskOut(BaseModel):
    id: str
    domain: str
    statement: str
    notation: str
    skill_ids: list[str]
    difficulty_b: float


class AttemptIn(BaseModel):
    learner_id: str
    task_id: str
    raw_text: str = Field(min_length=1)
    # No default. Mode is self-declared, and a default would be us declaring it for them.
    mode: Literal["unassisted", "assisted", "unknown"]
    attested: bool = False
    elapsed_ms: int = 0


class StepOut(BaseModel):
    index: int
    raw_text: str
    kind: str
    status: str
    tier: int
    evidence: str
    confidence: float | None = None
    derives: bool = False


class DiagnosisOut(BaseModel):
    first_break_index: int | None
    error_class: str
    misconception_id: str | None
    misconception_name: str | None
    confidence: float
    summary: str
    derivation_present: bool


class AttemptOut(BaseModel):
    id: str
    learner_id: str
    task_id: str
    statement: str
    mode: str
    mode_source: str
    submitted_at: datetime
    steps: list[StepOut]
    diagnosis: DiagnosisOut
    probe: str
    coverage: dict[str, Any]
    claims_updated: list[dict[str, Any]] = []
