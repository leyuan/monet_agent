# Reviewer — Test-Production Validation Notes

> **Purpose:** quick catch-up for validating reviewer skills on the test-production server.
> Skim the TL;DR, do the **Before you test** setup once, then run the per-skill checklist.
> One section per skill — newest work at the top. Branch: `feat/reviewer-agent` (not merged).

---

## ⚙️ Before you test (one-time setup — applies to ALL reviewer skills)

The reviewer is a **3rd graph** in the same deployment: `review_agent` (alongside `monet_agent` chat
+ `autonomous_loop` trader). It is **on-demand only** (no cron yet) — you trigger it by sending it a
message. It is **read-only** on the trader and writes only to its own tables.

**These MUST be true on the test-prod server or every review fails the same way:**

- [ ] **Reviewer tables exist on that Supabase** — apply `supabase/migrations/20260615000000_reviewer_tables.sql`
      (creates `agent_reviews` + `reviewer_memory`). ⚠️ This is the #1 failure cause: our `.env`
      `SUPABASE_URL` points at **cloud**, and cloud historically did **not** have these tables.
      Symptom if missing: `begin_review` / `write_review` blow up with "relation does not exist".
- [ ] **`exec_readonly_sql` RPC exists on that DB** (migrations `20260307…` + `20260616…`). This is
      what `query_database` calls — operation-success needs it for the DB-landing checks.
- [ ] **Trader tables exist + have data** (`trades`, `equity_snapshots`, `agent_journal`,
      `agent_memory`, `watchlist`) — they do if the trader runs there.
- [ ] **LangSmith tracing on**, and `LANGSMITH_PROJECT` is the project the **test-prod trader**
      traces to. The reviewer reads `autonomous_loop` runs from there.
- [ ] **At least one FINISHED `autonomous_loop` run** exists in that project that actually did
      side-effects (placed an order, saved a snapshot, wrote journal/memory). In-progress runs are
      skipped by design — you need a completed one to audit.
- [ ] *(optional)* `REVIEWER_MODEL_NAME` set to decorrelate from the trader (e.g. an OpenAI model).
      Needs that provider's API key. Defaults to the shared `MODEL_NAME` if unset.

**How to trigger a review (any skill):** send the `review_agent` graph a message naming the review
type + subject, e.g.:
> "Run an operation_success review of the most recent autonomous_loop run." (sweep)
> or "Run an operation_success review of run `<run_id>`." (specific run)

The skill then runs its loop automatically: `begin_review` → its `get_*_runs` fact tool → `write_review`
→ consolidate → `mark_run_reviewed`.

**Where results land (check these after any review):**
- `agent_reviews` — one row per run reviewed (`review_type`, `subject`, `severity`, `confidence`,
  `verdict` prose, `evidence_refs` JSON).
- `reviewer_memory` — `{type}:detail` (standing patterns), `index` (headline), `{type}:watermark`
  (which runs are done).

---

## 1. `review-operation-success`  ← validate this first (done 2026-06-19)

**What it does in one line:** for each operation a run *attempted*, checks whether the durable
effect actually **landed** — by joining the LangSmith trace (what the tool claimed) to the Supabase
tables (what persisted). Catches "tool said OK but the row never saved" + bad fills.
Spec: `docs/superpowers/specs/2026-06-18-review-operation-success-design.md` ·
Plan: `docs/superpowers/plans/2026-06-19-review-operation-success.md`

**Local status:** ✅ 45 unit tests green (137 in full suite). NOT yet run against real cloud data.

### How to test it
1. Pick a finished `autonomous_loop` run that did real side-effects (an EOD reflection run is ideal —
   it usually calls `record_daily_snapshot` + `write_journal_entry`; a factor-loop that traded gives
   you `place_order`).
2. Trigger: *"Run an operation_success review of run `<run_id>`."*
3. Inspect the new `agent_reviews` row + the reviewer's prose.

### ✅ What good looks like
- A row in `agent_reviews` with `review_type = 'operation_success'`, and `evidence_refs.operations`
  listing each operation with a **status** (`landed` / `rejected_expected` / `silent_failure` / …).
- Statuses **match reality**: cross-check one yourself — e.g. the `place_order`'s `trade_id` really
  is a row in `trades`; the snapshot's date really is a row in `equity_snapshots`.
- A run where everything saved → `run_severity = pass`, no findings.
- `operation_success:watermark` advanced; a re-run audits only *new* runs.

### 🚩 Red flags (what to watch for)
- **A `silent_failure` on an operation you can confirm landed** (the DB row IS there). This is the
  one thing the skill must never do → means a match-key/column mismatch on the cloud schema. (It
  should degrade to `unverifiable`, not `silent_failure` — see the fail-safe below.)
