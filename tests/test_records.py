"""Claims, and the rules that decide what we are willing to say about a person."""

from __future__ import annotations

from datetime import timedelta

from sqlmodel import Session, select

from warrant.models import Attempt, Claim, Learner, Skill, Task, utcnow
from warrant.pipeline.run import analyse
from warrant.records.claims import assess_evidence, level_for, update_claims
from warrant.records.decay import apply_decay, is_stale
from warrant.records.record import build_record
from warrant.records.render import render_record
from warrant.records.sign import sign, verify

GOOD = "4x + 5 = 17\n4x = 12\nx = 3"
TASK_ID = "lin-eq-004"


def _submit(
    session: Session,
    learner: Learner,
    task_id: str,
    text: str,
    mode: str,
    days_ago: int = 0,
) -> list[Claim]:
    task = session.get(Task, task_id)
    assert task is not None
    analysis = analyse(text, task.statement, task.canonical_answer)
    attempt = Attempt(
        learner_id=learner.id,
        task_id=task.id,
        mode=mode,
        raw_text=text,
        submitted_at=utcnow() - timedelta(days=days_ago),
    )
    session.add(attempt)
    session.commit()
    session.refresh(attempt)
    return update_claims(session, attempt, task, analysis)


def _learner(session: Session, handle: str = "kit") -> Learner:
    learner = Learner(handle=handle)
    session.add(learner)
    session.commit()
    session.refresh(learner)
    return learner


def test_one_unassisted_derivation_reaches_emerging(session: Session) -> None:
    learner = _learner(session)
    claims = _submit(session, learner, TASK_ID, GOOD, "unassisted")
    assert claims
    assert all(c.level == "emerging" for c in claims)
    assert all(c.n_unassisted == 1 for c in claims)


def test_an_assisted_derivation_does_not_promote(session: Session) -> None:
    """M3's acceptance test. A perfect assisted derivation moves nothing."""
    learner = _learner(session)
    claims = _submit(session, learner, TASK_ID, GOOD, "assisted")
    assert all(c.level == "not_evidenced" for c in claims)
    assert all(c.n_unassisted == 0 for c in claims)
    assert all(c.n_assisted == 1 for c in claims)


def test_unknown_mode_does_not_promote(session: Session) -> None:
    learner = _learner(session)
    claims = _submit(session, learner, TASK_ID, GOOD, "unknown")
    assert all(c.level == "not_evidenced" for c in claims)


def test_a_broken_derivation_is_not_evidence(session: Session) -> None:
    learner = _learner(session)
    claims = _submit(session, learner, TASK_ID, "4x + 5 = 17\n4x = 22\nx = 5.5", "unassisted")
    assert all(c.level == "not_evidenced" for c in claims)


def test_an_asserted_answer_is_not_evidence(session: Session) -> None:
    """Demo moment three, at the level of the record: checking does not promote."""
    learner = _learner(session)
    claims = _submit(
        session,
        learner,
        "lin-eq-007",
        "the answer is x = 3, substituting gives 19 = 19",
        "unassisted",
    )
    assert all(c.level == "not_evidenced" for c in claims)
    assert all(c.n_unassisted == 0 for c in claims)


def test_three_in_one_sitting_is_not_secure(session: Session) -> None:
    learner = _learner(session)
    _submit(session, learner, TASK_ID, GOOD, "unassisted")
    _submit(session, learner, "lin-eq-005", "5x - 3 = 12\n5x = 15\nx = 3", "unassisted")
    claims = _submit(
        session, learner, "lin-eq-011", "6x - 4 = 2x + 8\n4x = 12\nx = 3", "unassisted"
    )
    assert all(c.level == "emerging" for c in claims)


def test_spacing_and_distinct_tasks_reach_secure(session: Session) -> None:
    learner = _learner(session)
    _submit(session, learner, TASK_ID, GOOD, "unassisted", days_ago=30)
    _submit(
        session, learner, "lin-eq-005", "5x - 3 = 12\n5x = 15\nx = 3", "unassisted", days_ago=20
    )
    _submit(session, learner, "lin-eq-011", "6x - 4 = 2x + 8\n4x = 12\nx = 3", "unassisted")
    claims = session.exec(select(Claim).where(Claim.learner_id == learner.id)).all()
    divide = next(
        c
        for c in claims
        if session.get(Skill, c.skill_id) and session.get(Skill, c.skill_id).code == "LIN-DIVIDE"
    )
    assert divide.n_unassisted == 3
    assert divide.level == "secure"


def test_repeating_one_task_does_not_reach_secure(session: Session) -> None:
    learner = _learner(session)
    for days in (30, 20, 0):
        _submit(session, learner, TASK_ID, GOOD, "unassisted", days_ago=days)
    claims = session.exec(select(Claim).where(Claim.learner_id == learner.id)).all()
    assert all(c.level == "emerging" for c in claims)


def test_decay_demotes_a_stale_secure_claim(session: Session) -> None:
    learner = _learner(session)
    claim = Claim(
        learner_id=learner.id,
        skill_id="whatever",
        level="secure",
        n_unassisted=3,
        last_evidence_at=utcnow() - timedelta(days=120),
    )
    session.add(claim)
    session.commit()
    assert is_stale(claim)
    decayed = apply_decay(session)
    assert [c.level for c in decayed] == ["emerging"]


def test_decay_never_erases_evidence(session: Session) -> None:
    learner = _learner(session)
    claim = Claim(
        learner_id=learner.id,
        skill_id="whatever",
        level="emerging",
        n_unassisted=1,
        last_evidence_at=utcnow() - timedelta(days=400),
    )
    session.add(claim)
    session.commit()
    apply_decay(session)
    session.refresh(claim)
    assert claim.level == "emerging"
    assert claim.n_unassisted == 1


def test_level_for_is_pure() -> None:
    claim = Claim(learner_id="a", skill_id="b", n_unassisted=0)
    assert level_for(claim) == "not_evidenced"
    claim.n_unassisted = 1
    claim.first_evidence_at = utcnow()
    claim.last_evidence_at = utcnow()
    assert level_for(claim) == "emerging"


def test_evidence_reasons_are_stated() -> None:
    broken = assess_evidence(analyse("4x + 5 = 17\n4x = 22", "Solve 4x + 5 = 17"))
    assert not broken.admissible
    assert "break" in broken.reason


def test_record_lists_unevidenced_skills_and_links_evidence(session: Session) -> None:
    learner = _learner(session)
    _submit(session, learner, TASK_ID, GOOD, "unassisted")
    record = build_record(session, learner.id)
    levels = {c["skill_code"]: c["level"] for c in record["claims"]}
    assert levels["LIN-EXPAND"] == "not_evidenced"
    evidenced = [c for c in record["claims"] if c["evidence"]]
    assert evidenced and evidenced[0]["evidence"][0]["href"].startswith("/attempts/")


def test_record_signature_round_trips(session: Session) -> None:
    learner = _learner(session)
    record = build_record(session, learner.id)
    signature = record.pop("signature")
    assert verify(record, signature)
    record["claims"] = []
    assert not verify(record, signature)


def test_signature_declares_a_development_key() -> None:
    signed = sign({"a": 1})
    assert signed["key_kind"] == "development"
    assert signed["held_by"] == "learner"


def test_record_page_renders_the_things_a_reader_needs(session: Session) -> None:
    learner = _learner(session, "reader-test")
    _submit(session, learner, TASK_ID, GOOD, "unassisted")
    html = render_record(build_record(session, learner.id))
    assert "reader-test" in html
    assert "emerging" in html
    assert "unaided demonstration" in html
    assert "/attempts/" in html
