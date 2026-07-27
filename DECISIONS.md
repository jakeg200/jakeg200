# Decisions

The four questions in `SPEC.md` §14, answered before any code was written. Each one has a
consequence in the tree. Do not reopen these in an implementation PR — reopen them here first, with
a date and a reason, and then change the code.

---

## D1 — Does the room ever give in?

**Decision: it never states the answer to the problem in front of the learner. After the third flat
demand it escalates `FADE_EXAMPLE` to a fully worked *different* problem, and says plainly that it
is doing that instead.**

Answered: 2026-07-27.

The invariant is not "be unhelpful under pressure". It is narrower and harder: *the learner's own
derivation is theirs to complete*. A fully worked analogous problem is not a violation of that — it
is the oldest working intervention in the literature (worked-example effect), and refusing it out of
squeamishness makes the room feel punitive without making it more honest.

What this costs: the analogue is now the leakage surface. A "different" problem that is
$3x + 7 = 22$ when the learner is staring at $3x + 8 = 23$ is the answer with a coat on. So the
escalation carries a **structural-distance guard**, not a vibe:

- the analogue must differ from the live problem in at least two of {coefficients, operation order,
  variable side, sign pattern},
- its solution value must differ,
- and `policy/leakage.py` re-checks the *rendered* analogue against the live problem's remaining
  derivation before it goes out. Failing the distance check is a hard block, not a warning — the
  move degrades to `REDIRECT`.

Enforced in `policy/leakage.py::analogue_distance` and `policy/moves.py::FadeExample`. Tested in
`evals/leakage/` under the `four_asks_*` fixtures, which are part of the blocking corpus.

**Product consequence, accepted:** a learner who wants the answer and only the answer will not get
it here, and some of them will leave for a chatbot that hands it over. That is the trade the whole
product rests on. If retention pressure ever makes this look negotiable, re-read §1 — the company is
the learner model, and a learner model built on copied answers is worth nothing.

## D2 — Single-learner, or a second human in the room?

**Decision: single-learner, built so a second can be admitted later without a rewrite.**

Answered: 2026-07-27.

The session runtime is multi-client from M0 — several sockets can attach to one session and see the
same strokes, which is what M0's two-browser acceptance test exercises, and what makes a tutor or
observer able to look over a shoulder. But exactly one attached client holds the `producer` role.
The Observer, `Situation`, evidence ledger, and every promotion rule assume one producer, and the
policy addresses one person.

Consequence in the tree: `session/runtime.py` tracks `producer_client_id` and non-producer clients
are read-only. `Situation` deliberately has no participant field. Adding the second human means
adding it, attributing evidence per person, and deciding who the policy addresses — an explicit
scope change, not a drift.

## D3 — Who owns the learner model?

**Decision: the learner. Not the institution.**

Answered: 2026-07-27.

Consequence in the tree, and the reason this had to be decided before the first migration: the
schema keys on `learner_id` with **no `org_id` column anywhere**. There is no institution tenancy to
retrofit around later, because retrofitting it is how learner-owned quietly becomes
institution-owned. Full export and hard delete are first-class, in `api/` from M0 rather than bolted
on for a compliance review.

An institution reads a learner's state only by a grant the learner makes and can revoke. That is a
later table, and it is a *grant*, not a tenancy.

Commercial consequence, accepted: this sells to individuals. A university deal that requires owning
the cohort's models is a different company and we are not building it.

## D4 — Which subject after linear equations?

**Decision: deferred. M0 seeds solving linear equations only.**

Answered: 2026-07-27. Revisit when M1 and M2 are accepted.

The choice between analysis and probability is really a bet on how good tier 1 turns out to be on
real handwriting, and we do not have that number yet. Decide it against M1's recognition accuracy
and M2's false-accusation rate rather than against taste:

- if tier 1 abstains a lot and recognition holds up, take **analysis** — the Lean tier is earning
  its keep and the formal work is the moat,
- if recognition is the bottleneck, take **probability** — more tier-1-verifiable algebra, broader
  cohort for the §13 pilot, less pressure on the tier that is hardest to make fast.

Consequence in the tree: nothing in `verify/` or `policy/` may hard-code linear-equation
assumptions. Topics are data (`atrium/seed/`), not code. This is checked by the fact that the
seeded topic loads through the same path any later topic would.
