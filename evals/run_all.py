"""Run every eval and print the table. SPEC.md §10.

Two of these are blocking and the exit code reflects that: a single leakage failure, or a false
accusation rate above 2%, fails the build. The rest report.

Everything runs offline from fixtures so CI is deterministic — no network, no API key. If this
script ever needs one, the eval it needs it for has stopped being an eval.

    python -m evals.run_all
"""

from __future__ import annotations

import sys

from atrium.policy.leakage import check
from atrium.verify.ladder import Ladder
from atrium.verify.symbolic import SymbolicVerifier
from evals.accusation.corpus import build as accusation_corpus
from evals.leakage.corpus import build as leakage_corpus
from evals.recognition.score import load_samples
from evals.timing.score import score_all

ACCUSATION_GATE = 0.02


def leakage() -> tuple[bool, str]:
    cases = leakage_corpus()
    escaped = [c for c in cases if c.must_block and check(c.text, c.ctx) is None]
    blocked = [c for c in cases if not c.must_block and check(c.text, c.ctx) is not None]
    ok = not escaped
    detail = (
        f"{len(cases)} cases, {len(escaped)} leaked, {len(blocked)} legitimate moves blocked"
    )
    if escaped:
        detail += "\n    " + "\n    ".join(f"{c.id}: {c.text!r}" for c in escaped[:10])
    return ok, detail


def accusation() -> tuple[bool, str]:
    ladder = Ladder(tiers=[SymbolicVerifier()])
    total = 0
    wrong: list[str] = []
    for name, chain in accusation_corpus():
        for result in ladder.verify_chain(chain):
            total += 1
            if result.tellable:
                wrong.append(f"{name} line {result.line_index}")
    rate = len(wrong) / total if total else 0.0
    detail = (
        f"{len(accusation_corpus())} chains, {total} steps, "
        f"{len(wrong)} accusations ({rate:.2%})"
    )
    if wrong:
        detail += "\n    " + "\n    ".join(wrong[:10])
    return rate <= ACCUSATION_GATE, detail


def timing() -> tuple[bool, str]:
    score, count = score_all()
    if count == 0:
        return True, "no labelled sessions yet — §10 wants 20 recorded and hand-labelled"
    return True, (
        f"{count} sessions, precision {score.precision:.2f}, recall {score.recall:.2f}, "
        f"false interruption {score.false_interruption_rate:.2%}"
    )


def recognition() -> tuple[bool, str]:
    samples = load_samples()
    if not samples:
        return True, "no handwriting fixtures yet — target > 92% structural"
    return True, f"{len(samples)} samples (run pytest evals/recognition for the score)"


def main() -> int:
    checks = [
        ("leakage      [blocking]", leakage),
        ("accusation   [blocking]", accusation),
        ("timing       [report]  ", timing),
        ("recognition  [report]  ", recognition),
    ]
    failed = False
    print()
    for name, fn in checks:
        ok, detail = fn()
        blocking = "[blocking]" in name
        mark = "PASS" if ok else "FAIL"
        if not ok and blocking:
            failed = True
        print(f"  {mark}  {name}  {detail}")
    print()
    if failed:
        print("  blocking eval failed — the build does not ship\n")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
