"""Tier 2 — Lean 4 + mathlib, sandboxed, hard timeout.

**A timeout is `unverifiable`.** SPEC.md §7. This is stated twice in the spec and once more here
because it is the single easiest place to accidentally introduce a false accusation: a proof search
that ran out of wall clock has told you nothing about the learner, and a tier that reports
"couldn't prove it in 10s" as `invalid` will convict people for being slow to compile.

Status: the harness is real, the elaboration is not wired to a container yet. Without a Lean
toolchain on PATH every call returns `unverifiable`, which is the correct degradation — the ladder
simply falls through to tier 3, and nothing downstream can tell the difference except that the
learner is never told they are wrong on tier 2 evidence that does not exist.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Final

from .base import Step, Tier, Verdict, Verification, Verifier, unverifiable

TIMEOUT_S: Final = 10.0

_PREAMBLE: Final = "import Mathlib\nset_option maxHeartbeats 20000\n"


def lean_available() -> bool:
    return shutil.which("lake") is not None or shutil.which("lean") is not None


class FormalVerifier(Verifier):
    """Elaborate `prev = curr` as a Lean goal and see whether the tactic block closes it."""

    tier = Tier.FORMAL

    def __init__(self, timeout_s: float = TIMEOUT_S) -> None:
        self.timeout_s = timeout_s

    def verify(self, step: Step) -> Verification:
        if not lean_available():
            return unverifiable("no Lean toolchain", self.tier, step.line_index)
        if step.is_first_line():
            return unverifiable("no antecedent line", self.tier, step.line_index)

        try:
            source = self._goal(step)
        except ValueError as exc:
            return unverifiable(str(exc), self.tier, step.line_index)

        try:
            proc = self._run(source)
        except subprocess.TimeoutExpired:
            # The whole reason this file exists. Do not touch.
            return unverifiable(
                f"lean timed out after {self.timeout_s}s", self.tier, step.line_index
            )
        except OSError as exc:
            return unverifiable(f"lean could not run: {exc}", self.tier, step.line_index)

        if proc.returncode == 0:
            return Verification(
                verdict=Verdict.VALID,
                tier=self.tier,
                reason="lean closed the goal",
                line_index=step.line_index,
            )

        stderr = (proc.stderr or "") + (proc.stdout or "")
        # A failed tactic is not a disproof. Lean only convicts when it has refuted the goal,
        # which `ring_nf`/`norm_num` report distinctly from "unsolved goals".
        if "linarith failed to find a contradiction" in stderr or "unsolved goals" in stderr:
            return unverifiable("lean did not close the goal", self.tier, step.line_index)
        if "norm_num" in stderr and "False" in stderr:
            return Verification(
                verdict=Verdict.INVALID,
                tier=self.tier,
                reason="lean refuted the step",
                line_index=step.line_index,
            )
        return unverifiable("lean inconclusive", self.tier, step.line_index)

    def _goal(self, step: Step) -> str:
        for text in (step.prev, step.curr):
            if "\\" in text or not text.strip():
                raise ValueError("step is not Lean-expressible")
        body = f"example : ({step.prev}) = ({step.curr}) := by\n  ring_nf <;> norm_num\n"
        return _PREAMBLE + body

    def _run(self, source: str) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Step.lean"
            path.write_text(source, encoding="utf-8")
            return subprocess.run(  # noqa: S603 - fixed argv, content is a temp file we wrote
                ["lean", str(path)],
                capture_output=True,
                text=True,
                timeout=self.timeout_s,
                check=False,
            )
