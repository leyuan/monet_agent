---
name: review-operation-success
description: >
  Audit whether each intended OPERATION actually completed — orders filled vs rejected, snapshots
  saved, memory and journal writes landed, emails sent without error. Use when asked if a run's
  side-effects succeeded or whether something silently failed. Do NOT use for tool-call ordering
  (use review-tool-fidelity), hard-rule compliance (use review-strategy-conformance), reasoning
  quality (use review-decision-quality), or strategy efficacy (use review-strategy-efficacy).
memory_namespace: operation_success
memory_access: { read: own, write: own }
tags: [process, execution]
---

# Review: Operation Success

Audit whether each operation a run ATTEMPTED actually completed. You judge execution outcomes,
not process ordering and not rule compliance.

## Step 0 — begin + self-announce / fit-check
Call `begin_review("operation_success", subject="<run id / date>", reason="<why operation-success>")`
FIRST — it binds your memory to this review and returns your bounded prior-context. Then state:
"Running an OPERATION SUCCESS review of {subject}." If the request is about WHICH tools were
called or in what order, route to `review-tool-fidelity`. If about rule compliance or reasoning,
route accordingly or use `review-general`.

## Step 1 — treat priors as priors (not truth)
The prior-context from begin_review (standing operation-failure patterns + recent verdicts +
global insights) is PRIORS only. Database state and trace outputs are ground truth; if a prior
says "snapshots always save" but the database shows no row for today, the database wins. Treat
insights tagged "(unconfirmed)" cautiously.

## Step 2 — pull ground-truth evidence
Primary: `read_run_trace` — read each tool call's OUTPUT and whether it returned an error flag.
A tool call can succeed (no error thrown) while the underlying operation failed (e.g. Alpaca
rejected the order). Check both.
Cross-check with `query_database`:
- `trades` — status, filled_avg_price, broker_order_id (confirm fills vs rejections/partials)
- `equity_snapshots` — confirm a row exists for the run's date
- `agent_journal` — confirm entries were written for the run
- `agent_memory` — confirm memory keys updated (decision:*, stock:*, strategy_divergence)

## Step 3 — check each intended operation

For every operation the run trace shows was ATTEMPTED:

1. **Order fills** — for each `place_order` call:
   - Check `trades` table: status == "filled" and filled_avg_price populated?
   - If status == "rejected" or "cancelled", was the rejection expected (risk check failed) or
     unexpected (broker error, bad parameters)?
   - Any partial fills? Note quantity vs filled quantity.

2. **Equity snapshot** — was `record_daily_snapshot` (or equivalent) called AND does a row exist
   in `equity_snapshots` for the run date? A missing row means silent failure even if no error
   was thrown.

3. **Memory writes** — for each `write_agent_memory` / `update_stock_analysis` /
   `update_market_regime` / `record_decision` call in the trace, confirm the corresponding key
   exists in `agent_memory` with a recent timestamp. A call that returned OK but didn't persist
   is a silent write failure.

4. **Journal writes** — for each `write_journal_entry` call, confirm entries exist in
   `agent_journal` for the run with the expected type (trade, reflection, research, etc.) and
   recent timestamp.

5. **Email / notification sends** — if the run attempted to send a notification or email, did
   the trace show a success response? Note any error codes.

6. **Risk-check rejections (expected)** — if `place_order` was rejected by the internal risk
   check, that is NOT a failure; it is expected behavior. Distinguish from unexpected broker
   rejections.

## Step 4 — verdict
Decide an overall `severity`: `pass` (all operations completed or rejections were expected),
`warn` (one non-critical operation silently failed), or `fail` (order not filled unexpectedly,
snapshot missing, persistent memory write lost).
Record it:
`write_review(review_type="operation_success", subject="<run/date>", verdict="<prose with specifics>",
severity="<pass|warn|fail>", confidence=<0-1>, evidence_refs={...})`

## Step 5 — consolidate (REQUIRED)
- For each RECURRING or MATERIALLY SIGNIFICANT finding (e.g. snapshots missing for 3 consecutive
  EOD runs, orders consistently partially filled), call
  `record_insight(text="<standing observation>", source_review_ids=[<this + related review ids>])`.
  Discard one-off noise — a single unexpected partial fill on a thinly traded stock is not worth
  recording.
- Update the index headline: `write_reviewer_memory(scope="index", value={...})` — a one-line
  summary + count + last-seen for "operation_success".
- If a recurring operation failure also shows up as a missing tool call in `review-tool-fidelity`
  reviews (i.e. the step was never called AND the data never landed), call
  `promote_to_global(text, justification, corroborating_review_ids)` (requires ≥ 2 reviews).
- Write only via the bound scopes — never a raw namespace, never another task's detail.
