"""The ninety-second demo from SPEC section 12, runnable with `make demo`.

Four moments. The third is the pitch: a system that can tell the difference between
deriving an answer and checking one.
"""

from __future__ import annotations

import sys
from pathlib import Path

from sqlmodel import Session

from warrant import db
from warrant.config import settings
from warrant.models import Attempt, Learner, Task
from warrant.pipeline.run import AttemptAnalysis, analyse
from warrant.records.claims import assess_evidence, update_claims
from warrant.records.record import build_record
from warrant.seed import seed

BOLD, DIM, RESET = "\033[1m", "\033[2m", "\033[0m"
RED, GREEN, YELLOW = "\033[31m", "\033[32m", "\033[33m"

MARK = {
    "valid": f"{GREEN}✓{RESET}",
    "invalid": f"{RED}✗{RESET}",
    "unverifiable": f"{YELLOW}?{RESET}",
}


def show(title: str, analysis: AttemptAnalysis, note: str) -> None:
    print(f"\n{BOLD}{title}{RESET}")
    print(f"{DIM}{note}{RESET}\n")
    proved_at = analysis.diagnosis.detail.get("proved_at_index")
    for step in analysis.steps:
        result = step.verification
        index = step.view.index
        pointer = ""
        if analysis.diagnosis.first_break_index == index:
            pointer = f"{RED}  <- the reasoning goes wrong here{RESET}"
        elif proved_at is not None and int(proved_at) == index:
            pointer = f"{DIM}  <- where it becomes provably wrong{RESET}"
        derives = "" if result.detail.get("derives") == "yes" else f" {DIM}(derives nothing){RESET}"
        print(f"  {MARK[result.status]} {step.view.raw_text}{derives}{pointer}")
    print(f"\n  {DIM}{analysis.diagnosis.summary}{RESET}")
    if analysis.probe:
        print(f"  {BOLD}Probe:{RESET} {analysis.probe}")
    evidence = assess_evidence(analysis)
    print(f"  {DIM}Admissible as evidence: {evidence.admissible} — {evidence.reason}{RESET}")


def main() -> int:
    settings.database_url = "sqlite:///./demo.db"
    Path("demo.db").unlink(missing_ok=True)
    db.reset_engine()
    db.create_all()

    with Session(db.engine()) as session:
        seed(session)
        learner = Learner(handle="demo-learner")
        session.add(learner)
        session.commit()
        session.refresh(learner)

        script = [
            (
                "lin-eq-007",
                "7x take away 3x is 4x, and -2 add 10 is 8, so 4x = 8 and x = 2",
                "unassisted",
                "1. A sign error. It marks the step, says why, and asks a question that "
                "does not reveal the answer.",
            ),
            (
                "lin-eq-007",
                "7 - 3 = 4 and 10 + 2 = 12\n4x = 12\nx = 3",
                "unassisted",
                "2. Correct, written in an unusual order. It marks nothing. This is the "
                "moment that earns trust.",
            ),
            (
                "lin-eq-007",
                "the answer is x = 3, substituting gives 19 = 19",
                "unassisted",
                "3. True, verified, and not a derivation. The record does not move.",
            ),
            (
                "lin-eq-004",
                "4x + 5 = 17\n4x = 12\nx = 3",
                "unassisted",
                "4. A second unaided derivation, on a different task.",
            ),
        ]

        for task_id, text, mode, note in script:
            task = session.get(Task, task_id)
            assert task is not None
            analysis = analyse(text, task.statement, task.canonical_answer)
            title = f"{task.statement}  {DIM}[{mode}]{RESET}"
            show(title, analysis, note)
            attempt = Attempt(learner_id=learner.id, task_id=task.id, mode=mode, raw_text=text)
            session.add(attempt)
            session.commit()
            session.refresh(attempt)
            update_claims(session, attempt, task, analysis)

        record = build_record(session, learner.id)
        print(f"\n{BOLD}The record{RESET}\n")
        for claim in record["claims"]:
            unaided = claim["unaided_demonstrations"]
            print(
                f"  {claim['level']:<14} {claim['skill_name']:<36} "
                f"{unaided} unaided demonstration(s)"
            )
        print(
            f"\n  {DIM}signed {record['signature']['algorithm']} "
            f"({record['signature']['key_kind']} key), held by the learner{RESET}\n"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
