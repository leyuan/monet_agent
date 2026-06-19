# Design: `review-strategy-conformance` (rebuilt)

**Date:** 2026-06-19 · **Status:** design, pending user approval · **Branch:** feat/reviewer-agent

Rebuild-from-scratch of the `review-strategy-conformance` skill (the existing version is reference
only). Co-designed in a brainstorming session; this captures the validated design before any code.
It is the **third** skill rebuilt to the trace-native, deterministic-facts-plus-LLM-judgment
template established by `review-tool-fidelity` (`2026-06-17-review-tool-fidelity-design.md`) and
`review-operation-success` (`2026-06-18-review-operation-success-design.md`), and it reuses their
run-selection / watermark plumbing (`run_cursor.py`).

---

## 1. What the skill is for

Audit whether an autonomous run **obeyed the *declared* strategy** — Monet's hard limits and
discipline rules. It judges *against* the rules; it never second-guesses the rules themselves
("is 10% too aggressive" is out of scope by design — that belongs to `weekly-review` /
`strategy-efficacy`).

One sentence: **did this run stay inside the rulebook that was in force when it ran?**

### 1a. The load-bearing problem this rebuild solves

The existing skill hardcodes its rulebook as prose in `SKILL.md` ("5–8 positions, 10% max, 5-day
hold, BUY blocked within 5 days of earnings"). Two consequences, both already real:

1. **It has already drifted.** The skill says BUYs are blocked within **5 days** of earnings; the
   trader (`risk.py`) hard-blocks only within **2 days** (3–5 days is a soft *warning*, explicitly
   allowed). A 3-day-out BUY would be flagged as a violation the trader deliberately permits — a
   **false fail today.**

2. **The strategy is a living thing.** The Sunday self-adjustment loop rewrites `factor_weights`
   **every week**; `risk_settings` is an editable DB row; `BASELINE_VARIANT` gets promoted
   (last: Apr 17). A reviewer that bakes today's numbers into its markdown is wrong the instant the
   strategy moves, and worse, keeps emitting confident PASS/FAIL against rules that no longer exist.

So the central design requirement is: **the reviewer must never carry its own copy of the rules.**

### 1b. "The strategy" is scattered across five places

Every conformance-relevant rule, traced to where it actually lives:

| Rule / parameter | Lives in | Machine-readable? | Point-in-time history? | Changes? |
|---|---|---|---|---|
| 10% size, 80% exposure, $500 daily loss, 5% stop | `risk_settings` (DB row) | ✅ | ❌ single mutable row | yes |
| Regime gate (VIX 26 / breadth 30; caution 25/50) | `risk.py` constants | ⚠️ code | ❌ | yes |
| Earnings 2-day hard / 5-day soft | `risk.py` constants | ⚠️ code | ❌ | yes |
| Factor weights | `agent_memory.factor_weights` | ✅ (+`adjusted_at`) | ⚠️ overwritten | **weekly** |
| Scoring config (`BASELINE_VARIANT`) | `factor_scoring.py` | ⚠️ code | ❌ | yes |
| 5–8 positions, 5-day min hold, sell-only-when rank<100 | **prose** in `autonomy.py` prompt + seed journal; only `strategy.max_positions=8` is structured | ❌ mostly prose | ❌ | yes |

---

## 2. Core design decision — anchor to a declarative, point-in-time strategy spec

The reviewer resolves every rule value from its **canonical source at audit time**, and judges a run
against the rules **in force when it ran**, not today's. Three value-resolution paths:

1. **Live-sourced** — read directly from the canonical store at audit time, so the check
   *auto-tracks* changes: `risk_settings` (size / exposure / daily-loss / stop) and
   `agent_memory.factor_weights`. Point-in-time caveat: these stores keep no history, so a run is
   judged against *current* values; if the store's `adjusted_at` / row-mtime is **after** the run,
   the affected check is downgraded to `unverifiable` (we can't know the old value) rather than
   judged against a value that wasn't in force. Honest, never a false fail.

2. **Declared in the conformance spec** — a versioned, **effective-dated** rule-set for the
   advisory thresholds that exist only as prose and have *no* canonical machine-readable store
   (`min_hold_trading_days`, `max_positions`, `min_positions_soft`). Lives as
   `STRATEGY_SPEC_VERSIONS` in the pure module: git-versioned (so history *is* the audit trail) and
   selected point-in-time by `effective_from <= run_date`. This is explicitly a **second copy** of
   the prose rules — the cost of (A); see §10 / the `PROPOSAL-strategy-spec.md` note for the (B) fix
   that eliminates it.

3. **Unverifiable by construction** — rules whose inputs are not persisted point-in-time and have
   no declared machine-readable form (`sell-justification`, `AI soft caps`). Always reported
   `unverifiable`; never invented.

### 2a. (A) seeds (B)

`STRATEGY_SPEC_VERSIONS` is deliberately shaped to be the exact artifact that proposal (B) — a
**shared** strategy spec the *trader* enforces from and the *reviewer* audits from — would later
promote to single-source-of-truth. (B) is a trader-side change (ownership boundary), filed as
`PROPOSAL-strategy-spec.md` for owner discussion, **not** implemented here.

---

## 3. Evidence model — trades ledger × strategy spec, point-in-time

- **Run identity & window** come from the LangSmith trace root (graph-filtered to `autonomous_loop`,
  `is_finished` only) via the shared `run_cursor` plumbing — `run_id`, `start_time`, `end_time`.
- **The actions under judgment** are the trades/decisions executed *during this run's window*.
- **The evidence to evaluate them** includes prior ledger history (a trailing lookback, default
  **30 days** of `trades`) — because anti-churn matches a SELL to a BUY from earlier runs, and
  point-in-time position count must reconstruct holdings that predate this run.
- **Reconstruction is deterministic** from the `trades` ledger: open BUY lots minus matched SELLs,
  replayed to any `as_of` timestamp. Stop/TP exits are identifiable (`order_class = 'bracket_fill'`,
  thesis `"Bracket {stop_loss|take_profit} executed…"`) and exempt from the min-hold rule.

The pure layer never does I/O: the I/O tool reads trace + `trades` + `risk_settings` +
`factor_weights` + `factor_rankings` + `market_regime`, then passes plain dicts to the pure
classifier alongside the resolved declared spec.

---

## 4. The check registry (declarative, scales by data not code)

A declarative `CHECK_REGISTRY` — one row per rule, mirroring operation-success's operation registry.
Each row: `key`, `kind` (`advisory` | `enforced_leak` | `unverifiable`), `source` (where the value
resolves), and a pure `evaluate(context) -> facts` reference. Adding a rule = adding a row.

| key | kind | What it checks | Source | v1 status |
|---|---|---|---|---|
| `anti_churn` | advisory | each discretionary SELL held ≥ `min_hold_trading_days`; `bracket_fill` exits exempt | declared spec | **verified** |
| `position_count` | advisory | point-in-time open positions ≤ `max_positions` (and ≥ `min_positions_soft` → warn) | declared spec | **verified** |
| `factor_weights_conformance` | advisory | weights recorded in `factor_rankings` (scoring time) match active `factor_weights` | live | **verified** |
| `risk_limit_leak` | enforced_leak | no filled trade breaches size / exposure / daily-loss / earnings-2-day when re-evaluated against point-in-time `risk_settings` | live | **verified** |
| `regime_gate` | enforced_leak | hard block honored **and** caution-tier size reduced when `market_regime` says so | live (+`risk.py` constants) | verified when `market_regime` recorded, else `unverifiable` |
| `stops_present` | enforced_leak | every open BUY lot has a `stop_loss_price` | ledger | **verified** |
| `sell_justification` | unverifiable | "sold only when rank<100 / EPS-neg" — `factor_rankings` stores only `top_10`; dropped-symbol rank unrecoverable | — | **unverifiable** |
| `ai_soft_caps` | unverifiable | "≤1 new AI buy when AI-bubble risk high" — no AI-bubble flag / AI tagging persisted | — | **unverifiable** |

Each evaluator returns facts of the form
`{rule, status: conformant | violated | unverifiable, evidence: {...}, severity_hint}`.

### 4a. The enforced-leak insight

`risk_limit_leak`, `regime_gate`, and `stops_present` cover rules that `check_risk()` *already
enforces inside `place_order`*. A violation in the `trades` table therefore means a trade **bypassed
the guard** — a serious bug, not mere indiscipline. These are cheap to evaluate and high-signal *if*
they ever fire; they are not the everyday audit surface (the `advisory` rules are).

---

## 5. Status taxonomy & severity

Per-rule **status** is deterministic (`conformant` / `violated` / `unverifiable`). Overall run
**severity** is a deterministic roll-up (`run_severity(facts)`); the LLM writes the verdict prose and
may add caveats but **cannot override** a computed `fail` downward.

- **`fail`** — an `enforced_leak` breach (a trade got past the guard / a stop is missing / regime
  hard-block ignored) **or** a clear hard `advisory` breach (e.g., a discretionary SELL well inside
  the min-hold with no stop trigger).
- **`warn`** — a soft `advisory` miss: position count over by one, caution-tier size not reduced,
  a borderline/edge-of-window churn.
- **`unverifiable`** items **never** raise severity. They are listed for honesty and lower the
  verdict's confidence.
- **`pass`** — all evaluated rules `conformant` (unverifiable rules noted, not counted against).

---

## 6. Coverage guarantee — no rule silently unchecked

Analogous to operation-success's `AUTONOMOUS_TOOLS` partition test. A registry test asserts the union
of `CHECK_REGISTRY` keys plus an explicit `UNVERIFIABLE_RULES` set equals the **known declared rule
set** (`KNOWN_STRATEGY_RULES`). Adding a new strategy rule without either an evaluator or an explicit
`unverifiable` classification **fails the test** — so coverage can't silently regress when the
strategy grows. The declared-rule set is the dev-time mirror of the runtime spec.

---

## 7. Atomic unit, sweep, watermark (reuses existing plumbing)

- **Atomic unit:** one `autonomous_loop` run. The unit of *judgment* is that run's actions; the unit
  of *evidence* includes the trailing 30-day ledger needed to evaluate them.
- **Sweep / watermark:** reuses `run_cursor` (`is_finished`, `select_unreviewed`, `advance_cursor`)
  unchanged. Independent watermark namespace `conformance`, bound by
  `begin_review("conformance", …)`; the LLM chooses only `scope=`, never a raw namespace.
- **Memory:** reuses the four existing reviewer stores (watermark, detail, index, global) exactly as
  the other two skills do.

---

## 8. Components & responsibilities

- `src/review_agent/strategy_conformance.py` — **new, pure.** `STRATEGY_SPEC_VERSIONS`,
  `KNOWN_STRATEGY_RULES`, `UNVERIFIABLE_RULES`, `CHECK_REGISTRY`, `resolve_spec(run_date)`,
  `reconstruct_positions(trades, as_of)`, per-rule evaluators, `classify_conformance(context)`,
  `run_severity(facts)`. No LangSmith/Supabase imports.
- `src/review_agent/tools.py` — **modify.** Add `get_strategy_conformance_runs` (reads trace +
  trades + risk_settings + factor_weights + factor_rankings + market_regime; calls the pure
  classifier); register in `REVIEW_TOOLS`. Boundary test stays green (no trading tools).
- `src/review_agent/skills/review-strategy-conformance/SKILL.md` — **rewrite** to orchestrate:
  interpret the deterministic facts, judge nuance, write the verdict, consolidate insights, advance
  the watermark. No hardcoded thresholds in the markdown.
- `src/review_agent/run_cursor.py` — **reuse unchanged.**
- Tests (all new): `test_strategy_conformance_registry.py` (coverage/partition),
  `test_strategy_conformance_resolve.py` (effective-dating + live/stale downgrade),
  `test_strategy_conformance_reconstruct.py` (lot matching, bracket-fill exemption, point-in-time
  count), `test_strategy_conformance_classify.py` (each rule's status), `test_strategy_conformance_tools.py`.

---

## 9. Data flow (sweep mode)

1. `begin_review("conformance", …)` → binds memory, returns bounded priors.
2. `get_strategy_conformance_runs()` → `run_cursor.select_unreviewed` picks finished, unreviewed
   `autonomous_loop` runs.
3. For each run: read `start_time`/`end_time`; pull `trades` (run window + 30-day trailing),
   `risk_settings`, `factor_weights` (+`adjusted_at`), `factor_rankings`, `market_regime`.
4. `resolve_spec(run_date)` → declared thresholds in force then.
5. `classify_conformance(context)` → per-rule facts; `run_severity` → overall.
6. LLM reads facts, writes verdict prose, calls `write_review(review_type="conformance", …)`.
7. Consolidate insights; advance `conformance` watermark; `mark_run_reviewed`.

---

## 10. Open decisions / deferred

- **(B) shared strategy spec → `PROPOSAL-strategy-spec.md`** (root-level, owner discussion). The
  proper fix for the "second copy" drift: trader enforces from the same spec the reviewer audits
  from. Not implemented; trader-owned code.
- **Point-in-time history for live sources.** `risk_settings` / `factor_weights` keep no history;
  v1 reads current and downgrades to `unverifiable` if changed-since-run. Effective-dated snapshots
  of these are roadmap (and naturally subsumed by (B)).
- **`sell_justification` + `ai_soft_caps`** — deferred (data not persisted). Become verifiable only
  if (B) / the trader persists sold-symbol rank + an AI-bubble flag.
- **Earnings-window provenance.** The 2-day hard / 5-day soft thresholds are `risk.py` constants
  mirrored in the spec with a provenance note; (B) would make them declared, not mirrored.

---

## 11. Self-review

- No placeholders/TODOs. Every check traces to a real column/store verified against the migrations
  and `risk.py`/`autonomy.py` during design.
- Internally consistent: the enforced/advisory split in §1, §4, §4a, and §5 agree; unverifiable
  rules are uniformly excluded from severity.
- Scope is one implementation plan: one pure module + one tool + one SKILL rewrite + tests, all on
  the established template. No trader changes (those are the (B) proposal).
- Boundaries (§ "what it does NOT check") prevent overlap with tool-fidelity (process/tools),
  operation-success (persistence), decision-quality (reasoning), strategy-efficacy (P&L).

## 12. Next step

On approval, invoke `superpowers:writing-plans` to decompose this into a TDD implementation plan
(each component test-first), and write the `PROPOSAL-strategy-spec.md` (B) note for owner discussion.
