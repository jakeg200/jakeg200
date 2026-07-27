# Warrant — build spec

Working name: **warrant** (Toulmin: a claim is only as good as the warrant behind it).

---

## 1. Thesis

Education has never assessed learning. It has assessed artefacts — essays, answers, submitted
code — because watching a person actually think was unaffordable at scale. That was a tolerable
proxy for two hundred years. It stopped being one in about 2023, and no institution has a
replacement.

The replacement is not detection and it is not a tutor. It is an instrument that reads a person's
**reasoning**, establishes where that reasoning is and is not sound, and accumulates verified
claims about what they can do unaided.

Two design commitments follow, and everything below enforces them:

1. **The unit of assessment is a derivation, not an answer.** A correct answer with no valid
   derivation earns nothing. An invalid answer with three sound steps earns credit for three
   sound steps.
2. **We never tell a learner they are wrong unless we can prove it.** Symbolic and formal
   verification produce certainty. A language model produces a question, never a verdict.

## 2. The product in one sentence

A learner submits their working in ordinary language and notation; the system locates the first
step that does not follow, says why, asks one question that does not give the answer away, and
updates a portable record of what that person can derive without help.

## 3. Non-goals

Do not build any of these, and reject them if they appear in a later request without an explicit
decision to change scope:

- A tutor, chatbot, or anything that produces a solution to the learner's task.
- AI-usage detection or plagiarism scoring.
- An LMS, gradebook sync, timetabling, or SSO integration.
- Gamification, streaks, points, leaderboards.
- Mobile apps.

## 4. Domain model

Domain-general with a maths-first implementation. The verifier is pluggable so that a code
domain (execution + property tests) and a prose domain (rubric-based, model-tier only) can be
added without touching the pipeline.

```
Task          a problem statement plus the skills it exercises
Attempt       one learner's response to a Task, tagged with assistance mode
Step          one atomic move within an Attempt
Verification  a judgement about whether Step[i] follows from Step[i-1], with its tier
Diagnosis     the first break in the chain, its error class, and a confidence
Probe         a single Socratic question generated from the Diagnosis
Claim         an accumulated, evidence-backed statement about a learner and a skill
```

### Postgres schema (SQLModel)

```python
Learner(id, handle, created_at)
Skill(id, code, name, domain, prerequisite_ids: list[str])
Task(id, domain, statement, notation, canonical_answer, skill_ids: list[str],
     difficulty_b: float = 0.0)
Attempt(id, learner_id, task_id,
        mode: Literal["unassisted", "assisted", "unknown"],
        raw_text, submitted_at, elapsed_ms)
Step(id, attempt_id, index, raw_text,
     kind: Literal["algebraic", "inference", "definition", "assertion", "restatement"],
     formalised: str | None,          # SymPy srepr or Lean term
     formaliser_confidence: float | None)
Verification(id, step_id, tier: Literal[1, 2, 3],
             status: Literal["valid", "invalid", "unverifiable"],
             evidence: str, confidence: float | None, latency_ms: int)
Diagnosis(attempt_id, first_break_index: int | None,
          error_class: str, misconception_id: str | None,
          confidence: float, summary: str)
Claim(learner_id, skill_id,
      level: Literal["not_evidenced", "emerging", "secure"],
      n_unassisted: int, n_assisted: int,
      last_evidence_attempt_id, updated_at)
```

`mode` is load-bearing. **Only `unassisted` attempts may raise a Claim level.** Assisted attempts
are recorded and shown but cannot promote. This is the whole learning-debt instrument and it must
not be softened.

## 5. Pipeline

`POST /attempts` runs this synchronously for v0. Target p95 under 8 seconds.

```
segment(attempt.raw_text, task) -> list[Step]
    Model call. Split working into atomic steps. Preserve the learner's exact wording in
    raw_text — never paraphrase, never repair notation, never silently fix a typo.
    Classify each step's kind.

for i, step in enumerate(steps):
    formalise(step, prior_context) -> formalised, confidence
        Algebraic steps -> SymPy-parseable expression or relation.
        Inference steps  -> Lean statement if the Lean tier is enabled, else None.

    verify(steps[i-1], steps[i]) -> Verification
        Tier ladder, first conclusive answer wins. See section 6.

first_break = index of the first Verification with status == "invalid"
              (unverifiable steps do NOT break the chain — they are flagged, not failed)

diagnose(attempt, first_break) -> Diagnosis
probe(diagnosis) -> str
update_claims(attempt, diagnosis) -> list[Claim]
```

### Rules the pipeline must not violate

- An `unverifiable` step never produces a "you are wrong" message. It produces
  *"I can't follow the step from X to Y — can you justify it?"*
