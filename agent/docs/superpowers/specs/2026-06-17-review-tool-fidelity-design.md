# Design: `review-tool-fidelity` (rethought)

**Date:** 2026-06-17 · **Status:** design, pending user approval · **Branch:** feat/reviewer-agent

Rethink-from-scratch of the Phase-2 `review-tool-fidelity` skill (existing version is reference
only). Co-designed in a brainstorming session; this captures the validated design before any code.

---

## 1. What the skill is for

Audit whether an autonomous run followed its **prescribed tool choreography** — one narrow,
process-level question:

> Did this run call the **required tools** (and no **forbidden** ones), honour the **ordering
> invariants**, **complete** without crashing, and **recover** sensibly from any errored calls —
> and with what **tool-call success rate**? (Plus descriptive runtime/cost health, never a fail.)

It judges **process adherence**, nothing else. Explicit non-goals (route elsewhere):

| Question | Owner |
|---|---|
| Was the decision well-reasoned / biased? | `review-decision-quality` |
| Did the order actually fill / the row actually save? | `review-operation-success` |
| Was a hard rule broken (exposure, stop-loss)? | `review-strategy-conformance` |
| Is the strategy working / is the agent rationalizing? | `review-strategy-efficacy` |

---

## 2. Evidence model — LangSmith trace ONLY

The **LangSmith trace is the only direct record of tool usage** — it shows which tools were called,
in what order, with what arguments, and which errored. Supabase only holds tool *side-effects*
(artifacts), and many trader tools (`score_universe`, `enrich_eps_revisions`, technicals, risk
checks, quotes) leave no artifact, so a DB-derived view is a coarse proxy blind to most of the
sequence.

**Decision: the skill is trace-native. The Supabase-artifact fallback is explicitly dropped.** When
no trace is available the skill reports honestly ("no trace for this run — cannot audit tool
fidelity, confidence 0") rather than degrading to a weak proxy.

**Accepted consequence:** on the currently-synced data (which has no matching traces) the skill is
effectively inert. It becomes useful once real traces flow (newly-fired runs trace to LangSmith).

---

## 3. Core design decisions

### 3a. Deterministic detection, LLM judgment

Counting errored calls and checking ordering invariants are **deterministic computations** — a
script does them more reliably and cheaply than an LLM eyeballing a trace. So:

- **A tool computes the facts** (invariant violations + success-rate + per-tool error breakdown)
  from the resolved trace. Pure, testable, no model in the loop.
- **The LLM's job is the part it is good at:** interpret the facts (is this `get_quote` timeout a
  transient blip or a real process failure?), judge severity, and consolidate into standing memory.

This matches the reviewer's whole philosophy: facts from tools, judgment from the model. It also
keeps this (lowest-model-risk) skill from spending an LLM on arithmetic.

### 3b. Invariants, not a golden sequence

The trader is an LLM deep-agent, not a deterministic script — it legitimately varies (skips
`enrich_eps_revisions` with no candidates, reorders independent reads). Comparing against a **rigid
linear sequence produces false positives** on benign variation, and a reviewer that cries wolf gets
ignored.

So the rubric is a small set of **invariants**, not a script:

- **Required-step presence** — e.g. a factor-loop that placed orders must have run
  `generate_factor_rankings`; an EOD run must have produced a reflection journal entry +
  `record_daily_snapshot`.
- **Dependency-ordering invariants** — real causal constraints only, e.g. `place_order` must occur
  **after** `generate_factor_rankings`; `record_decision` after its `place_order`.
- **Required-*absence* / forbidden tools** — per-phase tools that must NOT appear, e.g. **no
  `place_order` on a weekend run** (weekends are no-execution). A forbidden call is a violation.
  (This absorbs "phase-appropriate tools" into the invariant check rather than a separate dimension.)
- **Benign reordering of independent steps is tolerated** (not flagged).

Invariants are defined **per phase** (factor-loop weekday / factor-loop weekend / EOD reflection /
weekly review). The phase is identified from the run input / journal.

### 3c. Dimensions of the verdict — two tiers

**Tier A — correctness (drives severity):**

1. **Invariant adherence** — required steps present, **forbidden tools absent**, dependency-order
   honoured (§3b).
