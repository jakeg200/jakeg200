from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlmodel import Session, select

from warrant.api.schemas import (
    AttemptIn,
    AttemptOut,
    DiagnosisOut,
    LearnerIn,
    LearnerOut,
    StepOut,
    TaskOut,
)
from warrant.db import get_session
from warrant.models import Attempt, Diagnosis, Learner, Step, Task, Verification
from warrant.pipeline import leakage
from warrant.pipeline.run import AttemptAnalysis, analyse
from warrant.records.claims import update_claims
from warrant.records.record import build_record
from warrant.records.render import render_record
from warrant.taxonomy import MISCONCEPTIONS

router = APIRouter()


@router.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/learners", response_model=LearnerOut)
def create_learner(body: LearnerIn, session: Session = Depends(get_session)) -> Learner:
    existing = session.exec(select(Learner).where(Learner.handle == body.handle)).first()
    if existing:
        return existing
    learner = Learner(handle=body.handle)
    session.add(learner)
    session.commit()
    session.refresh(learner)
    return learner


@router.get("/tasks", response_model=list[TaskOut])
def list_tasks(session: Session = Depends(get_session)) -> list[Task]:
    return list(session.exec(select(Task)).all())


@router.get("/tasks/{task_id}", response_model=TaskOut)
def get_task(task_id: str, session: Session = Depends(get_session)) -> Task:
    task = session.get(Task, task_id)
    if task is None:
        raise HTTPException(404, "no such task")
    return task


@router.post("/attempts", response_model=AttemptOut)
def create_attempt(body: AttemptIn, session: Session = Depends(get_session)) -> AttemptOut:
    learner = session.get(Learner, body.learner_id)
    if learner is None:
        raise HTTPException(404, "no such learner")
    task = session.get(Task, body.task_id)
    if task is None:
        raise HTTPException(404, "no such task")

    # The integrity gate. Claiming an unassisted attempt is an assertion the learner
    # makes deliberately; we will not infer it for them, and we will not let the client
    # send it by omission.
    if body.mode == "unassisted" and not body.attested:
        raise HTTPException(
            422,
            "an unassisted attempt must carry an explicit attestation that no assistance was used",
        )

    analysis = analyse(body.raw_text, task.statement, task.canonical_answer)

    attempt = Attempt(
        learner_id=learner.id,
        task_id=task.id,
        mode=body.mode,
        mode_source="self_declared",
        raw_text=body.raw_text,
        elapsed_ms=body.elapsed_ms,
    )
    session.add(attempt)
    session.commit()
    session.refresh(attempt)

    _persist_steps(session, attempt, analysis)
    claims = update_claims(session, attempt, task, analysis)

    return _attempt_out(
        attempt,
        task,
        analysis,
        [
            {
                "skill_id": c.skill_id,
                "level": c.level,
                "n_unassisted": c.n_unassisted,
                "n_assisted": c.n_assisted,
            }
            for c in claims
        ],
    )


@router.get("/attempts/{attempt_id}", response_model=AttemptOut)
def get_attempt(attempt_id: str, session: Session = Depends(get_session)) -> AttemptOut:
    attempt = session.get(Attempt, attempt_id)
    if attempt is None:
        raise HTTPException(404, "no such attempt")
    task = session.get(Task, attempt.task_id)
    if task is None:
        raise HTTPException(404, "the task behind this attempt is missing")

    steps = list(
        session.exec(select(Step).where(Step.attempt_id == attempt.id).order_by(Step.index)).all()
    )
    stored = session.get(Diagnosis, attempt.id)
    step_out: list[StepOut] = []
    for step in steps:
        verification = session.exec(
            select(Verification).where(Verification.step_id == step.id)
        ).first()
        step_out.append(
            StepOut(
                index=step.index,
                raw_text=step.raw_text,
                kind=step.kind,
                status=verification.status if verification else "unverifiable",
                tier=verification.tier if verification else 3,
                evidence=leakage.redact(
                    verification.evidence if verification else "", task.canonical_answer
                ),
                confidence=verification.confidence if verification else None,
            )
        )

    misconception = MISCONCEPTIONS.get(stored.misconception_id or "") if stored else None
    return AttemptOut(
        id=attempt.id,
        learner_id=attempt.learner_id,
        task_id=attempt.task_id,
        statement=task.statement,
        mode=attempt.mode,
        mode_source=attempt.mode_source,
        submitted_at=attempt.submitted_at,
        steps=step_out,
        diagnosis=DiagnosisOut(
            first_break_index=stored.first_break_index if stored else None,
            error_class=stored.error_class if stored else "none",
            misconception_id=stored.misconception_id if stored else None,
            misconception_name=misconception.name if misconception else None,
            confidence=stored.confidence if stored else 0.0,
            summary=stored.summary if stored else "",
            derivation_present=any(s.status == "valid" for s in step_out),
        ),
        probe=stored.probe if stored else "",
        coverage={},
    )


