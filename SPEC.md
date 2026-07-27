# Atrium — build spec

A room you enter and stay in until a concept clicks. Canvas, voice, and an agent that watches you
work. No tests, because the session is the evidence.

Paste this into a fresh repo as `SPEC.md` and work through it in milestone order. The earlier
`warrant` spec is not superseded — it becomes the `verify/` subsystem described in section 7.

---

## 1. Thesis

Nobody tests a child on whether they can walk. We know because we watched them. Learning has never
been observable at scale, so education invented an artificial sampling event — the exam — and then
built everything around it. Atrium makes learning observable, which makes the sampling event
unnecessary.

The product is a room. The company is the model of the learner that the room builds. Every design
decision is judged against one question: **does this interaction deposit something in the learner
model?** If a feature is delightful but leaves no trace, it is decoration and it does not ship.

## 2. What the learner experiences

They open a topic. There is a canvas, a voice, and no schedule. They can write, draw, talk, ask for
it to be explained as a circuit or a balance or a story, wander off into a prerequisite, come back,
try a problem, get stuck, get unstuck. The agent mostly watches. When it speaks it usually asks
something. It never writes the next line of their working for them.

At no point are they tested. At any point, they or their tutor can see exactly what they can now do
unaided.

## 3. Non-goals

Reject these if they appear later without an explicit scope change:

- Any move that supplies the next step or the final answer. See section 6.
- Tests, quizzes, scores, streaks, points, leaderboards, or any separate assessment event.
- Content generation at scale (question banks, video, courses). Atrium works on the learner's own
  material and a small seeded set.
- LMS integration, SSO, gradebook sync, admin dashboards.
- Detection of AI use.
- Mobile. Desktop with a stylus or trackpad only.

## 4. Architecture

```
┌─────────────────────────────────────────────────────────┐
│  Room (Next.js)                                          │
│  canvas · voice I/O · transcript · state peek            │
└───────────────┬─────────────────────────────────────────┘
                │ websocket: strokes, audio, events
┌───────────────▼─────────────────────────────────────────┐
│  Session runtime (FastAPI + Redis)                       │
│                                                          │
│  Observer ──► Verifier ──► Situation                     │
│     │                          │                         │
│     │                          ▼                         │
│     │                    Tutor policy ──► Move            │
│     │                          │                         │
│     └──────────► Evidence ledger                          │
└───────────────┬─────────────────────────────────────────┘
                │
┌───────────────▼─────────────────────────────────────────┐
│  Learner model (Postgres)                                │
│  skill estimates · readable state · representation       │
│  preferences · struggle log                              │
└─────────────────────────────────────────────────────────┘
```

Session state lives in Redis and is reconstructible from the event log. The learner model is the
only thing that must never be lost.

## 5. The Observer

The Observer answers one question continuously: **what is this person doing right now?**

Inputs: canvas strokes, speech transcript, typed text, idle timers.

### Reading the canvas

Do not attempt live stroke-level recognition. The loop is:

1. Buffer strokes. Detect a **stroke-idle boundary** (no new stroke for 900ms) or a region change.
2. Snapshot the affected canvas region to PNG at 2× density.
3. Send the snapshot plus the previous recognised state to a vision model. Ask for a structured
   reading: `{lines: [{latex, bbox, confidence, is_new, is_struck_through}]}`.
4. Diff against the previous reading to produce **events**, not a full re-read:
   `line_added`, `line_edited`, `line_erased`, `line_struck_through`.

Erasures and strike-throughs are signal, not noise — log them. Repeated erasure of the same line is
one of the strongest stall indicators you have.

MathPix is the fallback if vision-model accuracy on handwriting proves inadequate; keep recognition
behind `observe/recognise.py::Recogniser` so it can be swapped without touching anything else.

### Situation

The Observer emits a `Situation` on every event:

```python
class Situation(BaseModel):
    activity: Literal["producing", "consuming", "idle", "asking", "stalled"]
    latest_line: RecognisedLine | None
    verified: Verification | None          # from section 7
    seconds_since_production: int
    consumption_debt_s: int                # see section 6, production rule
    erasure_count_window: int
    topic_id: str
    open_question: str | None              # if the learner asked something
```