2. **Tool-call success rate** — `failed / total` calls + per-tool error breakdown (failure = §3d).
3. **Error-handling / recovery** — for each errored call, what did the agent do: retry, fall back,
   or **silently swallow it and proceed**? A silently-swallowed `place_order` error is a key catch.
   Detection is semi-deterministic (error-then-retry?); the LLM judges whether the recovery was
   *appropriate* — **this is where the LLM earns its place** in an otherwise mechanical skill.
4. **Run completion** — did the root run finish, or crash/abort before its terminal step (root
   `error` set)? Deterministic; a crashed loop is a major process failure.

**Tier B — observability (descriptive; `info`/`warn` only, NEVER a standalone `fail`):**

5. **Resource usage / runtime** — run wall-time, slowest tool calls, token/cost (all present in the
   trace). Flag only **egregious *relative* anomalies** (vs the run's own recent history), never
   absolute thresholds — latency and cost are environment-noisy, so absolute limits would cry wolf
   (the same false-positive trap as a rigid sequence). Sharpens over time as memory accumulates a
   rolling baseline.
6. **Redundant / wasteful calls** — e.g. `score_universe` called 3× in one run. Soft flag.

**Why the split:** Tier A is process-*correctness* and may fail a run; Tier B is process-*health* —
real signal, but too noisy to drive a fail by itself. Separating them keeps a slow API or a costly
run from producing a false `fail`. Deliberately still excluded: **argument *appropriateness*** (did
it order the *right* symbol → `decision-quality`/`conformance`) — that boundary must not creep in.

### 3d. Precise definition of "tool-call failure"

A **failed tool call = the trace `error` field is set** (the call mechanically raised/errored). A
structured business outcome (e.g. `place_order` returning a *risk-rejection* result with no error)
is **NOT** a tool-call failure — that belongs to `review-operation-success`. This keeps the
success-rate metric from double-counting what operation-success owns.

---

## 4. Run identification — fixing `read_run_trace`

The reviewer is handed a *subject* (a date, "the most recent run", a specific run). Two problems
today, both fixed in `read_run_trace`:

- **Which group (bug):** the `monet_agent` LangSmith project mixes root runs from several graphs —
  `autonomous_loop` (the trader, the target), `monet_agent` (chat), `review_agent` (the reviewer
  itself), `LangGraph` (dev). Today `read_run_trace` returns the newest root of *any* name → the
  reviewer's own run. **Fix: filter roots to `name == "autonomous_loop"`, excluding the reviewer.**
- **Which run:** add **subject→run targeting** — select by recency (most-recent-N trader roots)
  and/or a date/time window (match `start_time`). A date may hold several runs (10am/1pm/4pm); each
  is its own subject.

(Longer-term cleaner separation: trace the trader to its own `LANGSMITH_PROJECT` so the reviewer
queries only the trader's project. The name filter solves it today without touching the trader.)

---

## 5. Atomic unit, sweep, and the watermark

- **Atomic unit of a review = one run** (one root trace, one phase, one expected-invariant set, one
  success-rate). One run is the only clean object to compare against expected.
- **Cross-run patterns live in memory, not a wide audit.** "`record_daily_snapshot` missing from
  afternoon runs" emerges when several single-run audits each flag it and confidence hardens via the
  existing quarantine (low → established at count ≥ 3). Audit narrow; let consolidation aggregate.
- **Sweep = batch of atomic audits.** "Review today/this week" = run the same atomic audit on each
  trader root in the window → N verdicts + N consolidations, not one blurred aggregate. A true
  "weekly rollup" is a lightweight **memory read** (summarise standing insights + recent verdicts),
  not a re-trace — and belongs to the weekly-review flow.

### Watermark (self-resuming cursor)

The reviewer records the **last-reviewed run** in its own bound memory, so it audits exactly the
un-reviewed runs. This makes the skill **idempotent and cadence-agnostic** — fire it per-loop,
daily, or weekly and it always reviews "what's new since last time."

Required semantics (must be pinned, or it silently skips/re-reviews):

- **Cold start (no watermark):** review only the **most recent N** runs and set the mark — do NOT
  backfill all history.
- **Late-arriving traces (ingestion lag):** advancing purely by `start_time` would skip a run that
  lands out of order. Track **reviewed run_ids** (or a watermark with a small lookback) rather than
  a bare timestamp.
- **Advance on success only:** if a review errors mid-run, the watermark must NOT advance past that
  run, or it is never audited.

The watermark record is **target-stamped** (`graph: "autonomous_loop"`) so a future per-group fork
is clean.

### What the skill writes to memory (four stores)

Reuses the existing platform. The **LLM authors only #1 (verdict) and #2/#3 (consolidation via the
`scope=` API)**; the watermark (#4) is **code-managed, exactly like `routing_log`/`_active`** — the
model never hand-edits it.

> **These JSON shapes are implementer reference and are enforced by the tool signatures + code
> helpers (`write_review`, `stamp_insight`, the watermark helper) — they are NOT skill content.**
> The `SKILL.md` must restate only the *behavioral* memory contract — call `begin_review` first;
> after the verdict, `write_review(...)` with the deterministic facts in `evidence_refs`;
> consolidate via `record_insight` / `write_reviewer_memory(scope=…)` **only for recurring/
> significant** findings — and must **never inline these structures**. The agent hand-assembles only
> the `evidence_refs` *contents* and the one-line `index` value; the provenance schema and the
> watermark are built by code and the agent never sees them. Restating shapes in the skill would
> create a second, drift-prone source of truth and undo the namespace-encapsulation hardening.

1. **Per-run verdict → `agent_reviews` row.** Deterministic facts live in `evidence_refs`, so the
   verdict is pinned to ground truth:
   ```json
   { "review_type": "tool_fidelity",
     "subject": "autonomous_loop 2026-06-17T14:00Z (factor-loop weekday)",
     "severity": "warn", "confidence": 0.9,
     "verdict": "Invariants honoured; run completed. 1/12 calls errored: get_quote timeout — transient, agent retried and succeeded.",
     "evidence_refs": { "run_id": "…", "trace_url": "…", "run_completed": true,
       "total_calls": 12, "failed_calls": 1, "success_rate": 0.917,
       "invariant_violations": [], "per_tool_errors": [{"tool":"get_quote","error":"timeout","count":1}],
       "recovery": [{"tool":"get_quote","action":"retried_ok"}],
       "runtime_ms": 41200, "token_usage": 78140, "redundant_calls": [] } }
   ```
2. **Standing patterns → `tool_fidelity:detail`** (provenance + confidence schema):
   ```json
   { "patterns": [ { "text": "record_daily_snapshot missing from afternoon factor-loop runs",
       "source_review_ids": ["r1","r2","r3"], "confidence": "established", "count": 3,
       "first_seen": "2026-06-12", "last_seen": "2026-06-17" } ] }
   ```
3. **Headline → `index`** — `{ "tool_fidelity": { "summary": "...", "count": 17, "last_seen": "…" } }`.
4. **Watermark → `tool_fidelity:watermark`** (code-managed cursor; also the natural home for the
   Tier-B rolling baseline):
   ```json
   { "graph": "autonomous_loop", "last_reviewed_start_time": "2026-06-17T14:00Z",
     "reviewed_run_ids": ["…capped recent ids for late-arrival dedup…"],
     "baseline": { "runtime_ms_p50": 38000, "token_usage_p50": 72000 } }
   ```

---

## 6. Skill structure — single skill, fork-ready seam

One skill, **trader-scoped**, `review-tool-fidelity`. No common/base skill (that would be a
single-use abstraction today, and skill-to-skill "calls" are fragile prose composition + a
non-routable helper the router could wrongly pick).

Instead, the genuinely shared **plumbing** is pushed into **code/tools** (the trace-analysis tool +
watermark helper), reused cleanly by `review-operation-success` too. The skill keeps a clear
internal **seam**: a "Target & expected choreography" section (graph name + per-phase invariants) at
the top, generic procedure below. When a second group is real, forking
`review-<group>-tool-fidelity` is a mechanical copy-swap-the-top-section, and it gets **isolated
memory + watermark for free** from the existing per-`review_type` namespace binding — no platform
change.

---

## 7. Components & responsibilities

| Component | Kind | Responsibility |
|---|---|---|
| `read_run_trace` (extend) | code/tool | Add graph-name filter (`autonomous_loop`, exclude reviewer) + subject/date targeting. Return ordered tool calls with `error` flags. |
| trace-analysis fn + tool (new) | code/tool | Pure: per-run facts → `{phase, invariant_violations[] (incl. forbidden), total_calls, failed_calls, success_rate, per_tool_errors[], recovery[] (per errored call: retried/fell_back/swallowed), run_completed (root error?), runtime_ms, slowest_calls[], token_usage, redundant_calls[]}`. Deterministic detection of all Tier-A/B facts; the LLM interprets. |
| per-phase invariants | code (config) | Authoritative required-steps + forbidden-tools + dependency constraints per phase. Documented in prose in the skill for the LLM's *interpretation*; the *check* is code. |
| watermark helper (new) | code/tool | Read last-reviewed cursor + reviewed run_ids + Tier-B rolling baseline from bound memory; advance on success. Target-stamped. |
| `review-tool-fidelity/SKILL.md` | skill | Orchestrate: `begin_review` → resolve subject (explicit or watermark sweep) → call analysis tool per new run → **interpret + judge severity** → `write_review` → consolidate → advance watermark. |

Memory binding uses the existing `begin_review("tool_fidelity")` per-type namespace; no binding
change.

---

## 8. Data flow (sweep mode)

```
cron / caller: "run a tool-fidelity sweep"   (trigger is OPEN — see §10)
  └─ begin_review("tool_fidelity", subject, reason)        # binds namespace
       └─ read watermark (last-reviewed run_ids for autonomous_loop)
            └─ read_run_trace(name=autonomous_loop, newer-than-watermark)  # graph-filtered
                 └─ for each new run:
                      analysis tool → {phase, invariant_violations, success_rate, per_tool_errors}
                      LLM interprets facts → severity + prose
                      write_review(review_type="tool_fidelity", subject=run, ...)
                      consolidate (record_insight / index) if recurring/significant
                      advance watermark (this run_id)       # success only
```

Explicit-subject mode skips the watermark and audits the named run directly.

---

## 9. Testing & validation

- **Unit (deterministic core):** the analysis fn is pure — test invariant detection (missing
  required step, dependency violation, benign reorder tolerated) and success-rate math against
  hand-built trace fixtures. The watermark helper: cold-start, late-arrival, advance-on-success.
- **`read_run_trace`:** graph-name filter (excludes `review_agent`), recency/date targeting.
- **End-to-end (honest limits):**
  - We will **fire one real local `autonomous_loop` run** to get a genuine trace with real tool
    calls, then run the skill against it.
  - **This validates the happy path only.** "Missing required step" / "errored tool" branches stay
    unverified until we engineer a trace that contains them (fabricated fixture or an intentionally
    broken run).
  - On existing synced data (no traces) the skill correctly returns "no trace — cannot audit"; its
    live coverage is ~zero until trace ingestion flows for real runs.

---

## 10. Open decisions

- **Trigger / cadence — UNDECIDED.** The watermark makes the skill cadence-agnostic, so this is a
  pure cost/latency knob to pick later (per-loop / daily / weekly / manual). Not a blocker.
- **Severity thresholds** — exact mapping (e.g. missing required step → `fail`; success-rate < X →
  `warn`) to be set as sensible defaults in the implementation plan, tuned against the first real
  run.

---

## 11. Self-review

- **Placeholder scan:** none — no TBD/TODO; the one explicit unknown (trigger cadence, §10) is a
  consciously deferred decision, not a gap.
- **Consistency:** "tool-call failure" defined once (§3d) and used consistently in the success-rate
  dimension; "invariants not golden sequence" (§3b) consistent with the analysis-fn output (§7);
  watermark semantics (§5) consistent with data flow (§8); the Tier-A/B dimensions (§3c) match the
  analysis-fn facts (§7) and the verdict `evidence_refs` (§5 memory shape); Tier-B is explicitly
  non-failing (§3c) with its baseline stored in the watermark (§5).
- **Scope:** focused on one skill + its enabling plumbing; shared plumbing noted as reused by
  operation-success but that skill's redesign is out of scope. Dimensions are bounded — argument
  *appropriateness* explicitly excluded (§3c) to prevent decision-quality/conformance creep.
- **Ambiguity:** "group" fixed to mean *graph/agent under audit* (§4/§6); phase handled within the
  one skill (§3b), not as separate groups.

---

## 12. Next step

On approval → `superpowers:writing-plans` to turn this into a TDD implementation plan (analysis fn +
watermark + `read_run_trace` extension + skill, each test-first), then fire the validation run.