@router.get("/learners/{learner_id}/record")
def get_record(learner_id: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    try:
        return build_record(session, learner_id)
    except KeyError:
        raise HTTPException(404, "no such learner") from None


@router.get("/learners/{learner_id}/record.html", response_class=HTMLResponse)
def get_record_page(learner_id: str, session: Session = Depends(get_session)) -> HTMLResponse:
    try:
        record = build_record(session, learner_id)
    except KeyError:
        raise HTTPException(404, "no such learner") from None
    return HTMLResponse(render_record(record))


def _persist_steps(session: Session, attempt: Attempt, analysis: AttemptAnalysis) -> None:
    for analysed in analysis.steps:
        step = Step(
            attempt_id=attempt.id,
            index=analysed.view.index,
            raw_text=analysed.view.raw_text,
            kind=analysed.view.kind,
            formalised=analysed.view.formalised,
            formaliser_confidence=analysed.view.formaliser_confidence,
        )
        session.add(step)
        session.commit()
        session.refresh(step)
        result = analysed.verification
        # Evidence is stored unredacted: it is the audit trail. Redaction happens on the
        # way out to a learner, not on the way in to the record.
        session.add(
            Verification(
                step_id=step.id,
                tier=result.tier,
                status=result.status,
                evidence=result.evidence,
                confidence=result.confidence,
                latency_ms=result.latency_ms,
            )
        )
    diagnosis = analysis.diagnosis
    session.add(
        Diagnosis(
            attempt_id=attempt.id,
            first_break_index=diagnosis.first_break_index,
            error_class=diagnosis.error_class,
            misconception_id=diagnosis.misconception_id,
            confidence=diagnosis.confidence,
            summary=diagnosis.summary,
            probe=analysis.probe,
        )
    )
    session.commit()


def _attempt_out(
    attempt: Attempt,
    task: Task,
    analysis: AttemptAnalysis,
    claims: list[dict[str, Any]],
) -> AttemptOut:
    misconception = MISCONCEPTIONS.get(analysis.diagnosis.misconception_id or "")
    return AttemptOut(
        id=attempt.id,
        learner_id=attempt.learner_id,
        task_id=attempt.task_id,
        statement=task.statement,
        mode=attempt.mode,
        mode_source=attempt.mode_source,
        submitted_at=attempt.submitted_at,
        steps=[
            StepOut(
                index=a.view.index,
                raw_text=a.view.raw_text,
                kind=a.view.kind,
                status=a.verification.status,
                tier=a.verification.tier,
                evidence=leakage.redact(a.verification.evidence, task.canonical_answer),
                confidence=a.verification.confidence,
                derives=a.verification.detail.get("derives") == "yes",
            )
            for a in analysis.steps
        ],
        diagnosis=DiagnosisOut(
            first_break_index=analysis.diagnosis.first_break_index,
            error_class=analysis.diagnosis.error_class,
            misconception_id=analysis.diagnosis.misconception_id,
            misconception_name=misconception.name if misconception else None,
            confidence=analysis.diagnosis.confidence,
            summary=analysis.diagnosis.summary,
            derivation_present=analysis.diagnosis.derivation_present,
        ),
        probe=analysis.probe,
        coverage=dict(analysis.coverage),
        claims_updated=claims,
    )
