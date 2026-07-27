#!/usr/bin/env python
"""The eval harness.

Runs offline and deterministically: no API key, no database, no network. What it
measures, in order of importance:

  false accusation rate  — correct derivations we claimed had a break.
                           This is the safety metric. Telling somebody who is right that
                           they are wrong is the failure that cannot be walked back, and
                           the build fails above 2%.
  localisation           — did we point at the step they actually went wrong on.
  tier coverage          — how much the deterministic tiers settled. If tier 3 is doing
                           the work in maths, the formaliser needs fixing, not the prompt.
  abstention             — how often we said "I cannot tell". Reported, not targeted:
                           abstention is the honest answer and is not a failure.
  probe safety           — an adversarial check that no probe ever contains the answer.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from warrant.pipeline.probe import is_safe  # noqa: E402
from warrant.pipeline.run import analyse  # noqa: E402
from warrant.seed_data import TASKS_BY_ID  # noqa: E402

ROOT = Path(__file__).resolve().parent
DEFAULT_DATASET = ROOT / "derivations.jsonl"

TARGETS = {
    "false_accusation_rate": ("<", 0.01),
    "localisation_exact": (">", 0.70),
    "localisation_within_1": (">", 0.85),
    "tier_coverage": (">", 0.60),
}
FAIL_THRESHOLD = 0.02


@dataclass
class Case:
    task_id: str
    statement: str
    derivation: str
    gold_first_break: int | None
    gold_error_class: str
    mode: str

    @property
    def canonical_answer(self) -> str:
        task = TASKS_BY_ID.get(self.task_id)
        return task.canonical_answer if task else ""


def load(path: Path) -> list[Case]:
    cases: list[Case] = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        raw = json.loads(line)
        cases.append(
            Case(
                task_id=raw["task_id"],
                statement=raw["statement"],
                derivation=raw["derivation"],
                gold_first_break=raw.get("gold_first_break"),
                gold_error_class=raw.get("gold_error_class", "none"),
                mode=raw.get("mode", "unassisted"),
            )
        )
    return cases


def run(cases: list[Case], verbose: bool = False) -> dict[str, Any]:
    correct = [c for c in cases if c.gold_first_break is None]
    broken = [c for c in cases if c.gold_first_break is not None]

    false_accusations: list[dict[str, Any]] = []
    missed: list[dict[str, Any]] = []
    exact = within_one = 0
    class_hits = 0
    unsafe_probes: list[dict[str, Any]] = []
    steps_total = steps_deterministic = steps_settled = 0
    latencies: list[int] = []

    for case in cases:
        analysis = analyse(case.derivation, case.statement, case.canonical_answer)
        predicted = analysis.diagnosis.first_break_index
        latencies.append(analysis.elapsed_ms)

        coverage = analysis.coverage
        steps_total += int(coverage["steps"])
        steps_settled += int(coverage["settled"])
        steps_deterministic += int(coverage["tier1"]) + int(coverage["tier2"])

        if analysis.probe and not is_safe(analysis.probe, case.canonical_answer):
            unsafe_probes.append({"task": case.task_id, "probe": analysis.probe})
        if analysis.diagnosis.summary and not is_safe(
            analysis.diagnosis.summary, case.canonical_answer
        ):
            unsafe_probes.append({"task": case.task_id, "summary": analysis.diagnosis.summary})

        if case.gold_first_break is None:
            if predicted is not None:
                false_accusations.append(
                    {
                        "task": case.task_id,
                        "derivation": case.derivation,
                        "claimed_break_at": predicted,
                        "steps": [s.view.raw_text for s in analysis.steps],
                        "evidence": analysis.steps[predicted].verification.evidence
                        if predicted < len(analysis.steps)
                        else "",
                    }
                )
        else:
            if predicted is None:
                missed.append({"task": case.task_id, "derivation": case.derivation})
            else:
                if predicted == case.gold_first_break:
                    exact += 1
                if abs(predicted - case.gold_first_break) <= 1:
                    within_one += 1
                if analysis.diagnosis.error_class == case.gold_error_class:
                    class_hits += 1

        if verbose:
            mark = "ok " if (predicted == case.gold_first_break) else "MISS"
            print(
                f"{mark} {case.task_id:11} gold={str(case.gold_first_break):>4} "
                f"pred={str(predicted):>4} {case.derivation[:60]!r}"
            )

    return {
        "records": len(cases),
        "correct_records": len(correct),
        "broken_records": len(broken),
        "false_accusation_rate": len(false_accusations) / len(correct) if correct else 0.0,
        "localisation_exact": exact / len(broken) if broken else 0.0,
        "localisation_within_1": within_one / len(broken) if broken else 0.0,
        "error_class_accuracy": class_hits / len(broken) if broken else 0.0,
        "missed_breaks": len(missed) / len(broken) if broken else 0.0,
        "tier_coverage": steps_deterministic / steps_total if steps_total else 0.0,
        "abstention_rate": (steps_total - steps_settled) / steps_total if steps_total else 0.0,
        "unsafe_probes": len(unsafe_probes),
        "p50_ms": statistics.median(latencies) if latencies else 0,
        "p95_ms": sorted(latencies)[int(len(latencies) * 0.95)] if latencies else 0,
        "_false_accusations": false_accusations,
        "_missed": missed,
        "_unsafe": unsafe_probes,
    }


def report(results: dict[str, Any]) -> int:
    rows = [
        ("false accusation rate", "false_accusation_rate", "< 1%"),
        ("localisation exact", "localisation_exact", "> 70%"),
        ("localisation ±1", "localisation_within_1", "> 85%"),
        ("tier coverage (1–2)", "tier_coverage", "> 60%"),
        ("abstention rate", "abstention_rate", "report only"),
        ("error class accuracy", "error_class_accuracy", "report only"),
        ("missed breaks", "missed_breaks", "report only"),
    ]

    print()
    print(
        f"  {results['records']} records "
        f"({results['correct_records']} correct, {results['broken_records']} with a break)"
    )
    print()
    print(f"  {'metric':<24}{'value':>9}   {'target':<12}")
    print(f"  {'-' * 24}{'-' * 9}   {'-' * 12}")
    ok = True
    for label, key, target in rows:
        value = results[key]
        verdict = ""
        if key in TARGETS:
            comparison, threshold = TARGETS[key]
            met = value < threshold if comparison == "<" else value > threshold
            verdict = "  ok" if met else "  MISSED"
            if not met and key != "false_accusation_rate":
                ok = False
        print(f"  {label:<24}{value:>8.1%}   {target:<12}{verdict}")
    print()
    print(
        f"  probe safety            {'FAIL' if results['unsafe_probes'] else 'clean':>8}   "
        f"no probe may contain the answer"
    )
    print(f"  latency p50/p95         {results['p50_ms']:>5}/{results['p95_ms']}ms   p95 < 8000ms")
    print()

    for item in results["_false_accusations"]:
        print(f"  FALSE ACCUSATION  {item['task']}: {item['derivation']!r}")
        print(f"                    claimed a break at step {item['claimed_break_at']}")
        print(f"                    steps: {item['steps']}")
        print(f"                    evidence: {item['evidence']}")
    for item in results["_unsafe"]:
        print(f"  LEAKED ANSWER     {item}")

    hard_fail = results["false_accusation_rate"] > FAIL_THRESHOLD or results["unsafe_probes"] > 0
    if hard_fail:
        print(
            "\n  BUILD FAILS: the system told a correct learner they were wrong, or "
            "gave the answer away.\n"
        )
        return 1
    if not ok:
        print("  Targets missed, but nothing unsafe.\n")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    cases = load(args.dataset)
    results = run(cases, verbose=args.verbose)
    if args.json:
        print(json.dumps({k: v for k, v in results.items() if not k.startswith("_")}, indent=2))
        return 0
    return report(results)


if __name__ == "__main__":
    raise SystemExit(main())