`Situation` is the sole input to the tutor policy. Keep it small and serialisable — it is what you
will log, replay, and evaluate against.

## 6. The Tutor policy — the core IP

The tutor cannot say arbitrary things. It selects a **Move** from a closed set, and the move is then
realised as text or speech. This is what makes behaviour testable, and it is what stops the system
degrading into a chatbot that hands out answers.

### Move set

```python
class MoveType(str, Enum):
    OBSERVE           = "observe"            # say nothing
    CONFIRM           = "confirm"            # brief acknowledgement, <6 words
    PROMPT_RETRIEVAL  = "prompt_retrieval"   # "what happens next?"
    ASK_PROBE         = "ask_probe"          # Socratic question about a specific line
    REQUEST_EXPLAIN   = "request_explain"    # "say why that step is allowed"
    REFRAME           = "reframe"            # same idea, different representation
    OFFER_ANALOGY     = "offer_analogy"      # only on request or after 2 failed probes
    FADE_EXAMPLE      = "fade_example"       # analogous problem, worked to step k, learner finishes
    REDIRECT          = "redirect"           # name the real blocker, often a prerequisite
    RAISE_DIFFICULTY  = "raise_difficulty"
```

**Forbidden, enforced by test, not by prompt:** stating the next line of the learner's working,
stating the final answer, or completing a derivation the learner has started. `FADE_EXAMPLE` uses a
*different* problem — never the one in front of them.

### When to speak

Default is silence. `OBSERVE` is the correct move most of the time and the policy must be biased
hard toward it. Speak when one of these fires:

| trigger | move |
|---|---|
| learner asks a question | answer the *question*, not the problem |
| verified `invalid` step | `ASK_PROBE` at that line |
| stalled: no production for 45s after activity | `PROMPT_RETRIEVAL`, then `REDIRECT` if still stalled |
| 3+ erasures of the same line in 60s | `REDIRECT` |
| consumption debt exceeded | any production move |
| valid step completing a skill | `CONFIRM` then `RAISE_DIFFICULTY` |

**Silence budget.** Cap interventions at 6 per 10 minutes of session time, excluding
learner-initiated turns. When over budget, the policy may only emit `OBSERVE` unless a verified
error is on screen. Log budget breaches; they are a product bug.

### The production rule

Track `consumption_debt_s`: seconds of tutor output the learner has received since their last
genuine production event (a new line of working, a spoken explanation of at least one clause, an
answered probe).

**If `consumption_debt_s > 90`, the next move must be a production move**
(`PROMPT_RETRIEVAL`, `REQUEST_EXPLAIN`, or `FADE_EXAMPLE`). No exceptions, including when the
learner is asking for more explanation. This one rule is the difference between a system that
teaches and a system that produces the feeling of understanding.

### Realisation

Once a `Move` is chosen, a model call turns it into words, conditioned on: the move type, the
`Situation`, the learner's readable state, and their representation preferences (section 8). Output
is checked by `policy/leakage.py` before it reaches the learner — see section 10.

## 7. The Verifier

Lifted from the `warrant` spec, running as a subsystem. Three tiers, deterministic first, and a
model tier that may abstain but may never convict.

- **Tier 1 — SymPy.** Solution-set equality for equation moves, `simplify(prev - curr) == 0` for
  expression moves. Certain. Parse failure returns `unverifiable`, never `invalid`.
- **Tier 2 — Lean 4 + mathlib**, sandboxed, hard timeout. **A timeout is `unverifiable`.**
- **Tier 3 — model judge.** Must return `follows: yes | no | cannot_tell` with a confidence. Maps to
  `invalid` only above 0.85 confidence, and never for a step whose kind is `algebraic`.

The learner is only ever told they are wrong on Tier 1 or Tier 2 evidence. Tier 3 produces
*"I can't follow how you got from here to here — talk me through it"*, which is a better tutoring
move anyway.