- Steps after `first_break` are still verified and reported, but relative to the learner's own
  prior step, not to the correct one. A learner who makes one slip and then reasons perfectly
  should be told exactly that.
- No component in this pipeline is ever given the canonical answer except `diagnose`, and
  `diagnose`'s output is checked by `probe` for answer leakage before it is returned.

## 6. The verifier ladder

Three tiers. Deterministic first. The model is the last resort and is the only tier permitted to
abstain.

**Tier 1 — symbolic (SymPy).** Certain.
Parse both steps. For an equation-to-equation move, check that the solution sets are equal:
`solveset(lhs_prev - rhs_prev) == solveset(lhs_curr - rhs_curr)` over the declared domain. For an
expression-to-expression move, check `simplify(prev - curr) == 0`. Returns `valid` or `invalid`
with the failing substitution as evidence. If parsing fails, return `unverifiable` and fall
through — never `invalid`.

**Tier 2 — formal (Lean 4 + mathlib).** Certain when it succeeds.
Behind `VerifierProtocol`; stub it in M1 and implement in M6. Emit the step as a Lean goal with
the previous step as hypothesis, run in a sandboxed container with a hard timeout.
**A timeout is `unverifiable`, never `invalid`.** This distinction is the single most important
correctness property in the system.

**Tier 3 — model judge.** Uncertain by construction.
Structured output, required fields:
`{follows: "yes" | "no" | "cannot_tell", confidence: float, reason: str}`.
Prompt must instruct the model to answer `cannot_tell` whenever the step could be valid under a
reasonable reading. Map `no` with confidence < 0.85 to `unverifiable`. Tier 3 may never produce
`invalid` for a step whose `kind` is `algebraic` — those belong to Tier 1, and if Tier 1 could not
parse them the honest answer is that we do not know.

Log tier coverage on every attempt. If Tier 3 is settling more than 40% of steps in the maths
domain, the formaliser is the thing to fix, not the prompt.

## 7. Capability record

```
GET /learners/{id}/record -> {claims: [...], generated_at, signature}
```

A Claim moves `not_evidenced -> emerging` on one valid unassisted derivation exercising that
skill, and `emerging -> secure` on three valid unassisted derivations across at least two
distinct tasks, at least one of which was submitted seven or more days after the first (spacing —
a skill demonstrated three times in one sitting is not secure).

Decay: a `secure` claim drops to `emerging` after 90 days with no supporting evidence.

Render the record as a single page a human can read: skill, level, how many unaided
demonstrations, when, and a link to the actual derivations. The evidence must be inspectable or
the credential is worthless.

## 8. Eval harness — build this in M4, not last

`evals/derivations.jsonl`, one record per line:

```json
{
  "task_id": "lin-eq-007",
  "statement": "Solve 7x - 2 = 3x + 10",
  "derivation": "7x take away 3x is 4x, and -2 add 10 is 8, so 4x = 8 and x = 2",
  "gold_first_break": 1,
  "gold_error_class": "sign_error_across_equals",
  "mode": "unassisted"
}
```

Seed with 60 records minimum, at least 20 of which are **fully correct derivations** — including
correct ones written in unusual order, with non-standard notation, and with valid but unexpected
methods.

Metrics, reported by `make eval`:

| metric | definition | target |
|---|---|---|
| false accusation rate | correct derivations where we claim a break | **< 1%** |
| localisation exact | first_break matches gold exactly | > 70% |
| localisation ±1 | first_break within one step of gold | > 85% |
| tier coverage | share of steps settled by tiers 1–2 | > 60% |
| abstention rate | steps returned `unverifiable` | report, no target |

False accusation rate is the safety metric. Telling a learner who is right that they are wrong is
the failure that destroys trust and cannot be recovered. Fail the build if it exceeds 2%.

## 9. Stack

- Python 3.12, FastAPI, SQLModel, Postgres 16, Alembic
- SymPy for tier 1; Lean 4 + mathlib in Docker for tier 2 (M6)
- Anthropic SDK, `claude-sonnet-4-6` for segmentation, formalisation, diagnosis and probes
- Next.js 15, TypeScript, Tailwind for the frontend
- pytest, ruff, mypy strict on `warrant/verify/`

Model calls go through one `warrant/llm.py` wrapper with structured-output parsing, retries, and
a recorded-fixture mode so the eval harness runs offline and deterministically in CI.

## 10. Repo layout

```
warrant/
  api/            FastAPI routes
  pipeline/       segment.py formalise.py diagnose.py probe.py
  verify/         base.py symbolic.py formal.py judge.py ladder.py
  records/        claims.py decay.py render.py
  llm.py
  models.py
evals/
  derivations.jsonl
  run_eval.py
  fixtures/
web/              Next.js
tests/
SPEC.md
```

