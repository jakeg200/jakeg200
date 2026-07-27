# Atrium

A room you enter and stay in until a concept clicks. Canvas, voice, and an agent that watches you
work. No tests, because the session is the evidence.

The full build spec is [`SPEC.md`](SPEC.md). The four questions it says to answer before writing
code are answered in [`DECISIONS.md`](DECISIONS.md) — read that before changing anything in
`policy/` or `model/`.

## Where this is

M0 is in place, and the deterministic core of M2 and M3 is built and passing its blocking evals.
M1 (vision recognition) and M4 (voice) are scaffolded behind interfaces but not wired to a model or
a microphone.

| Milestone | State | Notes |
|---|---|---|
| **M0** skeleton | done | Two browsers join a session and see each other's strokes — `tests/test_api.py` |
| **M1** it can see your working | partial | Stroke-idle buffering, region snapshotting, and line diffing are done and tested. `VisionRecogniser` is written but has no fixtures, so the acceptance test has never been run against real handwriting. |
| **M2** it knows when you are wrong | done | Tier 1 + first-break localisation. **0 false accusations across 82 chains / 160 steps.** |
| **M3** the policy, text only | core done | Move set, triggers, silence budget, production rule, leakage guard. **Leakage eval at zero across 360 adversarial cases.** Not yet run with a real person for 15 minutes. |
| **M4** voice | not started | |
| **M5** the learner model | logic done, not persisted | Elo, PFA, promotion rules, representation preferences, and struggle log are implemented and tested. No Postgres schema or migrations yet, so nothing is actually cross-session. |
| **M6** the state view | endpoint shape only | `GET /learners/{id}/state` returns the right shape against an empty ledger. |
| **M7** pilot instrumentation | not started | |

Two gaps are deliberately left visible: the **intervention-timing** eval needs 20 recorded sessions
with a human labelling every second, and the **recognition** eval needs real handwriting. Both
harnesses are written, and both skip loudly rather than report a number nobody measured.

## Running it

```bash
pip install -e ".[dev]"        # deterministic core: pydantic + sympy
pip install -e ".[runtime]"    # + FastAPI, Redis, Postgres, Anthropic

python -m evals.run_all        # the blocking evals
pytest -q                      # everything
ruff check atrium evals tests
python -m mypy atrium/verify atrium/policy   # strict, per SPEC.md §11

uvicorn atrium.api.app:app --reload          # API on :8000
cd web && npm install && npm run dev         # the room on :3000
```

The evals run offline from fixtures and need no API key — a blocking eval that can reach the
network is not a blocking eval. `ATRIUM_LLM=replay` is the default whenever `ANTHROPIC_API_KEY` is
unset.

## The two numbers that matter right now

```
PASS  leakage      [blocking]  360 cases, 0 leaked, 0 legitimate moves blocked
PASS  accusation   [blocking]  82 chains, 160 steps, 0 accusations (0.00%)
```

Both are safety-critical and both fail the build on a single regression. They are also the reason
the verifier abstains so readily and the leakage guard blocks so eagerly: a missed error costs one
probe a few seconds later, and a false accusation costs the learner's trust, which they only lend
once.

## Layout

```
atrium/
  observe/   strokes.py     stroke-idle boundaries and region detection
             recognise.py   the Recogniser seam (vision now, MathPix if needed) + line diffing
             situation.py   the Observer; emits the Situation the policy consumes
  verify/    base.py        the valid / invalid / unverifiable asymmetry
             symbolic.py    tier 1, SymPy — needs a counterexample before it will convict
             formal.py      tier 2, Lean 4 (a timeout is `unverifiable`)
             judge.py       tier 3, model — may abstain, may never convict on algebra
             ladder.py      tier order and first-break localisation
  policy/    moves.py       the closed move set
             triggers.py    when to speak; pure, so the timing eval can replay it
             budget.py      silence budget and the production rule
             leakage.py     the guard, and D1's analogue-distance check
             realise.py     move -> words, guarded, with safe fallbacks
  model/     skills.py      Elo, PFA, promotion rules, assistance tagging
             representations.py   the personalisation moat
             struggle.py    append-only log and spaced resurfacing
             readable.py    the 120-word state
  session/   events.py      append-only event log; sessions replay from it
             runtime.py     Observer -> Verifier -> Situation -> Policy -> Move
  seed/      linear_equations.py   topics are data, not code
  api/       FastAPI: websocket room, state view, learner export and delete
  llm.py     every model call, with fixture replay
evals/       leakage/ accusation/ timing/ recognition/ run_all.py
web/         the room
```

## What this deliberately does not do

From §3: no tests, quizzes, scores, streaks, points, or leaderboards; no content generation at
scale; no LMS integration or SSO; no AI-use detection; no mobile. And no move that supplies the
next step or the final answer — that one is enforced by `policy/leakage.py` and a blocking eval,
because it is the one everything else rests on.
