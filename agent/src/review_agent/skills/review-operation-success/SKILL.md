---
name: review-operation-success
description: >
  Audit whether each OPERATION an autonomous_loop run attempted actually completed — orders
  filled, snapshots saved, memory/journal writes landed, emails sent — by joining the run's
  LangSmith trace to the trader's Supabase tables. Use when asked if a run's side-effects
  succeeded or whether something silently failed. Do NOT use for tool-call ordering or whether
  a call errored (use review-tool-fidelity), hard-rule compliance (use review-strategy-conformance),
  reasoning or bias (use review-decision-quality), or strategy efficacy (use review-strategy-efficacy).
memory_namespace: operation_success
memory_access: { read: own, write: own }
tags: [process, execution, trace]
---

# Review: Operation Success

Audit whether each operation a run ATTEMPTED actually LANDED. A tool can return OK while its
durable effect silently fails (order rejected at the broker, a write that never persisted). You
judge execution OUTCOMES — not tool ordering, not rule compliance, not reasoning.

**Detection is deterministic — `get_operation_success_runs` computes the facts** (trace × DB join).
Your job is to INTERPRET them (is this silent failure material or a one-off?), judge severity, and
consolidate. Do not hand-write SQL or re-derive a status the tool already computed.

## Step 0 — begin + fit-check
Call `begin_review("operation_success", subject="<run id / date / 'sweep'>", reason="<why operation-success>")`
FIRST — it binds your memory and returns prior context. State: "Running an OPERATION SUCCESS review
of {subject}." If the request is about WHICH tools were called or in what order, route to
`review-tool-fidelity`; for rule compliance or reasoning, route accordingly or use `review-general`.

## Step 1 — treat priors as priors
Prior context (standing operation-failure patterns + recent verdicts) is PRIORS only. The
freshly-computed facts are ground truth; if a prior conflicts with this run's facts, the facts win.
Treat "(unconfirmed)" insights cautiously.

## Step 2 — get the facts
Call `get_operation_success_runs()` (sweep — runs newer than your watermark) or
`get_operation_success_runs(subject="<run_id>")` for a specific run. Each run returns
`{run_id, start_time, run_severity, operations:[{tool, status, severity, detail, evidence}]}`.
If no runs are returned, there is nothing un-reviewed — say so and stop. If a run has no operations,
say there were no side-effects to audit (do not invent).

## Step 3 — interpret each operation
Statuses and what they mean:
- `landed` / `rejected_expected` — success. A guardrail rejection (risk check / anti-churn) is the
  system working, NOT a failure.
- `partial` — partial fill or partial multi-write. Note it; judge whether material.
- `degraded` — the row landed but its content looks wrong (e.g. snapshot `spy_close=0`). Worth a
  finding when it recurs.
- `silent_failure` — the headline catch: returned OK but no fresh row. On `place_order` /
  `record_daily_snapshot` this is critical; elsewhere it is a warning unless recurring.
- `rejected_unexpected` / `errored_unrecovered` — a real failure the run did not recover from.
- `unverifiable` — could not confirm (trace-only op, no identifier, or an unknown tool). LOWER your
  confidence; never turn absence of evidence into a `fail`. An `unclassified` tool means the registry
  needs updating — call that out.

## Step 4 — verdict (per run)
`write_review(review_type="operation_success", subject="<run_id> (<date>)", verdict="<prose citing the
operations + statuses>", severity="<pass|info|warn|fail>", confidence=<0-1>, evidence_refs={...the
operations you relied on})`. Default the severity to the tool's `run_severity`, adjusting only with a
stated reason (e.g. a single transient email error you judge immaterial). `unverifiable`-heavy runs
get lower confidence. Then call `mark_run_reviewed(run_id, start_time)` — ONLY after the verdict is
written, so a failed review re-audits the run next time.

## Step 5 — consolidate (selective)
- For a RECURRING or MATERIALLY SIGNIFICANT pattern (e.g. `record_daily_snapshot` silently missing
  across afternoon runs; memory writes consistently stale), call `record_insight(text="<standing
  observation>", source_review_ids=[<this + related ids>])`. Discard one-off noise.
- Update the headline: `write_reviewer_memory(scope="index", value={...})` — one-line summary +
  count + last-seen for "operation_success".
- If a silent failure here also shows up as a skipped/missing tool in `review-tool-fidelity`, call
  `promote_to_global(text, justification, corroborating_review_ids)` (>= 2 reviews).
- Write only via the bound scopes — never a raw namespace, never another task's detail. The
  watermark advances via `mark_run_reviewed`, not by you writing memory.