## 8. The Learner model

Four components, all persisted, all cross-session.

### 8.1 Skill estimates

Elo for ability and item difficulty, updated on every production event with an inferred difficulty.
Performance Factors Analysis for the per-skill view. Hierarchical pooling across the cohort so a new
learner starts from a sensible prior. Every estimate carries an evidence count and a confidence.

### 8.2 Readable state

A short natural-language description, regenerated at session end and capped at 120 words:

> Secure on rearranging linear equations and on the balance argument for why it works. Reliably
> drops a sign when a negative term crosses the equals. Gets unstuck faster from geometric framings
> than algebraic ones. Has not yet met simultaneous equations.

This is the primary artefact for a human — teacher, tutor, parent, or the learner themselves. It is
also the compression that lets you carry months of history into a prompt without carrying months of
transcript.

### 8.3 Representation preferences — the personalisation moat

This is the component that is genuinely yours and the one nobody else is building.

On every `REFRAME` or `OFFER_ANALOGY`, log:

```python
RepresentationEvent(
    learner_id, skill_id,
    representation: Literal["algebraic", "geometric", "numeric",
                            "physical_analogy", "code", "narrative", "diagrammatic"],
    followed_by_production: bool,     # did they produce a correct step within 120s?
    time_to_production_s: int | None,
)
```

Fit a simple per-learner multinomial over representations weighted by unstuck rate, with cohort
pooling for cold start. The policy then *selects* the reframing that works for this person rather
than sampling whatever the model felt like.

After eighty hours in the room, this model knows how a specific person gets unstuck. A competitor
with identical models cannot reproduce it for that person without those eighty hours. Everything
else in this build is copyable in a quarter; this is not.

### 8.4 Struggle log

Append-only: topic, first-break line, error class, resolution move, elapsed. Feeds spaced
resurfacing — the room reopens an old sticking point at the right interval without announcing it as
revision.

## 9. Assessment without tests

`GET /learners/{id}/state` renders skill estimates, evidence counts, the readable state, and links
to the actual moments of evidence.

Promotion rules, unchanged from `warrant`:

- `not_evidenced → emerging`: one valid unaided derivation exercising the skill.
- `emerging → secure`: three valid unaided derivations, across at least two distinct problems, with
  at least seven days between the first and last. Three in one sitting is not secure.
- `secure → emerging`: 90 days with no supporting evidence.

**Assistance tagging.** Every production event is tagged by how much tutor scaffolding preceded it
within the last 120 seconds: `unaided`, `probed`, `scaffolded`. **Only `unaided` events promote.**
This is the learning-debt instrument and it must never be softened to make the numbers look better.

## 10. Evals — build these alongside, not after

Everything below runs offline from recorded fixtures so CI is deterministic.

**Leakage (safety-critical, blocking).** Adversarial corpus of 200 situations including learners
begging for the answer, claiming an emergency, and claiming to be the teacher. Assert no tutor
output ever contains the next line of the learner's working or the final answer, in any notation
including words, LaTeX, and code. **Target: zero. A single failure fails the build.**

**False accusation (safety-critical, blocking).** 60+ correct derivations, including unusual orders
and non-standard notation. Assert we never claim a break in a correct chain. **Target < 1%, fail
build above 2%.**

**Intervention timing.** Record 20 real sessions. Have a human label every second with
`should_speak: yes | no`. Score the policy's choices as precision and recall against that. Report
false-interruption rate separately — interrupting someone who is thinking is the worst failure the
room can make and no other metric compensates for it.

**Recognition accuracy.** Handwritten maths line-level exact match, and structural match ignoring
cosmetic differences. Target > 92% structural on your own cohort's handwriting.

**Latency budgets, p95.** Stroke-idle to recognition 1.2s. Situation to move decision 400ms. Speech
in to first audio out 900ms. Blow any of these and the room feels dead.

**Outcome (the one that matters).** See section 12.

## 11. Stack

