---
name: review-tool-fidelity
description: >
  Audit whether an autonomous_loop run followed its prescribed tool choreography — required
  tools present, forbidden tools absent, dependency-ordering honoured, the run completed, errors
  recovered, and the tool-call success rate. Use when asked if the agent followed its process,
  skipped a step, called tools out of order, or whether tool calls are erroring. Do NOT use for
  whether operations completed/filled (use review-operation-success), hard-rule compliance (use
  review-strategy-conformance), reasoning or bias (use review-decision-quality), or strategy
  efficacy (use review-strategy-efficacy).
memory_namespace: tool_fidelity
memory_access: { read: own, write: own }
tags: [process, tools, trace]
---

# Review: Tool Fidelity

Audit process adherence for the trader (`autonomous_loop`), from its LangSmith trace. You judge
whether the prescribed tool choreography was followed — not outcomes, rules, or reasoning.

**Detection is deterministic — `get_tool_fidelity_runs` computes the facts.** Your job is to
INTERPRET those facts (is an error transient or real?), judge severity, and consolidate. Do not
eyeball the raw trace or re-count anything the tool already counted.

## Step 0 — begin + fit-check
Call `begin_review("tool_fidelity", subject="<run id / date / 'sweep'>", reason="<why tool-fidelity>")`
FIRST — it binds your memory and returns prior context. State: "Running a TOOL FIDELITY review of
{subject}." If the request is about whether operations *succeeded* (fills, snapshots saved), route
to `review-operation-success`; for rule compliance or reasoning, route accordingly or use
`review-general`.

## Step 1 — treat priors as priors
Prior context (standing skip/error patterns + recent verdicts) is PRIORS only. The freshly-computed
facts are ground truth; if a prior conflicts with this run's facts, the facts win. Treat
"(unconfirmed)" insights cautiously.

## Step 2 — get the facts
Call `get_tool_fidelity_runs()` (sweep — returns trader runs newer than your watermark) or
`get_tool_fidelity_runs(subject="<run_id>")` for a specific run. Each run returns:
`{run_id, start_time, facts}` where `facts` holds `phase`, `run_completed`, `invariant_violations`,
`total_calls`/`failed_calls`/`success_rate`, `per_tool_errors`, `recovery`, `redundant_calls`,
`runtime_ms`, `token_usage`. If no runs are returned, there is nothing un-reviewed — say so and stop.
If a run has no trace / no tool calls, say you cannot audit it (confidence 0) — do not invent.

## Step 3 — interpret each run (two tiers)
**Tier A — correctness (drives severity):**
1. **Invariants** — any `invariant_violations`? A `missing_required` or `forbidden_present` is
   serious; weigh `order_violation`/`missing_terminal` in context.
2. **Success rate** — interpret `per_tool_errors`: is a failure transient (a quote timeout) or a
   real process break (a persistent tool exception)?
3. **Recovery** — in `recovery`, a `swallowed` error on a consequential tool (e.g. `place_order`)
   is a key finding; `retried_ok` is healthy.
4. **Run completion** — `run_completed == false` (the loop crashed) is a major failure.

**Tier B — observability (NEVER a standalone fail; `info`/`warn` at most):**
5. **Runtime / tokens** — only flag an *egregious* anomaly relative to recent norms; absolute
   numbers alone are not a finding.
6. **Redundant calls** — a soft note, not a severity driver.

## Step 4 — verdict (per run)
`write_review(review_type="tool_fidelity", subject="<run_id> (<phase>)", verdict="<prose citing the
facts>", severity="<pass|info|warn|fail>", confidence=<0-1>, evidence_refs={...the facts you relied
on: run_id, success_rate, invariant_violations, ...})`. Lower confidence if `phase=="unknown"` or
the trace was partial. Tier B alone never yields `fail`.

Then call `mark_run_reviewed(run_id, start_time)` — ONLY after the verdict is written, so a failed
review re-audits the run next time.

## Step 5 — consolidate (selective)
- For a RECURRING or MATERIALLY SIGNIFICANT pattern (e.g. `record_daily_snapshot` missing across
  afternoon runs; a tool erroring every run), call `record_insight(text="<standing observation>",
  source_review_ids=[<this + related ids>])`. Discard one-off noise.
- Update the headline: `write_reviewer_memory(scope="index", value={...})` — one-line summary +
  count + last-seen for "tool_fidelity".
- If a skip also shows up as a failed operation in `review-operation-success`, call
  `promote_to_global(text, justification, corroborating_review_ids)` (>= 2 reviews).
- Write only via the bound scopes — never a raw namespace, never another task's detail. The
  watermark advances via `mark_run_reviewed`, not by you writing memory.
