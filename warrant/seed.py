"""Idempotent seeding of skills and tasks."""

from __future__ import annotations

from sqlmodel import Session, select

from warrant.db import create_all, session_scope
from warrant.models import Skill, Task
from warrant.seed_data import SKILLS, TASKS


def seed(session: Session) -> tuple[int, int]:
    by_code: dict[str, Skill] = {skill.code: skill for skill in session.exec(select(Skill)).all()}
    added_skills = 0
    for spec in SKILLS:
        if spec.code not in by_code:
            skill = Skill(code=spec.code, name=spec.name, domain="maths", prerequisite_ids=[])
            session.add(skill)
            by_code[spec.code] = skill
            added_skills += 1
    session.commit()

    for spec in SKILLS:
        skill = by_code[spec.code]
        skill.prerequisite_ids = [by_code[code].id for code in spec.prerequisites]
        session.add(skill)
    session.commit()

    existing = {task.id for task in session.exec(select(Task)).all()}
    added_tasks = 0
    for spec in TASKS:
        if spec.id in existing:
            continue
        session.add(
            Task(
                id=spec.id,
                domain="maths",
                statement=spec.statement,
                notation="text",
                canonical_answer=spec.canonical_answer,
                skill_ids=[by_code[code].id for code in spec.skills],
                difficulty_b=spec.difficulty_b,
            )
        )
        added_tasks += 1
    session.commit()
    return added_skills, added_tasks


def main() -> None:
    create_all()
    with session_scope() as session:
        skills, tasks = seed(session)
    print(f"seeded {skills} skill(s) and {tasks} task(s)")


if __name__ == "__main__":
    main()
