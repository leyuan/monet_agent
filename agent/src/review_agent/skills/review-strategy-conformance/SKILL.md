---
name: review-strategy-conformance
description: >
  Audit whether an autonomous run obeyed the DECLARED strategy (point-in-time): anti-churn
  min-hold, position-count band, factor-weight conformance, stops-present, regime hard-block.
  Deterministic facts come from get_strategy_conformance_runs; you judge severity and write the
  verdict. Use for rule compliance / discipline / "did it follow strategy". NOT for reasoning
  quality (review-decision-quality), efficacy (review-strategy-efficacy), tool correctness
  (review-tool-fidelity), or persistence (review-operation-success).
memory_namespace: conformance
memory_access: { read: own, write: own }
tags: [rules, process, discipline]
---

# Review: Strategy Conformance

You audit whether a run OBEYED the declared strategy. You judge against the rules as the tool
resolved them (point-in-time); you never hand-derive thresholds and never second-guess the
strategy itself.

## Step 0 — begin + fit-check
Call `begin_review("conformance", subject="<run id / date>", reason="<why conformance>")` FIRST —
it binds your memory and returns your bounded prior-context. Then state:
"Running a CONFORMANCE review of {subject}." If the request is really about reasoning quality,
efficacy, tool correctness, or persistence, STOP and route to the right skill (or `review-general`).

## Step 1 — treat priors as priors
The prior-context is PRIORS only. The deterministic facts below are ground truth; if a prior
conflicts with this run's facts, the facts win. Treat "(unconfirmed)" insights cautiously.

## Step 2 — pull the deterministic facts
Call `get_strategy_conformance_runs()` (sweep — runs newer than the watermark) or
`get_strategy_conformance_runs(subject="<run_id>")` (one run). For each run you get
`run_severity` and a `rules` list; each rule has `status`
(`conformant | violated | unverifiable`), `severity`, `detail`, `evidence`. The numbers are
already computed against the strategy in force when the run ran — do not recompute them.

## Step 3 — interpret, don't recompute
Read each rule's `status`/`evidence` and explain the run in plain terms:
- `violated` + `fail` (anti_churn, stops_present, regime_gate) → a hard discipline breach. Name the
  specific trade(s) from `evidence`.
- `violated` + `warn` (position_count, factor_weights_conformance) → a soft slip. Note it; don't
  inflate it to a fail.
- `unverifiable` → say plainly what couldn't be checked and why (from `detail`); it must NOT lower
  the verdict to a fail, only the confidence.
A clean run (all `conformant`, the rest `unverifiable`) is a `pass`.

## Step 4 — verdict
Use the tool's `run_severity` as your severity (do not soften a computed `fail`). Record it:
`write_review(review_type="conformance", subject="<run/date>", verdict="<prose with the specific
violating trades + which rules were unverifiable and why>", severity="<pass|info|warn|fail>",
confidence=<0-1, lower it when key rules were unverifiable>, evidence_refs={"run_id":..., "rules":...})`.

## Step 5 — consolidate (REQUIRED)
- For each RECURRING or MATERIALLY SIGNIFICANT finding, call
  `record_insight(text="<standing observation>", source_review_ids=[<this + related ids>])`.
  Discard one-off noise.
- Update the index headline: `write_reviewer_memory(scope="index", value={...})` — one-line
  summary + count + last-seen for "conformance".
- If a finding generalizes to ALL review types, call `promote_to_global(text, justification,
  corroborating_review_ids)` (requires ≥ 2 reviews).
- Write only via the bound scopes — never a raw namespace, never another task's detail.

## Step 6 — advance the watermark
For each run reviewed, call `mark_run_reviewed(run_id, start_time)` so a re-run audits only new runs.

## What this skill does NOT check
- Process / tool sequence → `review-tool-fidelity`.  · Persistence of effects → `review-operation-success`.
- Reasoning quality → `review-decision-quality`.       · Did it make money → `review-strategy-efficacy`.

## v1 limits (honest degradation, by design)
- `risk_limit_leak` (size/exposure/daily-loss/earnings) is `unverifiable` in v1 — needs point-in-time
  equity / earnings not durably stored (see `PROPOSAL-strategy-spec.md`).
- `regime_gate` checks the hard-block only; the caution-tier size-reduction is deferred.
- `sell_justification` / `ai_soft_caps` are `unverifiable` — the inputs aren't persisted.
- Thresholds come from the declared, effective-dated spec resolved by the tool — never hardcode them here.
