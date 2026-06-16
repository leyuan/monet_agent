---
name: review-tool-fidelity
description: >
  Audit whether a run called the RIGHT tools in the RIGHT ORDER and whether any were silently
  skipped or errored. Use when asked if the agent followed its prescribed tool sequence, missed
  a required step, or called tools out of order. Do NOT use for outcome rule compliance (use
  review-strategy-conformance), reasoning or bias in decisions (use review-decision-quality),
  strategy efficacy (use review-strategy-efficacy), or whether individual operations actually
  completed / succeeded (use review-operation-success).
memory_namespace: tool_fidelity
memory_access: { read: own, write: own }
tags: [process, tools]
---

# Review: Tool Fidelity

Audit whether a run called the correct tools in the correct order per its phase. You judge
process adherence, not outcomes.

**Note:** This skill requires a LangSmith trace to be maximally useful. Results will be
limited / low-confidence if tracing is not yet flowing for the run under review.

## Step 0 — begin + self-announce / fit-check
Call `begin_review("tool_fidelity", subject="<run id / date>", reason="<why tool-fidelity>")`
FIRST — it binds your memory to this review and returns your bounded prior-context. Then state:
"Running a TOOL FIDELITY review of {subject}." If the request is about whether operations
succeeded (fills, snapshots saved), route to `review-operation-success`. If about rule compliance
or reasoning quality, route accordingly or use `review-general`.

## Step 1 — treat priors as priors (not truth)
The prior-context from begin_review (standing tool-skip patterns + recent verdicts + global
insights) is PRIORS only. The actual trace is ground truth; if a prior says "step X is always
skipped" but the trace shows it ran, the trace wins. Treat insights tagged "(unconfirmed)"
cautiously.

## Step 2 — pull ground-truth evidence
Primary: `read_run_trace` for the subject run — this returns the actual tool-call sequence, each
call's arguments, and any error flags or exceptions.
Supplementary: `query_database` for `agent_journal` to see which phase the run was executing
(factor-loop weekday / weekend / reflection / weekly-review), which determines the expected
sequence.

## Step 3 — compare actual vs expected sequence

### Expected tool sequence by run phase

**Factor-loop (weekday execution — Mon/Tue/Thu/Fri 10am + 1pm Toronto):**
```
score_universe
  → enrich_eps_revisions          (on top candidates)
  → generate_factor_rankings
  → [earnings guard check]        (read earnings proximity for BUY candidates)
  → place_order(s)                (for each BUY/SELL signal above threshold)
  → record_decision               (per order)
  → write_journal_entry           (trade + reasoning)
  → update_stock_analysis         (memory: stock:SYMBOL for bought/sold)
  → record_daily_snapshot         (or equivalent equity snapshot)
```

**Factor-loop (weekend — Sat 11am):**
```
score_universe
  → enrich_eps_revisions
  → generate_factor_rankings
  [NO place_order — no execution on weekends]
  → write_journal_entry           (rankings summary)
```

**EOD Reflection (4pm weekday):**
```
check_live_vs_backtest_divergence
  → query_database (equity_snapshots, trades today)
  → write_journal_entry (reflection)
  → update_market_regime          (optional, if VIX data fresh)
  → write_reviewer_memory / write_agent_memory (strategy_divergence)
```

**Weekly Review (Sunday):**
```
audit_factor_ic
  → suggest_factor_weight_adjustment
  → query_database (backtest_runs, equity_snapshots, trades past week)
  → write_journal_entry (weekly summary)
  → write_agent_memory (factor_weights if adjusted)
```

### Checks to perform
For the actual trace vs the expected sequence above:
1. **Missing required tools** — any tool in the expected sequence not present in the trace?
   Flag each absence with which step it was.
2. **Out-of-order calls** — e.g. `place_order` before `generate_factor_rankings`, or
   `record_daily_snapshot` called before trades?
3. **Errored tool calls** — any tool call in the trace that returned an error or exception?
   Note: an error is not the same as a failed operation — that is `review-operation-success`.
   Here you flag that the call threw (process broke), not whether the underlying op completed.
4. **Unexpected extra calls** — tool calls not in the expected sequence that are not obviously
   supplementary (e.g. extra `score_universe` mid-run without explanation).

## Step 4 — verdict
Decide an overall `severity`: `pass` (sequence correct, no errors), `warn` (non-critical step
skipped or minor reordering), or `fail` (required step absent or tool errored critically).
Record it:
`write_review(review_type="tool_fidelity", subject="<run/date>", verdict="<prose with specifics>",
severity="<pass|warn|fail>", confidence=<0-1>, evidence_refs={...})`

Lower confidence if the trace was unavailable or partial.

## Step 5 — consolidate (REQUIRED)
- For each RECURRING or MATERIALLY SIGNIFICANT finding (e.g. `record_daily_snapshot` consistently
  missing from afternoon runs), call
  `record_insight(text="<standing observation>", source_review_ids=[<this + related review ids>])`.
  Discard one-off noise — a single missing supplementary call is not worth recording.
- Update the index headline: `write_reviewer_memory(scope="index", value={...})` — a one-line
  summary + count + last-seen for "tool_fidelity".
- If a systematic skip also surfaces as a failed operation in `review-operation-success` reviews,
  call `promote_to_global(text, justification, corroborating_review_ids)` (requires ≥ 2 reviews).
- Write only via the bound scopes — never a raw namespace, never another task's detail.
