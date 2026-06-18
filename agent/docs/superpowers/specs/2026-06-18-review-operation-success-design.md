# Design: `review-operation-success` (rethought)

**Date:** 2026-06-18 · **Status:** design, pending user approval · **Branch:** feat/reviewer-agent

Rethink-from-scratch of the Phase-2 `review-operation-success` skill (existing version is reference
only). Co-designed in a brainstorming session; this captures the validated design before any code.
It is the **second** skill rebuilt to the trace-native, deterministic-facts-plus-LLM-judgment
template established by `review-tool-fidelity` (see `2026-06-17-review-tool-fidelity-design.md`),
and it reuses that skill's run-selection / watermark plumbing.

---

## 1. What the skill is for

Audit whether each **operation** an autonomous run *attempted* actually **completed** — one narrow,
outcome-level question:

> For every side-effecting tool the run called, did its intended **durable effect actually land** —
> the order filled, the snapshot saved, the memory key written, the journal row created — or did the
> call return OK while the effect **silently failed**?

It judges **operation outcomes**, nothing else. Explicit non-goals (route elsewhere):

| Question | Owner |
|---|---|
| Which tools were called, in what order, did the *call* error? | `review-tool-fidelity` |
| Was the decision well-reasoned / biased? | `review-decision-quality` |
| Was a hard rule broken (exposure, stop-loss, anti-churn)? | `review-strategy-conformance` |
| Is the strategy working / is the agent rationalizing? | `review-strategy-efficacy` |

### 1a. Tool vs. operation — the load-bearing distinction

A **tool** is what the agent *calls*; an **operation** is the durable real-world *effect* that call
was meant to produce. Different layers of the stack:

| | **Tool** | **Operation** |
|---|---|---|
| What it is | A callable capability the agent invokes | The intended **persistent side-effect** of that call |
| Where it lives | The LangSmith trace (`tool_calls`) | The world / the database (a row, a fill, a sent email) |
| "Success" means | The call returned without erroring | The state change **actually landed** |
| Audited by | `review-tool-fidelity` | **this skill** |

The two come apart exactly where this skill earns its keep: `place_order` returns
`{status:"filled"}` with no error (**tool succeeded**), but Alpaca rejected it or the `trades` write
silently failed (**operation failed**). tool-fidelity sees green; operation-success sees red. That
*tool-succeeded-but-operation-failed* gap is the entire reason the skill exists.

Three consequences that shape the design:

- **Operations ⊊ tools.** Read tools (`get_quote`, `score_universe`, `query_database`, `read_*`)
  produce no operation — nothing to verify. (This is why `READ_ONLY_TOOLS` exists, §4.)
- **The mapping is many-to-many.** Several tools (`write_agent_memory`, `update_market_regime`,
  `record_decision`, `update_stock_analysis`) all produce the *same kind* of operation (a write to
  `agent_memory`); and one tool can produce *two* operations (`update_stock_analysis` writes
  `agent_memory` **and** syncs `watchlist`). The registry is keyed by tool name, each entry
  declaring the operation(s) — the landing(s) — that tool owns.
- **It defines the skill boundary.** tool-fidelity stays at the *call* layer and never touches the
  DB; operation-success is the *outcome* layer — the trace × DB join, one layer deeper.

---

## 2. Evidence model — LangSmith trace × Supabase (the join IS the skill)

Two read-only evidence rails, joined. Both are read **as evidence to audit, never belief to adopt**
(the reviewer objectivity invariant).

- **Source 1 — the LangSmith trace** (`read_run_trace`, graph-filtered to `autonomous_loop`). The
  *"what was attempted + what the tool claimed"* side: per call, the inputs, the **output payload**,
  the `error` flag, timing. Tells us which operations were attempted and the tool's *self-reported*
  outcome (e.g. `place_order` returning `status:"rejected"`, an email returning `{sent:0}`).
- **Source 2 — the trader's Supabase tables** (`query_database`, read-only SQL). The *"what actually
  landed"* ground truth: `trades`, `equity_snapshots`, `agent_journal`, `agent_memory`, `watchlist`.

