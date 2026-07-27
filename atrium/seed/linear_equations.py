"""M0's seeded topic: solving linear equations. 4 skills, 12 problems.

Topics are **data, not code** (DECISIONS.md D4). Nothing in `verify/` or `policy/` may assume
linear equations; the second subject loads through this same shape. If adding a topic requires
touching a module outside `seed/`, that is the bug.

Each problem carries:

* `solution_steps` — the canonical derivation. Used *only* by the leakage guard, as the list of
  lines the tutor must never say. It is not a rubric and the learner is never scored against it;
  a different valid route is still valid, which is what the verifier is for.
* `analogue` — a different problem for FADE_EXAMPLE, chosen to pass `analogue_distance`.
"""

from __future__ import annotations

from typing import Any

TOPIC_ID = "linear-equations"
TITLE = "Solving linear equations"

SKILLS: list[dict[str, str]] = [
    {
        "id": "le.inverse-operations",
        "name": "Undoing an operation on both sides",
        "description": "Applies the inverse operation to both sides to isolate a term.",
    },
    {
        "id": "le.transposition",
        "name": "Moving a term across the equals",
        "description": "Moves a term to the other side with the correct sign change.",
    },
    {
        "id": "le.distribution",
        "name": "Expanding brackets",
        "description": "Multiplies a bracket out correctly before collecting terms.",
    },
    {
        "id": "le.balance-argument",
        "name": "Why it works",
        "description": "Explains equation solving as preserving a balance, not as a ritual.",
    },
]


def _problem(
    pid: str,
    statement: str,
    steps: list[str],
    answer: str,
    skills: list[str],
    difficulty: float,
    analogue: dict[str, Any],
) -> dict[str, Any]:
    return {
        "id": pid,
        "statement": statement,
        "solution_steps": steps,
        "answer": answer,
        "skills": skills,
        "difficulty": difficulty,
        "variable": "x",
        "analogue": analogue,
    }


PROBLEMS: list[dict[str, Any]] = [
    _problem(
        "le-01", "x + 7 = 12", ["x = 5"], "x = 5",
        ["le.inverse-operations"], 1000.0,
        {"statement": "y - 4 = 9", "steps": ["y = 13"]},
    ),
    _problem(
        "le-02", "3x = 15", ["x = 5"], "x = 5",
        ["le.inverse-operations"], 1020.0,
        {"statement": "m/4 = 3", "steps": ["m = 12"]},
    ),
    _problem(
        "le-03", "3x + 8 = 23", ["3x = 15", "x = 5"], "x = 5",
        ["le.inverse-operations", "le.transposition"], 1100.0,
        {"statement": "5t - 4 = 26", "steps": ["5t = 30", "t = 6"]},
    ),
    _problem(
        "le-04", "5 - 2x = 1", ["-2x = -4", "x = 2"], "x = 2",
        ["le.transposition"], 1180.0,
        {"statement": "14 = 4w + 2", "steps": ["12 = 4w", "3 = w"]},
    ),
    _problem(
        "le-05", "2(x + 3) = 14", ["2x + 6 = 14", "2x = 8", "x = 4"], "x = 4",
        ["le.distribution", "le.inverse-operations"], 1200.0,
        {"statement": "4(n - 1) = 20", "steps": ["4n - 4 = 20", "4n = 24", "n = 6"]},
    ),
    _problem(
        "le-06", "4x - 4 = 2x + 6", ["2x - 4 = 6", "2x = 10", "x = 5"], "x = 5",
        ["le.transposition"], 1260.0,
        {"statement": "7p + 2 = 3p + 18", "steps": ["4p + 2 = 18", "4p = 16", "p = 4"]},
    ),
    _problem(
        "le-07", "3(x - 2) = x + 4", ["3x - 6 = x + 4", "2x - 6 = 4", "2x = 10", "x = 5"], "x = 5",
        ["le.distribution", "le.transposition"], 1320.0,
        {
            "statement": "5(q + 1) = 2q + 17",
            "steps": ["5q + 5 = 2q + 17", "3q + 5 = 17", "3q = 12", "q = 4"],
        },
    ),
    _problem(
        "le-08", "x/4 + 2 = 5", ["x/4 = 3", "x = 12"], "x = 12",
        ["le.inverse-operations"], 1280.0,
        {"statement": "k/3 - 1 = 4", "steps": ["k/3 = 5", "k = 15"]},
    ),
    _problem(
        "le-09", "(2x + 1)/3 = 5", ["2x + 1 = 15", "2x = 14", "x = 7"], "x = 7",
        ["le.inverse-operations", "le.transposition"], 1380.0,
        {"statement": "(3z - 2)/4 = 4", "steps": ["3z - 2 = 16", "3z = 18", "z = 6"]},
    ),
    _problem(
        "le-10", "7 - (x + 2) = 3", ["7 - x - 2 = 3", "5 - x = 3", "-x = -2", "x = 2"], "x = 2",
        ["le.distribution", "le.transposition"], 1420.0,
        {"statement": "2(c - 3) = 8", "steps": ["2c - 6 = 8", "2c = 14", "c = 7"]},
    ),
    _problem(
        "le-11", "2(3x - 1) = 4(x + 2)",
        ["6x - 2 = 4x + 8", "2x - 2 = 8", "2x = 10", "x = 5"], "x = 5",
        ["le.distribution", "le.transposition"], 1480.0,
        {"statement": "3(2d + 1) = 5(d - 1)", "steps": ["6d + 3 = 5d - 5", "d + 3 = -5", "d = -8"]},
    ),
    _problem(
        "le-12", "x/2 + x/3 = 5", ["3x/6 + 2x/6 = 5", "5x/6 = 5", "5x = 30", "x = 6"], "x = 6",
        ["le.inverse-operations", "le.balance-argument"], 1540.0,
        {"statement": "2v/3 - v/6 = 4", "steps": ["4v/6 - v/6 = 4", "3v/6 = 4", "v = 8"]},
    ),
]


def topic() -> dict[str, Any]:
    return {"id": TOPIC_ID, "title": TITLE, "skills": SKILLS, "problems": PROBLEMS}