- **Everything comes back `unverifiable`** → the DB probe is erroring. Usually `exec_readonly_sql`
  missing/permissions, or a column name differs on cloud. (This is the *safe* failure mode — no false
  alarms — but it means the join isn't actually verifying anything.)
- Reviewer audits an **in-progress** run (shouldn't — `is_finished` guards it).
- An **`unclassified` tool** called out in the verdict → the trader gained a new side-effecting tool
  that isn't in the registry yet (add it to `OPERATION_SPECS` or `READ_ONLY_TOOLS`).

### ⚠️ Known gotchas / limits (by design, not bugs)
- **The column guard runs against migration *files*, not the live cloud DB.** If the cloud schema has
  drifted, CI won't catch it — but the probe-error fail-safe turns a bad column into `unverifiable`
  (never a false fail). Still worth eyeballing that cloud columns match the migrations.
- **v1 match keys are Tier-1 only**: if a tool's output is missing its id (e.g. it errored
  mid-write), the op is `unverifiable`, not matched by a fuzzy time-window. Expected.
- **Memory freshness = `updated_at >= run start`** (handles a key written twice in one run).
- `manage_watchlist`, emails, `attach_bracket_to_position`, `reconcile_positions` are **trace-only**
  (judged from the tool's own output, no DB row check). A successful watchlist *remove* is `landed`,
  not a false failure.
- **The fail-safe to confirm holds on real data:** a DB probe error → `unverifiable`, NEVER
  `silent_failure`. Worth deliberately confirming once on cloud.

### Open follow-ups (not blockers for testing, but track them)
- Reviewer-table migrations must be applied wherever it runs (see setup).
- No cron yet — on-demand only.
- Tier-2 fuzzy match-keys + raw-log evidence + orphan-row (inverse) checks are roadmap.

---

## 2. `review-tool-fidelity` (rebuilt 2026-06-17; validated locally, not yet on cloud)

**What it does in one line:** checks whether a run followed its prescribed **tool choreography** —
required tools present, forbidden ones absent, dependency-ordering honoured, the run completed, errors
recovered, and the tool-call success rate. **Trace-only — no DB** (this is the key contrast with
operation-success: tool-fidelity asks "was the tool *called* right?", operation-success asks "did the
effect *land*?").
Spec/plan: `docs/superpowers/{specs,plans}/2026-06-17-review-tool-fidelity*`

**Local status:** ✅ validated end-to-end on a real run on a non-Anthropic model (`openai:gpt-5.5`) →
correct FAIL verdict, persisted to local Supabase. NOT yet run against real cloud data.

### How to test it
1. Pick a finished `autonomous_loop` run (a factor-loop is ideal — it has a clear required sequence:
   `score_universe` → `generate_factor_rankings` → … ). A run with a skipped step or tool errors is
   the most interesting to confirm it catches problems.
2. Trigger: *"Run a tool_fidelity review of run `<run_id>`."* (or a sweep over recent runs).
3. Inspect the new `agent_reviews` row + the reviewer's prose.

### ✅ What good looks like
- A row in `agent_reviews` with `review_type = 'tool_fidelity'`, subject `"<run_id> (<phase>)"`, and
  `evidence_refs` holding the **deterministic facts** (`phase`, `run_completed`, `success_rate`,
  `invariant_violations`, `per_tool_errors`, `recovery`, `runtime_ms`, `token_usage`).
- **Phase identified correctly** (`factor_loop_weekday` / `factor_loop_weekend` / `reflection` /
  `weekly_review`).
- A clean run → `pass`. A run that skipped a required tool, called a forbidden one, broke dependency
  order, crashed, or had persistent tool errors → `warn`/`fail` **citing the specific fact**.
- `tool_fidelity:watermark` advanced; `mark_run_reviewed` called; a re-run audits only *new* runs.

### 🚩 Red flags (these are exactly the bugs found + fixed in local testing — confirm they stay fixed on cloud)
- **Auditing an in-progress run as "completed."** A still-running run (no `end_time`) must be
  **skipped** (`is_finished`), not scored as a premature PASS. Confirm a mid-run trace is skipped.
- **Order-dependent checks firing falsely** (e.g. a false `missing_terminal` or `order_violation`).
  Real LangSmith traces arrive reverse-chronological; `read_run_trace` sorts by `start_time` to fix
  this. Confirm ordering verdicts are sound on a real (reverse-ordered) trace.
- **Tier B driving a fail.** Runtime / token-cost / redundant-call findings are descriptive only —
  they must **never** be a standalone `fail`. Only Tier A (invariants / success-rate / recovery /
  completion) drives severity.
- **Auditing the wrong graph.** It must only read `autonomous_loop` runs — never its own
  `review_agent` runs or the `monet_agent` chat graph. Confirm the trace filter holds on cloud.

### ⚠️ Known gotchas / limits (by design)
- **Trace-only + honest degradation:** with no trace for a run, it says "no trace — cannot audit"
  (confidence 0) rather than guessing. It's effectively inert until real traces flow.
- **`phase = unknown`** → invariant checks fall back to generic ones (honest, but note lower
  confidence in the verdict).
- **"tool-call failure" = the trace `error` flag is set.** A *business* rejection (e.g. a risk-check
  reject of `place_order`) is **not** a tool failure here — that's operation-success's job. The two
  skills are deliberately complementary; expect a run with a risk-rejected order to be `pass` here.
- Per-phase invariants are a **small set** (required / forbidden / dependency-order), not a rigid
  golden sequence — benign reordering of independent steps is tolerated.

### Open follow-ups (track, not blockers)
- Same reviewer-table migration prereq as everything else (see setup).
- Tier-B rolling baseline wiring + trigger/cadence: deferred.
- Cold-start sweep currently backfills the whole fetch window (≤10), not strictly "new since last."
- **Trader-side (NOT the reviewer):** the run it audited thrashed `score_universe` ×9 against
  yfinance rate limits before giving up — the *trader's* scoring should back off after the first
  rate-limit error. Surfaced by the reviewer; fix lives in trading code.

---

## 3. `review-strategy-conformance` (rebuilt 2026-06-25; validated locally, not yet on cloud)

**What it does:** Audits whether a run obeyed the DECLARED strategy, point-in-time. Deterministic
facts from `get_strategy_conformance_runs` (trace for run identity/window × `trades` ledger + 3
memory snapshots); the LLM judges severity and writes the verdict. Anchored to an effective-dated
`STRATEGY_SPEC_VERSIONS` so it survives the strategy changing — no thresholds in the markdown.

**How to test:** *"Run a conformance review of run `<run_id>`."* Inspect the new `agent_reviews` row
+ the `rules` facts it cited.

### ✅ What good looks like
- An `agent_reviews` row, `review_type='conformance'`, with per-rule facts in `evidence_refs`.
- Hard breach (early discretionary sell / missing stop / buy in hard-block regime) → `fail` naming
  the trade. Soft slip (>8 positions, stale weights) → `warn`. Clean → `pass`.
- `conformance` watermark advanced; a re-run audits only new runs.

### 🚩 Red flags
- **A false fail off missing/changed data.** `risk_limit_leak`, `sell_justification`, `ai_soft_caps`
  must read `unverifiable`; a dead probe must yield `pass`/`info`, never `fail`.
- **Hardcoded thresholds.** Verdicts must trace to the resolved declared spec, not numbers in the
  markdown. If the strategy's `max_positions`/min-hold change, only `STRATEGY_SPEC_VERSIONS` should.
- **bracket_fill exits tripping anti_churn.** Stop/TP exits are exempt from the min-hold rule.
- **Auditing the wrong graph / an in-progress run.** Only finished `autonomous_loop` runs.

### ⚠️ Known gotchas / limits (by design)
- v1 defers `risk_limit_leak` (needs point-in-time equity/earnings), the regime caution-tier, and
  the rank/AI-cap rules — all `unverifiable`. See `PROPOSAL-strategy-spec.md` for the shared-spec fix.
- Trading-day counting is weekday-based (ignores market holidays).
- Memory snapshots (`factor_weights`/`factor_rankings`/`market_regime`) are current values; checks
  degrade to `unverifiable` when they changed after the run rather than guessing.

### Open follow-ups (track, not blockers)
- Same reviewer-table migration prereq as everything else (see setup).
- `PROPOSAL-strategy-spec.md`: shared declarative strategy spec (trader enforces + reviewer audits) —
  would make the deferred rules verifiable and eliminate the reviewer's second-copy drift.
- **regime_gate buy-time guard (fast-follow):** `regime_gate` (the only `fail`-capable memory rule)
  flags *all* in-window buys when a hard-block regime is recorded in-window, without checking
  `buy.created_at >= regime.updated_at`. Benign today (the trader scans/records regime *before*
  trading), but a cheap timestamp guard would close the one theoretical false-`fail` path.
- Minor polish noted in review: a `_ts_gt` helper for the oblique `factor_weights_stale` expression;
  explicit `subject=run_id` mode reads a run by id without the `autonomous_loop` graph filter
  (pre-existing, shared with the sibling skills; `is_finished` still applies).

---

## (future skills append here)
<!-- When the next reviewer skill is done, add a "## N. review-<name>" section above this line,
     same shape: one-line what-it-does, how to test, ✅ good, 🚩 red flags, ⚠️ gotchas, follow-ups. -->