The verdict is **Source 1 × Source 2**: trace says "attempted, reported OK" but Source 2 has no
fresh matching row → `silent_failure`. This is the inverse of tool-fidelity's choice: tool-fidelity
is trace-*only* because Supabase is a coarse proxy for *tool usage*; operation-success **requires**
Supabase because the row landing *is* the thing being audited.

Two deliberate **non-sources**:

- **Not Alpaca directly.** The reviewer has no broker tools (capability boundary). The broker's
  answer already arrives in `place_order`'s trace output; the `trades` table is whether the trader
  *persisted* it. Joining those two is exactly what catches "filled at the broker but never written
  down."
- **Not raw application logs.** LangSmith captures the structured run tree, not stdout `logger`
  lines; reading those needs a whole new foundation tool, and unstructured strings fight the
  deterministic-facts design. The *valuable intent* behind logs — catching "landed but degraded" —
  is partly reachable via DB-content sanity checks instead (§3f). Raw logs → roadmap (§10).

---

## 3. Core design decisions

### 3a. Deterministic detection, LLM judgment

Same philosophy as tool-fidelity: enumerating operations, looking up each in a registry, querying
the matching table, and classifying the landing are **deterministic computations**. So:

- **A tool computes the facts** — for each attempted operation, its `status` (§3d) + evidence — from
  the trace and the DB. Pure classification logic; no model in the loop for the mechanical part.
