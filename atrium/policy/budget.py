"""The silence budget and the production rule. SPEC.md §6.

Two counters that between them define the room's manners.

**Silence budget.** Six interventions per ten minutes, excluding learner-initiated turns. Over
budget, the policy may only emit OBSERVE unless a verified error is on screen. Breaches are logged
because they are a product bug, not a metric.

**Consumption debt.** Seconds of tutor output since the learner last produced anything. Over 90,
the next move *must* make them produce — no exceptions, including when they are asking for more
explanation. The spec is blunt about why: this is the difference between a system that teaches and
one that manufactures the feeling of understanding. A learner nodding along to a fluent explanation
is the failure mode that every tutoring product ships with, and this counter is the only thing in
the architecture that resists it.
"""

from __future__ import annotations

from collections import deque
from typing import Final

from pydantic import BaseModel

CAP: Final = 6
WINDOW_S: Final = 600  # ten minutes
DEBT_LIMIT_S: Final = 90


class BudgetBreach(BaseModel):
    at_s: float
    interventions_in_window: int
    reason: str


class SilenceBudget:
    def __init__(self, cap: int = CAP, window_s: int = WINDOW_S) -> None:
        self.cap = cap
        self.window_s = window_s
        self._spoken: deque[float] = deque()
        self.breaches: list[BudgetBreach] = []

    def _trim(self, now_s: float) -> None:
        while self._spoken and now_s - self._spoken[0] > self.window_s:
            self._spoken.popleft()

    def spent(self, now_s: float) -> int:
        self._trim(now_s)
        return len(self._spoken)

    def remaining(self, now_s: float) -> int:
        return max(0, self.cap - self.spent(now_s))

    def over_budget(self, now_s: float) -> bool:
        return self.spent(now_s) >= self.cap

    def record(self, now_s: float, *, learner_initiated: bool = False) -> None:
        """Log an intervention. Learner-initiated turns do not count against the cap (§6) —
        answering a question they asked is not an interruption."""
        if learner_initiated:
            return
        self._trim(now_s)
        self._spoken.append(now_s)

    def record_breach(self, now_s: float, reason: str) -> None:
        self.breaches.append(
            BudgetBreach(
                at_s=now_s, interventions_in_window=self.spent(now_s), reason=reason
            )
        )


def debt_exceeded(consumption_debt_s: int) -> bool:
    return consumption_debt_s > DEBT_LIMIT_S
