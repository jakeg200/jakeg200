"""The seeded topic: linear equations in one unknown.

Four skills, twelve tasks. Small on purpose — the point of the first topic is to make
the instrument honest, not to cover a syllabus.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SeedSkill:
    code: str
    name: str
    prerequisites: tuple[str, ...] = ()


@dataclass(frozen=True)
class SeedTask:
    id: str
    statement: str
    canonical_answer: str
    skills: tuple[str, ...]
    difficulty_b: float = 0.0


SKILLS: list[SeedSkill] = [
    SeedSkill("LIN-REARRANGE", "Move a term across the equals sign"),
    SeedSkill("LIN-EXPAND", "Expand a bracket in a linear equation"),
    SeedSkill("LIN-COLLECT", "Collect like terms in the unknown", ("LIN-REARRANGE",)),
    SeedSkill("LIN-DIVIDE", "Divide through by the coefficient", ("LIN-COLLECT",)),
]

TASKS: list[SeedTask] = [
    SeedTask("lin-eq-001", "Solve x + 4 = 9", "x = 5", ("LIN-REARRANGE",), -1.0),
    SeedTask("lin-eq-002", "Solve x - 7 = 2", "x = 9", ("LIN-REARRANGE",), -1.0),
    SeedTask("lin-eq-003", "Solve 3x = 12", "x = 4", ("LIN-DIVIDE",), -0.8),
    SeedTask("lin-eq-004", "Solve 4x + 5 = 17", "x = 3", ("LIN-REARRANGE", "LIN-DIVIDE"), -0.4),
    SeedTask("lin-eq-005", "Solve 5x - 3 = 12", "x = 3", ("LIN-REARRANGE", "LIN-DIVIDE"), -0.4),
    SeedTask("lin-eq-006", "Solve 2x + 7 = x + 11", "x = 4", ("LIN-COLLECT",), 0.0),
    SeedTask(
        "lin-eq-007",
        "Solve 7x - 2 = 3x + 10",
        "x = 3",
        ("LIN-REARRANGE", "LIN-COLLECT", "LIN-DIVIDE"),
        0.2,
    ),
    SeedTask("lin-eq-008", "Solve 3(x + 2) = 12", "x = 2", ("LIN-EXPAND", "LIN-DIVIDE"), 0.2),
    SeedTask(
        "lin-eq-009",
        "Solve 2(x - 3) = 4x - 10",
        "x = 2",
        ("LIN-EXPAND", "LIN-COLLECT", "LIN-DIVIDE"),
        0.6,
    ),
    SeedTask(
        "lin-eq-010",
        "Solve 5x + 3 = 2x - 9",
        "x = -4",
        ("LIN-REARRANGE", "LIN-COLLECT", "LIN-DIVIDE"),
        0.5,
    ),
    SeedTask(
        "lin-eq-011",
        "Solve 6x - 4 = 2x + 8",
        "x = 3",
        ("LIN-REARRANGE", "LIN-COLLECT", "LIN-DIVIDE"),
        0.3,
    ),
    SeedTask(
        "lin-eq-012",
        "Solve 4(x + 1) = 2(x + 5)",
        "x = 3",
        ("LIN-EXPAND", "LIN-COLLECT", "LIN-DIVIDE"),
        0.8,
    ),
]

TASKS_BY_ID = {task.id: task for task in TASKS}
