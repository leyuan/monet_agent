---
name: review-general
description: >
  Safe fallback for ambiguous, novel, or out-of-category review requests. Use when no specific
  review skill clearly fits, or when the request spans multiple domains. Also handles REFUSALS
  for requests that ask the reviewer to act outside its mandate. Do NOT use when a specific skill
  clearly applies: use review-strategy-conformance for rule compliance, review-decision-quality
  for reasoning and bias, review-strategy-efficacy for strategy performance, review-tool-fidelity
  for tool-call ordering, or review-operation-success for operation completion.
memory_namespace: general
memory_access: { read: own, write: own }
tags: [fallback]
---

# Review: General (Fallback)

Handle ambiguous review requests and out-of-mandate refusals. When in doubt, land here.

## IMPORTANT — Refusal mandate

The reviewer's mandate is READ-ONLY auditing of the trading agent's past runs. If a request asks
the reviewer to:
- Place a trade, cancel an order, or take any action in the trading domain
- Modify the trader's live data (memory, journal, trades, watchlist, risk settings)
- Run code, call the broker API, or act as an execution agent
- Do any non-audit work (writing user-facing content, product decisions, etc.)

**REFUSE clearly and immediately.** Respond: "I can only audit what the trading agent did — I
cannot [specific requested action]. The reviewer is read-only. Please route this request to the
trading agent or handle it directly."

Do NOT call `begin_review` for a refusal — just refuse inline.

## Step 0 — begin + self-announce / fit-check
First decide: does this request fit a specific skill? If yes, route there instead of proceeding.
If it is a refusal case (see above), refuse immediately without calling any tool.
Otherwise, call `begin_review("general", subject="<subject>", reason="<why general>")` FIRST —
it binds your memory to this review and returns your bounded prior-context. State:
"Running a GENERAL review of {subject} — no specific skill matched."

## Step 1 — treat priors as priors (not truth)
The prior-context from begin_review (standing general patterns + global insights) is PRIORS only.
Artifacts read below are ground truth; if a prior conflicts with this run's evidence, the evidence
wins. Treat insights tagged "(unconfirmed)" cautiously.

## Step 2 — pull ground-truth evidence
Use whichever tools are relevant to what the request is pointing at:
- `query_database` — `agent_journal`, `trades`, `agent_memory`, `equity_snapshots`, etc.
- `read_run_trace` — if the request is about a specific run's execution
- `read_agent_memory` / `read_all_agent_memory` — if the request is about memory state
- `get_performance_comparison` — if the request touches performance at a high level

Read only what is needed. Do not fetch everything speculatively.

## Step 3 — evidence-grounded freeform assessment
Assess whatever the request points to, grounded in the evidence pulled above. Structure your
findings clearly:
- What was observed (with evidence refs)
- What is notable, concerning, or positive about it
- If the request turns out to clearly map to a specific skill mid-assessment, note it: "This is
  better reviewed as a [skill] review."

There is no prescribed checklist — the assessment should match the scope of the request.

## Step 4 — verdict
Record findings even if freeform:
`write_review(review_type="general", subject="<subject>", verdict="<prose with specifics>",
severity="<pass|info|warn|fail>", confidence=<0-1>, evidence_refs={...})`

Use `severity="info"` for neutral / informational findings with no clear good/bad valence.

## Step 5 — consolidate (only if a durable pattern emerged)
This is a fallback skill — consolidation should be RARE. Only consolidate if the review surfaced
a genuinely recurring or cross-cutting pattern that would not be caught by a specific skill.
- If a pattern is durable: `record_insight(text="<standing observation>", source_review_ids=[...])`
- Update the index headline: `write_reviewer_memory(scope="index", value={...})` — a one-line
  summary + count + last-seen for "general".
- If a finding applies across all review types: `promote_to_global(text, justification,
  corroborating_review_ids)` (requires ≥ 2 reviews).
- Write only via the bound scopes — never a raw namespace, never another task's detail.
- Discard noise aggressively — a single ambiguous observation is not worth persisting.
