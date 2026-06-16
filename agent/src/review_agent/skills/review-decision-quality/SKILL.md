---
name: review-decision-quality
description: >
  Audit whether the agent's REASONING was sound and its decisions were justified by the evidence
  it cited. Use when asked to judge reasoning quality, detect systematic bias (always bullish,
  always waiting, confirmation bias, anchoring, over-trading), or evaluate whether decisions were
  logically grounded. Do NOT use for hard-rule compliance (use review-strategy-conformance),
  strategy efficacy / whether the strategy is working (use review-strategy-efficacy), or
  tool-call ordering / correctness (use review-tool-fidelity).
memory_namespace: decision_quality
memory_access: { read: own, write: own }
tags: [reasoning, bias, behavioral]
---

# Review: Decision Quality

Audit whether the agent's decisions were LOGICALLY JUSTIFIED and free of systematic bias. You
judge the reasoning, not the outcome — a well-reasoned decision that lost money can still PASS.

## Step 0 — begin + self-announce / fit-check
Call `begin_review("decision_quality", subject="<run id / date>", reason="<why decision-quality>")`
FIRST — it binds your memory to this review and returns your bounded prior-context. Then state:
"Running a DECISION QUALITY review of {subject}." If the request is really about rule compliance,
strategy efficacy, or tool-call ordering, STOP and route to the right skill (or `review-general`).

## Step 1 — treat priors as priors (not truth)
The prior-context from begin_review (standing bias patterns + recent verdicts + global insights)
is PRIORS only. Re-read ground truth below; if a prior conflicts with this run's evidence, the
evidence wins. Treat insights tagged "(unconfirmed)" cautiously.

## Step 2 — pull ground-truth evidence
Use `query_database` for the subject run/period:
- `agent_journal` — the run's stated reasoning (research, analysis, trade entries)
- `agent_memory` — `decision:*` records (action, reasoning, confidence, evidence cited)
- `trades` — what was actually executed (symbol, side, confidence, thesis)
Optionally use `read_run_trace` to see the full reasoning trace, which may reveal reasoning
that was never written to the journal.

## Step 3 — assess reasoning quality and bias
For each decision the run made (BUY, SELL, HOLD, pass/wait):

1. **Evidence justification** — Was the decision supported by evidence explicitly cited in the
   reasoning? Or did it leap to a conclusion without citing data? Flag unsupported leaps.

2. **Logical coherence** — Given the evidence cited, does the conclusion follow? E.g. "revenue
   beat but guided down → held position" is coherent. "Revenue beat → bought more despite VIX 28
   and no breadth check" is a gap.

3. **Confirmation bias** — Did the reasoning only cite supporting data while ignoring contrary
   signals the tools surfaced? (E.g. EPS revision negative but agent focused only on price momentum.)

4. **Anchoring** — Did the agent anchor to a prior thesis or price target even when new data
   contradicted it?

5. **Systematic optimism / pessimism** — Across the run (or across recent runs per priors), is
   the agent always bullish? Always finding reasons to wait? Flag if a pattern holds across ≥ 2
   consecutive runs.

6. **Over-trading / under-trading** — Did the agent churn positions without new information, or
   conversely, refuse to act on strong signals citing vague uncertainty?

Rate each decision: JUSTIFIED / WEAK (logic present but thin) / UNJUSTIFIED. Flag any systematic
patterns.

## Step 4 — verdict
Decide an overall `severity`: `pass` (reasoning sound, no significant bias), `warn` (reasoning
thin or a soft bias pattern), or `fail` (clear logical gaps, confirmed systematic bias).
Record it:
`write_review(review_type="decision_quality", subject="<run/date>", verdict="<prose with specifics>",
severity="<pass|warn|fail>", confidence=<0-1>, evidence_refs={...})`

## Step 5 — consolidate (REQUIRED)
- For each RECURRING or MATERIALLY SIGNIFICANT finding (e.g. confirmation bias pattern spanning
  multiple runs, systematic optimism), call
  `record_insight(text="<standing observation>", source_review_ids=[<this + related review ids>])`.
  Discard one-off noise — do NOT record a single isolated weak decision.
- Update the index headline: `write_reviewer_memory(scope="index", value={...})` — a one-line
  summary + count + last-seen for "decision_quality".
- If a bias finding generalizes across ALL review types (e.g. the agent systematically ignores
  negative signals across domains), call
  `promote_to_global(text, justification, corroborating_review_ids)` (requires ≥ 2 reviews).
- Write only via the bound scopes — never a raw namespace, never another task's detail.