- Next.js 15, TypeScript, Tailwind. Canvas via `perfect-freehand` over an OffscreenCanvas; pointer
  events with pressure where available.
- Audio: streaming STT in, TTS out, with barge-in — the tutor stops speaking the instant the learner
  starts. Barge-in is not optional; without it the room feels like a lecture.
- FastAPI, Python 3.12, Redis for session state, Postgres 16 + SQLModel + Alembic.
- Anthropic API for recognition (vision), move realisation, diagnosis, and state summarisation, all
  behind `llm.py` with structured outputs, retries, and a fixture-replay mode.
- SymPy for tier 1. Lean 4 + mathlib in Docker for tier 2.
- pytest, ruff, mypy strict on `verify/` and `policy/`.

```
atrium/
  observe/     recognise.py strokes.py situation.py
  verify/      base.py symbolic.py formal.py judge.py ladder.py
  policy/      moves.py triggers.py budget.py realise.py leakage.py
  model/       skills.py readable.py representations.py struggle.py
  session/     runtime.py events.py
  api/
  llm.py
evals/         leakage/ accusation/ timing/ recognition/ run_all.py
web/
```

## 12. Milestones

**M0 — skeleton.** Repo, schema, migrations, websocket session, event log, one seeded topic
(solving linear equations, 4 skills, 12 problems). Acceptance: two browsers join a session and see
each other's strokes.

**M1 — it can see your working.** Canvas, stroke-idle snapshotting, vision recognition, line diffing.
Acceptance: write a five-line derivation by hand; the system's recognised state matches within one
cosmetic difference, and it correctly identifies which line you just added. *This is the first
moment that feels like magic — get here fast.*

**M2 — it knows when you are wrong.** Tier 1 verifier, first-break localisation, no tutor yet.
Acceptance: false accusation rate < 2% on the eval corpus.

**M3 — the policy, text only.** Move set, triggers, silence budget, production rule, leakage guard.
Acceptance: leakage eval at zero; a 15-minute session with a real person produces fewer than 10
interventions and they can describe at least half as well-timed.

**M4 — voice.** Streaming STT, TTS, barge-in, latency budgets met. Acceptance: you can work a
problem for ten minutes without touching the keyboard.

**M5 — the learner model.** Skills, readable state, representation preferences, struggle log,
cross-session continuity. Acceptance: start session two and it opens on the thing you were stuck on
in session one, without being told.

**M6 — the state view.** The no-tests assessment page, with evidence links and assistance tagging.
Acceptance: a scaffolded correct derivation does not promote a claim.

**M7 — pilot instrumentation.** Cohort assignment, consented session recording, delayed unaided
post-test harness, export for analysis.

## 13. The pilot this is all for

Design M7 around this and nothing else.

Twenty-plus classmates on the same modules. Randomise to Atrium or to their existing setup
(ChatGPT and past papers) for a fixed set of topics over a term. Primary outcome: **unaided
performance on the real January assessments**, pre-registered before you look at anything.
Secondary: time-to-unstuck, retention at four weeks, and the assistance-tagged claim counts.

Pre-register the analysis. If it works you have the only outcome number in the category and the
application writes itself. If it doesn't, you will know in ten weeks rather than three years, which
is worth almost as much.

## 14. Decide before building — do not let the model guess

- Which subject after linear equations. Analysis makes the Lean tier earn its keep sooner;
  probability gives you a broader cohort.
- Whether sessions are single-learner or admit a second human. Your Weavv work makes the group
  version tractable, and the evidence on group-plus-AI is the strongest in the field — but it
  doubles the interaction design. Decide, do not drift into it.
- Who owns the learner model: the institution or the learner. This decides whether you sell to
  universities or to individuals, and it is not a technical question.
- Whether the room ever refuses. If a learner asks flatly for the answer four times, does it give
  in? The honest answer is no, and the product consequence is that some people will leave. Decide
  that now, in writing, rather than at 2am under user pressure.

**These four are answered in [`DECISIONS.md`](DECISIONS.md). Read that before changing anything in
`policy/` or `model/`.**
