---
name: review-strategy-conformance
description: >
  Audit whether a trading run obeyed Monet's HARD RULES (regime gate, 5-day anti-churn,
  position/cash limits, earnings guard, stops, AI soft caps). Use when asked to review a
  run/period for rule compliance, discipline, or "did it follow strategy". Do NOT use for
  reasoning quality (use review-decision-quality), strategy efficacy (use
  review-strategy-efficacy), or tool-call correctness (use review-tool-fidelity).
memory_namespace: conformance
memory_access: { read: own, write: own }
tags: [rules, process, discipline]
---

# Review: Strategy Conformance

Audit whether a trading run OBEYED Monet's hard rules. You judge against the rules; you do
not second-guess the strategy itself.

## Step 0 — begin + self-announce / fit-check
Call `begin_review("conformance", subject="<run id / date>", reason="<why conformance>")` FIRST —
it binds your memory to this review and returns your bounded prior-context. Then state:
"Running a CONFORMANCE review of {subject}." If the request is really about reasoning quality,
strategy efficacy, or tool-call correctness, STOP and route to the right skill (or `review-general`).

## Step 1 — treat priors as priors (not truth)
The prior-context from begin_review (standing conformance patterns + recent verdicts + global
insights) is PRIORS only. Re-read ground truth below; if a prior conflicts with this run's
evidence, the evidence wins. Treat insights tagged "(unconfirmed)" cautiously.

## Step 2 — pull ground-truth evidence
Use `query_database` for the subject run/period:
- `trades` — symbol, side, quantity, created_at, status, filled_avg_price, stop_loss_price
- `agent_journal` — the run's market_scan / trade entries
- `agent_memory` — decisions (`decision:*`) and `factor_rankings`
Optionally use `read_run_trace` to see what actually executed.

## Step 3 — check each hard rule → PASS / WARN / FAIL with evidence
1. **Regime gate** — if VIX > 26 AND breadth < 30%, were new BUYs blocked?
2. **Anti-churn** — any SELL inside the 5-day minimum hold? rapid re-entry?
3. **Position count** — holdings within 5–8?
4. **Position size** — any position > 10% of equity?
5. **Cash buffer** — ≥ 20% cash maintained?
6. **Earnings guard** — any BUY within 5 days of earnings?
7. **Stops** — does every new position have a stop?
8. **AI soft caps** — if AI durability/bubble is high, ≤ 1 new AI buy?

## Step 4 — verdict
Decide an overall `severity`: `pass` (all clean), `warn` (minor / soft-rule), or `fail` (a hard
rule broken). Record it:
`write_review(review_type="conformance", subject="<run/date>", verdict="<prose with specifics>",
severity="<pass|warn|fail>", confidence=<0-1>, evidence_refs={...})`

## Step 5 — consolidate (REQUIRED)
- For each RECURRING or MATERIALLY SIGNIFICANT finding, call
  `record_insight(text="<standing observation>", source_review_ids=[<this + related review ids>])`.
  This merges it into conformance's standing detail with provenance; confidence hardens with
  corroboration. Discard one-off noise — do NOT record trivia.
- Update the index headline: `write_reviewer_memory(scope="index", value={...})` — a one-line
  summary + count + last-seen for "conformance".
- If a finding generalizes to ALL review types (e.g. a systematic bias), call
  `promote_to_global(text, justification, corroborating_review_ids)` (requires ≥ 2 reviews).
- Write only via the bound scopes — never a raw namespace, never another task's detail.
