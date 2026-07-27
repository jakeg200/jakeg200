# warrant

An instrument that reads a person's reasoning, locates the first step that does not follow, and
accumulates verified claims about what they can derive unaided.

Not a tutor. Not a detector. The unit of assessment is a derivation, not an answer — and nothing
is ever called wrong unless it can be proved wrong.

The full design is in [SPEC.md](SPEC.md).

## Quick start

```bash
make install        # python 3.12 venv + deps
make demo           # the 90-second demo, in the terminal
make eval           # the eval harness — offline, no API key, no database
make test           # 85 tests
```

To run the thing:

```bash
make db-up          # postgres 16 (optional: the default is a local sqlite file)
make migrate
make dev            # api on :8000
cd web && npm install && npm run dev    # three screens on :3000
```

No API key is needed for any of the above. Every model call degrades to a deterministic path
when the model is unavailable, which is how the system was built and measured.

## What it does

Give it working written the way a person actually writes it:

```
7x take away 3x is 4x, and -2 add 10 is 8, so 4x = 8 and x = 2
```

```
✓ 7x take away 3x is 4x                (derives nothing)
✓ -2 add 10 is 8                       (derives nothing)   <- the reasoning goes wrong here
✗ 4x = 8                                                   <- where it becomes provably wrong
✓ x = 2

Step 2 does not follow: a constant crossed the equals sign without changing sign.
Probe: You moved a term across the equals sign here. What has to happen to that term's
       sign when it crosses, and why?
```

Three things are happening there that are the whole point.

**Both of the first two lines are true**, and are marked true, even though the second one is where
the reasoning goes wrong. `-2 + 10 = 8` is correct arithmetic; the mistake is *using* it, because
the -2 should have changed sign on crossing. The break is proved at line three and attributed back
to line two, and attribution can only ever move a break earlier — never invent one.

**The last line is marked valid.** `x = 2` genuinely follows from `4x = 8`. One slip followed by
sound reasoning is reported as exactly that, because every step is judged against the learner's own
previous line rather than against the line they should have written.

**The probe never contains the answer.** Neither does the summary, and neither does any evidence
string the API returns — tier-1 evidence usually contains the solution as a witness value, so it is
stored for audit and redacted on the way out.

## The three demo moments

`make demo` runs these:

1. A sign error at step two — marked, explained, probed, without revealing `x = 3`.
2. A correct derivation written in an unusual order — marked as entirely fine. This is the moment
   that earns trust.
3. `the answer is x = 3, substituting gives 19 = 19` — every line verifies, nothing is wrong, and
   the record does not move, because checking an answer is not deriving one.

The third is the pitch.

## How it decides

Three tiers, deterministic first, first conclusive answer wins:

| tier | method | may say "invalid"? |
|---|---|---|
| 1 | SymPy solution-set equivalence | yes, with a witness value |
| 2 | Lean 4 + mathlib, sandboxed | only by proving the negation |
| 3 | model judge | never for an algebraic step |

Everything else is `unverifiable`, which costs the learner nothing: unverifiable steps are flagged,
never failed, and never break a chain. A Lean timeout is `unverifiable`. A parse failure is
`unverifiable`. An unreachable API is `unverifiable`. There is no path in the system from
"we could not tell" to "you were wrong".

Tier 1 reads each step charitably: `7x - 3x = 4x` is a true lemma, not a botched transformation of
the equation above it, and reading it the other way would confidently accuse someone who is
entirely correct. A step is invalid only when every reasonable reading fails.

## Measured

`make eval` over 71 records (35 with no break, 36 with a known break):

| metric | value | target |
|---|---|---|
| false accusation rate | 0.0% | < 1% (build fails above 2%) |
| localisation exact | 100% | > 70% |
| localisation ±1 | 100% | > 85% |
| tier coverage (1–2) | 95.9% | > 60% |
| abstention rate | 4.1% | report only |
| error class accuracy | 83.3% | report only |
| p95 latency | 72 ms | < 8 s |

Read those two localisation figures with the caveat in SPEC.md §14: the eval set and the system
share an author. The false accusation rate is the number that matters and the number the build
gates on.

## The record

`GET /learners/{id}/record` returns claims with their evidence; `record.html` renders one page a
human can read. A skill reaches `emerging` on one unaided derivation and `secure` on three, across
at least two tasks, spread over at least seven days — three in one sitting is not secure. A secure
claim decays to emerging after ninety days without evidence.

Assisted attempts are counted and shown and **never** promote a level. That gap is the instrument.

Assistance mode is self-declared behind an explicit attestation, the record says so, and the record
is held by the learner and signed by warrant. Both decisions, and why, are in SPEC.md §13.

## Layout

```
warrant/verify/     the ladder: base, mathparse, symbolic, formal, judge   (mypy strict)
warrant/pipeline/   segment, formalise, diagnose, probe, leakage, run
warrant/records/    claims, decay, record, render, sign
warrant/api/        FastAPI routes
evals/              derivations.jsonl + run_eval.py, offline and deterministic
docker/lean/        the tier 2 sandbox image
web/                Next.js, three screens, no dashboard
```