## 11. Build order

**M0 — skeleton.** Repo, schema, migrations, health check, seeded Tasks and Skills for one topic
(linear equations, four skills, twelve tasks). Acceptance: `make dev` serves, `make test` passes.

**M1 — segment and symbolic verify.** Segmentation, SymPy tier, first-break localisation. Tiers 2
and 3 stubbed to return `unverifiable`. Acceptance: on 20 hand-written derivations, first break
located within ±1 on at least 16, and zero false accusations on the correct ones.

**M2 — diagnose and probe.** Error classification against a small named misconception taxonomy
(start with six). Socratic probe generation. Acceptance: an automated adversarial test asserts the
probe never contains the canonical answer, in any notation, across all 60 eval records.

**M3 — records.** Claims, promotion rules, spacing constraint, decay, assist tagging, the readable
record page. Acceptance: an assisted derivation that is fully valid does not promote a claim.

**M4 — eval harness.** The table in section 8, running offline from fixtures, wired into CI.

**M5 — frontend.** Three screens only: submit an attempt; see the chain with the break marked and
the probe; see your record. No dashboard.

**M6 — Lean tier.** Sandboxed, timeouts as `unverifiable`, coverage reported.

## 12. Demo script — must run in 90 seconds

1. Paste a derivation with a sign error at step two. It marks step two, explains the break, and
   asks a question that does not reveal `x = 3`.
2. Paste a *correct* derivation written in an unusual order. It marks nothing. This is the moment
   that earns trust.
3. Paste "the answer is x = 3, substituting gives 19 = 19". It records a valid verification and
   *no* derivation, and the record does not move.
4. Show the record: two skills emerging, one not evidenced, with the underlying attempts linked.

Point 3 is the pitch. A system that can tell the difference between deriving and checking is the
whole company.

Run it with `make demo`.

## 13. Decided before building

These were open questions in the original spec. They are settled; changing one is a scope
decision, not an implementation detail.

**Which subject after linear equations — first-year analysis.**
Probability has the bigger market and a richer misconception taxonomy, but it is mostly tier-1 and
tier-3 territory, and Lean would sit idle. Analysis is where tier 2 starts paying for itself
immediately: epsilon-delta arguments are genuine inferences rather than algebra, which is exactly
the class of step SymPy cannot reach and a model must not be trusted with. Taking the harder
domain second keeps the ladder honest while the taxonomy is still small.

**How `mode` is established — self-declared, behind an explicit attestation.**
`POST /attempts` rejects `mode="unassisted"` unless the request also carries `attested: true`, and
the record page states that assistance mode is self-declared rather than implying more.
Inferring mode from environment signals — paste events, focus loss, keystroke timing — is one step
away from AI-usage detection, which section 3 forbids outright, and it would make the instrument
adversarial towards the person it is meant to serve. Proctoring is stronger but requires an
institutional caller, which contradicts the ownership decision below. Self-declaration is honest
and weak; the record says which it is, so the credential never claims more than it has.
`Attempt.mode_source` exists so a proctored context can be added later without a migration.

**Who issues the record — the learner holds it; warrant signs it.**
The record is signed with warrant's Ed25519 key and carries `held_by: "learner"`. Warrant is the
verifier, not the awarding body; institutions become readers who check a signature rather than
gatekeepers who grant one. This makes the product sellable to individuals, and it is why there is
no tenancy in the schema. Institution-issued records would need tenants from day one, so this is
the decision that is expensive to reverse.

## 14. What is not yet true

Recorded here because a build report that only lists what works is not much of a report.

- **The eval set is self-authored.** The 71 records were written by the same author as the
  system, so the localisation figures measure internal consistency as much as accuracy. Real
  learner derivations are messier than anything in that file. The false-accusation metric is the
  one that survives this criticism least badly, because a false accusation is a false accusation
  whoever wrote the derivation.
- **Tier 2 is implemented but unproven.** The Lean verifier, its sandbox flags and its
  timeout-is-unverifiable behaviour are all in place and unit-tested behind a stub, but the image
  in `docker/lean` has not been built and no step has been settled by Lean.
- **Tier 3 has never run.** Every model call path degrades to the deterministic pipeline when no
  API key is present, which is how the whole system was built and measured. The judge's prompt and
  its confidence floor are unexercised against a live model.
- **Segmentation is the weakest link.** The deterministic splitter handles the derivations in the
  eval set, but it is a regex over connectives. A learner who writes in long prose paragraphs, or
  in two dimensions on a page, will be segmented badly, and bad segmentation moves the reported
  break even when every verification is right.
