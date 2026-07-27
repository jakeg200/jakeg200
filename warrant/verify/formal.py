"""Tier 2 — formal verification with Lean 4 + mathlib. Certain when it succeeds.

The single most important property in this file: **a timeout is "unverifiable", never
"invalid"**. Lean failing to close a goal inside its budget tells you about Lean, not
about the person. Every failure path here — no Lean, no Docker, no formalisation, a
crash, a timeout, an unparseable transcript — resolves to "unverifiable".

The only thing that produces "invalid" is Lean reporting that the *negation* of the step
is provable, which is a genuine disproof.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Literal

from warrant.config import settings
from warrant.verify.base import (
    StepView,
    TaskContext,
    VerificationResult,
    unverifiable,
)

TEMPLATE = """import Mathlib
set_option maxHeartbeats 400000

-- hypothesis: the learner's previous line
-- goal: the learner's next line
theorem warrant_step {binders} {hypothesis} : {goal} := by
  first
    | linarith
    | nlinarith
    | ring_nf <;> linarith
    | field_simp <;> ring_nf <;> linarith
    | norm_num
    | simp_all <;> linarith
"""

REFUTE_TEMPLATE = """import Mathlib
set_option maxHeartbeats 400000

theorem warrant_step_refuted {binders} {hypothesis} : ¬ ({goal}) := by
  first
    | norm_num
    | decide
    | simp_all
"""


def lean_available() -> bool:
    if not settings.lean_enabled:
        return False
    return shutil.which("docker") is not None


class LeanVerifier:
    """Tier 2. Sandboxed, budgeted, and mute unless it actually proves something."""

    tier: Literal[1, 2, 3] = 2
    name = "lean4"

    def verify(self, prev: StepView | None, curr: StepView, ctx: TaskContext) -> VerificationResult:
        started = time.perf_counter()

        def elapsed() -> int:
            return int((time.perf_counter() - started) * 1000)

        if not lean_available():
            return unverifiable(2, "lean tier not enabled", elapsed())
        if curr.formalised is None:
            return unverifiable(2, "step was not formalised into Lean", elapsed())

        binders, hypothesis = self._context(prev)
        goal = curr.formalised

        proved = self._run(TEMPLATE.format(binders=binders, hypothesis=hypothesis, goal=goal))
        if proved is True:
            return VerificationResult(
                tier=2,
                status="valid",
                evidence=f"lean proved: {goal}",
                latency_ms=elapsed(),
                detail={"reading": "lean_proof"},
            )
        if proved is None:
            return unverifiable(2, "lean did not finish inside its budget", elapsed())

        # Lean failed to prove the step. That alone means nothing — the tactics may
        # simply be too weak. Only an actual proof of the negation is a disproof.
        refuted = self._run(
            REFUTE_TEMPLATE.format(binders=binders, hypothesis=hypothesis, goal=goal)
        )
        if refuted is True:
            return VerificationResult(
                tier=2,
                status="invalid",
                evidence=f"lean proved the negation of: {goal}",
                latency_ms=elapsed(),
                detail={"reading": "lean_refutation"},
            )
        return unverifiable(2, "lean could neither prove nor refute the step", elapsed())

    def _context(self, prev: StepView | None) -> tuple[str, str]:
        if prev is None or prev.formalised is None:
            return "(x : ℝ)", ""
        return "(x : ℝ)", f"(h : {prev.formalised})"

    def _run(self, source: str) -> bool | None:
        """True = proved, False = did not prove, None = no usable answer."""
        with tempfile.TemporaryDirectory() as workdir:
            path = Path(workdir) / "Step.lean"
            path.write_text(source)
            cmd = [
                "docker",
                "run",
                "--rm",
                "--network",
                "none",
                "--cpus",
                "1",
                "--memory",
                "2g",
                "--pids-limit",
                "128",
                "--read-only",
                "--tmpfs",
                "/tmp:rw,size=64m",
                "-v",
                f"{workdir}:/work:ro",
                settings.lean_image,
                "lake",
                "env",
                "lean",
                "/work/Step.lean",
            ]
            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=settings.lean_timeout_s,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                return None
            except OSError:
                return None

        if result.returncode == 0 and not result.stderr.strip():
            return True
        transcript = (result.stdout + result.stderr).lower()
        if "error" in transcript and "unsolved goals" not in transcript:
            # A compile error means our emitted Lean was wrong, not the learner.
            return None
        return False


def coverage_note() -> str:
    return json.dumps(
        {"lean_enabled": settings.lean_enabled, "docker": shutil.which("docker") is not None}
    )
