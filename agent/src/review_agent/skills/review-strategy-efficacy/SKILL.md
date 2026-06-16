---
name: review-strategy-efficacy
description: >
  Audit whether the STRATEGY is actually working and whether the agent is being honest or
  rationalizing underperformance. Use when asked if factor weights are earning their keep,
  whether live alpha tracks the backtest, or whether the agent is ignoring its own flagged
  signals. Do NOT use for hard-rule compliance (use review-strategy-conformance), reasoning
  quality or bias in individual decisions (use review-decision-quality), or tool-call
  ordering / correctness (use review-tool-fidelity).
memory_namespace: efficacy
memory_access: { read: own, write: own }
tags: [strategy, rationalization]
---

# Review: Strategy Efficacy

Audit whether the STRATEGY is adding real value and whether the agent is being honest with itself
about what the numbers say.

## CRITICAL — Do NOT recompute alpha, IC, or divergence

The trader's own tools already produce these numbers. Your job is to READ the existing numbers
and JUDGE whether the agent is drawing honest conclusions from them — not to replicate the math.
Recomputing creates inconsistency and wastes a run.

## Step 0 — begin + self-announce / fit-check
Call `begin_review("efficacy", subject="<run id / date / period>", reason="<why efficacy>")`
FIRST — it binds your memory to this review and returns your bounded prior-context. Then state:
"Running a STRATEGY EFFICACY review of {subject}." If the request is really about rule compliance,
individual reasoning quality, or tool-call ordering, STOP and route to the right skill (or
`review-general`).

## Step 1 — treat priors as priors (not truth)
The prior-context from begin_review (standing efficacy patterns + recent verdicts + global
insights) is PRIORS only. Re-read ground truth below; if a prior conflicts with this run's
evidence, the evidence wins. Treat insights tagged "(unconfirmed)" cautiously.

## Step 2 — pull ground-truth evidence (READ; do not recompute)
Use `query_database` to read pre-computed numbers:
- `equity_snapshots` — live portfolio equity, SPY close, cumulative returns, alpha (30-day
  annualized)
- `factor_ic_runs` — IC per factor per horizon (variant_name="live_audit"), recent rows
- `backtest_runs` — annualized backtest alpha for the BASELINE_VARIANT

Use `read_agent_memory` / `read_all_agent_memory` for:
- `strategy_health` — the trader's own audit summary (flagged factors, SIGN FLIP, DRAG, etc.)
- `strategy_divergence` — live vs backtest alignment status
- `factor_weights` — current weights the agent is running
- `factor_rankings` — most recent scoring snapshot

Use `query_database` for `agent_journal` to read the agent's OWN conclusions from weekly-review
entries — specifically what it said about factor performance and any weight changes it made or
declined to make.

## Step 3 — judge honesty and efficacy
Answer each question with evidence:

1. **Is the strategy adding value?**
   Read `equity_snapshots` alpha and `strategy_divergence`. Is live alpha positive? Aligned with
   backtest? `major_underperformance` for ≥ 4 weeks is a red flag.

2. **Are the factor ICs earning their weights?**
   From `factor_ic_runs` (live_audit): is any factor showing SIGN FLIP or DRAG across ≥ 3 audits?
   Does the current `factor_weights` allocation match the IC evidence, or is a dead-weight factor
   over-allocated?

3. **Is the agent rationalizing?**
   Cross-check the agent's weekly-review journal against the hard numbers. Red flags:
   - IC negative for a factor ≥ 3 consecutive audits AND agent kept / raised its weight, citing
     "regime" or "short window" without new evidence.
   - Live alpha negative but agent claimed "in line with strategy" without citing divergence status.
   - Agent flagged a signal in `strategy_health` (SIGN FLIP, SIGNIFICANCE LOSS) but took no action
     and gave no documented reason.

4. **Short-window overfitting?**
   Did the agent adjust weights based on only 1–2 weeks of data, then reverse them the next week?
   That is overfitting, not adaptation.

5. **Ignored self-flags?**
   `strategy_health` is written by the trader's own `audit_factor_ic()`. If a factor was flagged
   DRAG or SIGN FLIP and the agent's journal shows no acknowledgment, that is a rationalization
   failure.

## Step 4 — verdict
Decide an overall `severity`: `pass` (strategy evidence-based, agent honest), `warn` (one
unaddressed flag or mild rationalization), or `fail` (repeated rationalization, ignored signals,
clear strategy drag unacknowledged).
Record it:
`write_review(review_type="efficacy", subject="<run/period>", verdict="<prose with specifics>",
severity="<pass|warn|fail>", confidence=<0-1>, evidence_refs={...})`

## Step 5 — consolidate (REQUIRED)
- For each RECURRING or MATERIALLY SIGNIFICANT finding (e.g. agent rationalizing a dead factor
  across ≥ 2 weekly reviews), call
  `record_insight(text="<standing observation>", source_review_ids=[<this + related review ids>])`.
  Discard one-off noise — a single soft excuse is not worth recording.
- Update the index headline: `write_reviewer_memory(scope="index", value={...})` — a one-line
  summary + count + last-seen for "efficacy".
- If a rationalization pattern also shows up in decision-quality reviews (the same ignored signals
  appear there too), call `promote_to_global(text, justification, corroborating_review_ids)`
  (requires ≥ 2 reviews from different namespaces).
- Write only via the bound scopes — never a raw namespace, never another task's detail.