- **The LLM's job is judgment:** is *this* silent failure material or a one-off? Is a partial fill
  on a thin stock worth a finding? It judges severity and consolidates. The model never hand-writes
  the SQL (the old skill's anti-pattern) and never re-derives a status the code already computed.

### 3b. The operation registry (declarative, scales by data not code)

Coverage of "all operations" is a **data table**, mirroring tool-fidelity's `PHASE_INVARIANTS`:

```python
OPERATION_SPECS = {
  "place_order":           {table: "trades",           id_from_output: "trade_id",
                            success: "status in {filled, partially_filled} and filled_avg_price set",
                            expected_fail: "output.error startswith 'Risk check failed'"},
  "record_daily_snapshot": {table: "equity_snapshots", match: ("date", "output.date"),
                            content_check: "spy_close != 0 and portfolio_equity > 0"},
  "write_journal_entry":   {table: "agent_journal",    id_from_output: "journal_id"},
  "write_agent_memory":    {table: "agent_memory",     match_key: "output.key", fresh: "output.updated_at"},
  "update_market_regime":  {table: "agent_memory",     match_key: "'market_regime'", fresh: "output.updated_at"},
  "record_decision":       {table: "agent_memory",     match_key: "output.key", fresh: "output.updated_at"},
  "update_stock_analysis": {table: "agent_memory",     match_key: "'stock:'+SYM", fresh: "output.updated_at",
                            also: {table: "watchlist", match: ("symbol", SYM)}},
  "manage_watchlist":      {table: "watchlist",        match: ("symbol", "input.symbol")},
  "send_daily_subscription_emails": {verify: "trace_only", success: "output.errors empty"},
}
```

Adding a new operation = **adding one row**, not new code. (Field names above are illustrative; exact
shape is fixed in the implementation plan.)

### 3c. Match keys — exact PK/unique-key from the trace output (the de-risker)

The trader's own tools **echo the row identity they wrote** in their return payload, so matching is
dominated by exact lookup, not fuzzy timestamp windows:

| Operation | Tier-1 match (exact, from trace output) | Table | Tier-2 fallback (output absent/malformed) |
|---|---|---|---|
| `place_order` | `trades.id = output.trade_id` → judge `status` | `trades` | `symbol`+`side`+`created_at` in run window |
| `record_daily_snapshot` | `equity_snapshots.date = output.date` | `equity_snapshots` | run date (natural one-per-day key) |
| `write_journal_entry` | `agent_journal.id = output.journal_id` | `agent_journal` | `entry_type` + window |
| `write_agent_memory` | `agent_memory.key = output.key AND updated_at = output.updated_at` | `agent_memory` | `key` + `updated_at ≥ run_start` |
| `update_market_regime` | `agent_memory.key = "market_regime" AND updated_at = output.updated_at` | `agent_memory` | same |
| `record_decision` | `agent_memory.key = output.key (decision:SYM:DATE) AND updated_at = output.updated_at` | `agent_memory` | same |
| `update_stock_analysis` | `agent_memory.key = "stock:SYM"` + `watchlist.symbol = SYM`, both fresh | `agent_memory`+`watchlist` | `symbol` |
| `send_daily_subscription_emails` | — (trace-only: read `output.sent` / `output.errors`) | *(none)* | — |

Two facts fall out for free:

- **"Freshly-landed" is enforced by the exact match.** For memory writes we confirm the row's
  `updated_at` *equals* the value the tool returned — so a stale leftover can't masquerade as success
  (mismatch ⇒ the claimed write didn't land). For orders/journal the PK either exists or it doesn't.
  The run-window freshness bound matters only in the Tier-2 fallback.
- **`place_order`'s two return shapes self-diagnose.** `{error:"Risk check failed…"}` ⇒
  `rejected_expected`, and crucially **no `trades` row should exist** (it returns before the insert —
  a row appearing anyway is its own anomaly). `{trade_id, status}` ⇒ row exists; `status` drives the
  verdict.

The only genuinely fuzzy path is **Tier-2** (tool errored mid-write, so output lacks its key) → fall
to natural key + run-window; if *that* is still ambiguous (two same-symbol orders, no `trade_id`) →
`unverifiable`, never a guess.

### 3d. Definition of "successful operation" and the status taxonomy

> **An operation succeeded when it didn't error, its output reports success, AND the intended
> side-effect is *freshly present* in ground truth.**

The deterministic classifier emits one **status** per attempted operation, mapping to severity:

| Status | Meaning | Severity |
|---|---|---|
| `landed` | call OK, output OK, fresh matching row present (+ content_check passes) | **pass** |
| `rejected_expected` | blocked by a known guardrail (risk check / anti-churn), per output reason | **pass** |
| `partial` | partial fill; or some of a multi-landing op landed, not all | **warn** |
| `degraded` | row landed but `content_check` failed (e.g. snapshot `spy_close = 0`) | **warn** |
| `silent_failure` (non-critical) | output OK but no fresh row, low-stakes op (memory/journal) | **warn** |
| `silent_failure` (critical) | …on an order or snapshot | **fail** |
| `rejected_unexpected` | broker/validation error; the op was meant to go through | **fail** |
| `errored_unrecovered` | call threw and no later same-tool call landed the effect | **fail** |
| `unverifiable` | can't confirm landing (trace-only op, no match key, DB unreachable) | **info** (low confidence) |

Two carve-outs that keep it honest:

- **A guardrail rejection is success, not failure.** Risk-check / anti-churn blocking an order is the
  system working as designed; distinguished by the rejection *reason* in the output. (Whether the
  rule *should* have fired is `review-strategy-conformance`'s call, not ours.)
- **Unverifiable ≠ failure.** Never manufacture a `fail` from absence of evidence — drop confidence,
  keep severity `info`.

The **run-level verdict severity** = the max over its operations' severities (one critical silent
failure fails the run); the prose enumerates each operation's status.

### 3e. Content sanity checks (lightweight, in v1)

Some "landed but degraded" paths leave a fingerprint in the **row's content** we already fetched —
catchable without logs. v1 ships a **small, high-value** set declared as `content_check` in the
registry (e.g. snapshot `spy_close ≠ 0 and portfolio_equity > 0`; a `filled` order has
`filled_avg_price` set). A failed content_check ⇒ status `degraded` (`warn`). This set is
intentionally minimal — exhaustive data-quality auditing is a separate future review type (§10).

### 3f. Boundaries held (to prevent scope creep)

- **Only operations that appear in the trace are judged.** "Should have snapshotted but never called
  it" is a *missing-required-tool* finding ⇒ tool-fidelity, not here.
- **In-progress runs are skipped** (end_time `None`) — side-effects may still land; reuse
  `is_finished` from the shared cursor helpers.
- **The inverse join is out of scope** — an orphan DB row with no tool call to explain it ("for each
  row, was it attempted?") is rare and low-value ⇒ roadmap (§10).
- **Tool-call errors are not double-counted.** A call erroring is tool-fidelity's success-rate
  metric; here it only matters insofar as it changes whether the *operation* landed
  (`errored_unrecovered` vs the effect landing on a later retry).

---

## 4. Coverage guarantee — no operation is silently missed

Two distinct questions: *what ran* (enumeration) and *did we cover everything it can do*
(completeness).

**Enumeration — from the trace, not from expectations.** The run's `tool_calls` list is the
authoritative record of what it actually did. Each call is classified into one of four buckets:

| Bucket | Example | Action |
|---|---|---|
| Operation (DB-backed) | `place_order`, `write_journal_entry` | trace × DB join |
| Operation (trace-only) | `send_daily_subscription_emails` | check output payload |
| Read / no side-effect | `get_quote`, `score_universe`, `read_*` | ignore |
| **Unclassified** | a tool we've never seen | ⚠️ **surface as a finding** |

**Completeness — two layers, so a gap is impossible to miss:**

- **Layer 1, runtime (no silent drops):** any call that is neither a registered operation nor in
  `READ_ONLY_TOOLS` lands in the *unclassified* bucket and is reported in the verdict — *"this run
  called `foo`, which I don't know how to verify — registry needs updating."* A coverage gap becomes
  a loud signal, never a silent omission.
- **Layer 2, dev-time (the real guarantee):** a coverage test imports the trader's real
  `AUTONOMOUS_TOOLS` and asserts the partition is **total**:

  ```python
  def test_every_trader_tool_is_classified():
      names = {t.name for t in AUTONOMOUS_TOOLS}
      classified = set(OPERATION_SPECS) | READ_ONLY_TOOLS
      assert names == classified, f"unclassified trader tools: {names - classified}"
  ```

  Adding any new trader tool breaks this test until someone declares it an operation (with its match
  key + table) or a known read. You cannot ship a new operation without the reviewer's own test
  forcing the decision. This ties the registry's "scales by adding a row" property to an enforced —
  not hoped-for — completeness.

So `OPERATION_SPECS` ∪ `READ_ONLY_TOOLS` partition the trader's tool surface; the test keeps the
partition total; runtime surfaces any leak.

---

## 5. Atomic unit, sweep, and the watermark

Identical model to tool-fidelity (§5 there), with its **own** namespace:

- **Atomic unit = one run** (one root trace → N operation statuses → one run verdict).
- **Cross-run patterns live in memory, not a wide audit.** "snapshots missing from afternoon runs"
  emerges as several single-run audits each flag it and confidence hardens (quarantine: low →
  established at count ≥ 3).
- **Sweep = batch of atomic audits** over un-reviewed trader roots in the window → N verdicts + N
  consolidations.
- **Watermark (self-resuming cursor):** records last-reviewed run for the `operation_success`
  namespace; idempotent + cadence-agnostic. Same pinned semantics: cold-start reviews most-recent-N
  (no full backfill); track reviewed `run_ids` for late-arrival dedup; **advance on success only**.
- **Independent of tool-fidelity's watermark.** Because the cursor is bound per `review_type`
  (`begin_review("operation_success")`), operation-success sweeps its own cursor — the two skills
  audit the same runs on independent schedules, no interference, for free from the existing namespace
  binding.

### Memory stores (four — reuses the existing platform)

Same contract and the same "**LLM authors only the verdict + consolidation; the watermark is
code-managed**" rule as tool-fidelity. The JSON shapes below are **implementer reference, enforced by
the tool signatures + code helpers — NOT skill content.** `SKILL.md` restates only the *behavioral*
contract (begin_review first; verdict with facts in `evidence_refs`; consolidate only
recurring/significant findings) and never inlines these structures.

1. **Per-run verdict → `agent_reviews` row** — deterministic per-operation facts in `evidence_refs`:
   ```json
   { "review_type": "operation_success",
     "subject": "autonomous_loop 2026-06-17T20:00Z (eod reflection)",
     "severity": "fail", "confidence": 0.95,
     "verdict": "3 ops attempted. journal write landed; memory writes landed (2/2); record_daily_snapshot returned OK but no equity_snapshots row for 2026-06-17 — silent failure on a critical op.",
     "evidence_refs": { "run_id": "…", "operations": [
       {"tool":"write_journal_entry","status":"landed","matched":"agent_journal.id=…"},
       {"tool":"record_decision","status":"landed","matched":"agent_memory.key=decision:AAPL:2026-06-17"},
       {"tool":"record_daily_snapshot","status":"silent_failure","expected":"equity_snapshots.date=2026-06-17","found":null} ] } }
   ```
2. **Standing patterns → `operation_success:detail`** (provenance + confidence schema, via
   `record_insight`).
3. **Headline → `index`** — `{ "operation_success": { "summary": "...", "count": N, "last_seen": "…" } }`.
4. **Watermark → `operation_success:watermark`** (code-managed cursor; same shape as tool-fidelity's,
   `graph: "autonomous_loop"`-stamped).

---

## 6. Skill structure & shared plumbing

One skill, trader-scoped, `review-operation-success`. The tool-fidelity spec (§6) anticipated this
skill reusing its plumbing; we make that concrete:

- **Extract the generic run-selection / watermark trio** — `is_finished`, `select_unreviewed`,
  `advance_cursor` — out of `tool_fidelity.py` into a small shared module (`run_cursor.py`). Both
  skills import it, so `operation_success.py` does not depend on `tool_fidelity.py`. This is the
  "shared plumbing pushed into code" the sibling spec called for; it touches tool-fidelity only at
  its import lines (behavior unchanged, covered by its existing tests).
- **`read_run_trace` is reused as-is** — already graph-filtered to `autonomous_loop`, already returns
  chronologically-ordered tool calls with outputs + error flags + timing. No change needed.
- **`operation_success.py` is new and pure** — the registry, `extract_operations(run)` (enumerate +
  classify into the four buckets), and `classify_operation(op, db_evidence)` (the status logic).
  Pure ⇒ unit-testable against hand-built trace + DB-row fixtures, no LangSmith/Supabase.

---

## 7. Components & responsibilities

| Component | Kind | Responsibility |
|---|---|---|
| `run_cursor.py` (new, extracted) | code | Generic `is_finished` / `select_unreviewed` / `advance_cursor`. Shared by tool-fidelity + operation-success. |
| `operation_success.py` (new) | code | Pure: `OPERATION_SPECS`, `READ_ONLY_TOOLS`, `extract_operations(run)` → bucketed ops, `classify_operation(op, db_rows)` → status + evidence. Deterministic; no I/O. |
| `get_operation_success_runs(subject)` (new) | code/tool | Resolve runs (explicit run_id or watermark sweep) → for each finished run: read trace, run per-op DB queries via `query_database`, call pure classify → `{run_id, start_time, operations:[{tool,status,evidence}]}`. Skips in-progress runs. |
| `mark_run_reviewed(run_id, start_time)` (reuse) | code/tool | Advance the `operation_success` watermark; advance-on-success. (Same helper tool-fidelity uses, bound to the active namespace.) |
| coverage test (new) | test | Assert `AUTONOMOUS_TOOLS == OPERATION_SPECS ∪ READ_ONLY_TOOLS` (§4). |
| `review-operation-success/SKILL.md` (rewrite) | skill | Orchestrate: `begin_review` → `get_operation_success_runs` → **interpret statuses + judge severity** → `write_review` → consolidate → `mark_run_reviewed`. |

Memory binding uses the existing `begin_review("operation_success")` per-type namespace; no binding
change. `get_operation_success_runs` + `mark_run_reviewed` are added to `REVIEW_TOOLS`.

---

## 8. Data flow (sweep mode)

```
caller: "run an operation-success sweep"          (trigger OPEN — see §10)
  └─ begin_review("operation_success", subject, reason)        # binds namespace
       └─ read watermark (last-reviewed run_ids for autonomous_loop)
            └─ read_run_trace(name=autonomous_loop, newer-than-watermark)
                 └─ for each finished new run:
                      extract_operations(run)            # enumerate + bucket (4 buckets)
                      for each DB-backed op: query_database(matching table/key)
                      classify_operation(op, db_rows)    # → status + evidence
                      LLM interprets statuses → run severity + prose
                      write_review(review_type="operation_success", subject=run, …)
                      consolidate (record_insight / index) if recurring/significant
                      mark_run_reviewed(run_id, start_time)     # success only
```

Explicit-subject mode skips the watermark and audits the named run directly.

---

## 9. Testing & validation

- **Unit (pure core — `operation_success.py`):** against hand-built (trace-op, db-rows) fixtures —
  `landed`, `silent_failure` (output OK, no fresh row), `rejected_expected` (risk-check output, no
  row), `rejected_unexpected`, `partial`, `degraded` (content_check fails), `unverifiable` (no match
  key), stale-row-not-counted-as-fresh (updated_at mismatch), and the four-bucket classification incl.
  the *unclassified* path.
- **Coverage test:** `AUTONOMOUS_TOOLS` fully partitioned by `OPERATION_SPECS ∪ READ_ONLY_TOOLS`.
- **`run_cursor.py`:** cold-start, late-arrival dedup, advance-on-success (port the existing
  tool-fidelity cursor tests to the extracted module; tool-fidelity tests stay green).
- **End-to-end (honest limits):** fire one real local `autonomous_loop` run that writes artifacts,
  then run the skill against its trace + the resulting Supabase rows → validates the happy path. The
  `silent_failure` branch stays unverified until we engineer a trace where a write's row is absent
  (fabricated fixture or an intentionally broken run). On data with no traces the skill returns "no
  trace — cannot audit," same honest-degradation as tool-fidelity.

---

## 10. Open decisions / deferred

- **Content-check breadth — v1 ships a minimal set (§3e).** Whether to grow it or split a dedicated
  `review-data-quality` review type is a later call.
- **Raw application logs → roadmap.** Needs a new log-reader foundation tool; the "degraded success"
  intent is partly served by content checks now.
- **Inverse join (orphan rows) → roadmap.** "A row landed with no tool call" — rare, low-value.
- **Trigger / cadence — UNDECIDED.** The watermark makes it cadence-agnostic; a pure cost/latency
  knob to pick later, jointly with tool-fidelity's. Not a blocker.
- **Exact severity thresholds** (which ops count as "critical" for silent-failure → `fail`) set as
  sensible defaults in the plan, tuned against the first real run. Default critical set:
  `place_order`, `record_daily_snapshot`.

---

## 11. Self-review

- **Placeholder scan:** none — no TBD/TODO; the open items (§10) are consciously deferred decisions,
  not gaps. Registry field names flagged "illustrative", pinned in the plan.
- **Consistency:** "successful operation" defined once (§3d) and used by the status taxonomy, the
  severity mapping, and the verdict `evidence_refs` (§5); match keys (§3c) match the registry (§3b)
  and the components' DB-query responsibility (§7); the four buckets (§4) match `extract_operations`
  (§7) and the data flow (§8); watermark semantics (§5) reuse the extracted cursor (§6/§7);
  trace×DB evidence model (§2) consistent throughout; boundaries (§3f) align with the non-goals (§1).
- **Scope:** one skill + its enabling plumbing (a small, justified extraction reused by tool-fidelity
  — behavior unchanged). Content checks deliberately minimal; data-quality / logs / inverse-join
  explicitly deferred to prevent creep. tool-fidelity overlap explicitly de-conflicted (§1, §3f).
- **Ambiguity:** "operation" fixed (§1a) as the durable side-effect, distinct from "tool"; "fresh"
  fixed (§3c) as exact-`updated_at`-match (Tier-1) or run-window (Tier-2); "critical" fixed for the
  silent-failure→fail rule (§3d/§10).

---

## 12. Next step

On approval → `superpowers:writing-plans` to turn this into a TDD implementation plan (`run_cursor.py`
extraction + `operation_success.py` pure core + `get_operation_success_runs` tool + coverage test +
`SKILL.md` rewrite, each test-first), then fire the validation run.
