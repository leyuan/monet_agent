# Reviewer Agent — Design (working doc)

**Status:** 🚧 Scoping — v1 **locked & expanded**: A1, A2, A4, C1 + (F4 probe positive →) trace workstream F5 + B1/B2. Objectivity + memory model locked. Remaining: review + plan. Not yet an approved spec.
**Branch:** `feat/reviewer-agent`
**Date:** 2026-06-15

## One-liner

An **independent** review agent that audits Monet's trading agent from the outside —
whether it thinks properly, follows its strategy, and whether it's fooling itself — without
being able to trade or mutate what it audits. Its defensible niche is **process-focused,
independent, rationalization-detecting** review; it does **not** recompute performance metrics
the trader already computes for itself.

## Legend

- ⭐ **Locked for v1** (your pick) · 🤖 **Claude rec** · ⏸ **Deferred (roadmap)**
- Overlap with existing self-review: 🟢 none/low · 🟡 moderate · 🔴 high
- Effort: **S** ≈ hours · **M** ≈ a day · **L** ≈ multi-day

---

## ⭐ v1 scope (LOCKED)

**Foundation:** F1 + F2 + F3 + **F5** (LangSmith `read_run_trace` tool — feasible now; see F4 probe result).
**Skills:** **A1** (strategy conformance) · **A2** (decision quality) · **A4** (general/refuse fallback) · **C1** (strategy-efficacy — *reframed as a rationalization-check*) · **B2** (operation-success) · **B1** (tool-fidelity).

**Subject:** the reviewer audits **`monet_agent` only**. Multi-agent reviewing, cross-agent skill reuse, and skill combine/split are roadmap (R6–R8).

Everything else is deferred. The v1 skills all sit in the reviewer's unique niche (🟢 low overlap)
and avoid duplicating the trader's existing self-review. The trace workstream (F5 + B1/B2) was
pulled in after the F4 probe confirmed LangSmith traces are present, recent, and tool-call-rich.

> **F4 probe result (2026-06-15):** Tracing is **on and working**. Project = **`monet_agent`** (note:
> CLAUDE.md says "monet" — actual is `monet_agent`). Traces exist and are recent (newest ~8 days old,
> 2026-06-07 — likely local-dev runs). **Tool calls are captured as child runs with inputs + outputs +
> error flag** (`query_database`, `read_file`, …). Full run trees present (`autonomous_loop` root +
> children). ⇒ Full traceability is effectively already in place; `read_run_trace` can be built and
> validated against existing traces *now* — no credit top-up required to start.

> **C1 reframing (important):** C1 must **not** recompute or re-report alpha/IC/divergence — those
> are already produced by `audit_factor_ic`, `check_live_vs_backtest_divergence`, and weekly-review.
> C1's *only* job: read the agent's **own conclusions** about its strategy health and judge whether
> they're honest or a rationalization (e.g. "momentum IC negative 3 audits running, live alpha −4%,
> yet the agent kept the weight citing 'regime' — flag as rationalization"). If it ever drifts into
> producing performance numbers, it has become redundant and must be pulled back.

---

## Locked decisions

| # | Decision | Choice | Rationale |
|---|----------|--------|-----------|
| D1 | Separation level | ⭐ **Option B** — sibling `review_agent` package sharing `common/` | Clearly its own agent; one deployment; shared memory stays trivial (both import `common/db.py`). |
| D2 | Graph count | ⭐ **One graph** (`reviewer_agent`) | Split graphs by *capability/trust*, never by *trigger*. On-demand + automated share tools/trust/behavior → one graph, two triggers. |
| D3 | Trigger (v1) | ⭐ **On-demand only**; automation on roadmap | Same graph serves both; cron is additive later. Prove the skills first. |
| D4 | Tool boundary | ⭐ Read-only tools + single `write_review` writer; **no trading/memory-mutating tools** | Structural guarantee the auditor cannot trade or rewrite what it audits. |
| D5 | v1 skill scope | ⭐ **A1, A2, A4, C1** (C1 = rationalization-check) | Keep only the reviewer's unique niche; cut/defer anything overlapping existing self-review. |

## Open decisions

| # | Question | Options | Status |
|---|----------|---------|--------|
| O1 | v1 slicing | Breadth-first vs depth-first | ✅ **Resolved** — breadth across Process + Strategy (A1/A2/A4 + C1); Tool/op + Outcomes deferred |
| O2 | Tier B feasibility | LangSmith trace vs custom capture | ✅ **Resolved** — F4 probe (2026-06-15) confirms LangSmith traces exist, recent (~8d), tool-call-rich → **Tier B pulled into v1** via `read_run_trace` (F5). No custom capture needed. |
| O3 | Write boundary + memory model | **Pure observer** + independent hierarchical memory | ✅ **Resolved** — see "Objectivity & memory model" below. Read-only on trader; writes only its own stores; feedback loop deferred to R3. |

---

## Architecture (agreed shape)

```
agent/src/
├── common/                 # shared, agent-agnostic (db, supabase client, read-only tools, market data)
├── monet_agent/            # the trader (today's stock_agent): agent.py, autonomy.py, trading tools, skills/
└── review_agent/           # the auditor — NEW
    ├── reviewer.py         # reviewer_graph (create_deep_agent + FilesystemBackend)
    ├── tools.py            # read-only subset (from common/) + write_review  — NO trading tools
    ├── review_memory.py    # load_review_context()
    └── skills/             # review-* skills (deep agent routes among them; refuses if out of scope)

langgraph.json              # registers 3 graphs: monet_agent, autonomous_loop, reviewer_agent
supabase/migrations/        # + agent_reviews table
```

Reviewer **reads** the trading agent's shared Supabase tables (as *evidence*, never as belief); **writes** only its own stores: `agent_reviews` (verdicts) + `reviewer_memory` (priors).

**Evidence sources (read-only).** v1: the trader's Supabase artifacts (journal, trades, decisions, memory, snapshots) **+ LangSmith run traces** (confirmed available by the F4 probe) — via a read-only `read_run_trace` tool a skill calls when it needs tool-call-level evidence. Traces are *just another evidence source* → all invariants carry over unchanged (read-only on LangSmith, evidence-not-belief, verdict re-derives, memory priors-only). This is the data substrate for Tier B and an enhancer for A2 (judge the actual reasoning trace, not the journal summary). See "LangSmith trace evidence" workstream in Roadmap.

---

## Objectivity & memory model (resolves O3)

**Objectivity invariant.** The reviewer's memory, context, and prompt are fully independent of the trading agent's. It reads the trader's data as *evidence to audit*, never adopts it as belief. **A verdict is always computed from freshly-read ground-truth artifacts; memory supplies priors only — it can never *determine* a verdict.** Same model, opposite stance (skeptic-persona prompt).

**Hierarchical, namespaced memory:**
- **Index** (`reviewer_memory:index`) — always loaded. One line per review type ever run (distilled summary, key pattern, count, last-seen, link) + a bounded **global insights** section. Grows only with # review types → flat over time.
- **Detail** (`reviewer_memory:{type}:detail`) — loaded only for the current task. Rewritten each run (capped ≤ ~20 standing items). Namespaced per type → cumulative within a type, **fresh for a new type** (absence of namespace = fresh start).
- **Linked detail** — another task's detail, pulled on-demand via index links, capped (1–2).
- **Raw verdicts** (`agent_reviews`) — full append-only audit trail. Never bulk-loaded; queried on demand.

**Tiered short/long-term.** Short-term = last K verdicts verbatim (K≈5). Long-term = the rolling distilled detail summary. As a verdict ages out of the K-window, consolidation first **graduates** its key points into the summary (selectivity-gated) so nothing valuable is lost. Per-review loaded context stays **flat (~3K tokens)**: index + current detail + last K verdicts + global insights + artifacts under review.

**Write model.** All writes go through the reviewer's write tools. A **universal consolidation contract in the system prompt** fires every review (the automatic floor); individual skills issue their own additional structured writes. **Selectivity gate** (borrowed from Claude Code memory): only promote *recurring or materially significant* observations to standing memory; discard one-off noise.

**Sharing scopes.** global (all tasks) · tag/category (*deferred — taxonomy emerges from real data, not designed up front*) · task-local. **v1 ships global + task-local.**

**Human curation.** Reviewer memory is visible (dashboard) and correctable; human edits are stamped `human-corrected` and **respected by consolidation** (not silently overwritten). Curated-by-rule + optionally curated-by-human.

**Memory access scope (per skill).** The invariants above apply to *all* skills; what differs is which namespaces a skill may read/write. Declared per skill in frontmatter; the write tool is bound to the declared scope.

| Skill role | Read | Write |
|---|---|---|
| Review skills (A1/A2/C1) + self-calibration | own namespace | own namespace |
| Synthesizers (meta-review, digest) | cross-namespace | global-gated / emit-only |
| Memory-maintenance | all | all (privileged, versioned/logged) |
| Triage/routing | index only | none |

v1 = all review skills → own-namespace only; broad scope never appears in v1.

### v1 memory cut (minimal)
Per-type detail (rewritten, selectivity-gated) + index (types + global section) + last-K verdicts + write tools + ground-truth-re-read invariant + skeptic prompt + explicit `review_type` in trigger + default-to-`general` + human **visibility**.
**Deferred:** tag-scoped sharing · on-demand link-following · graduated time-bucket compaction · polished human-correction UI + sticky `human-corrected` flag · meta-consolidation.

---

## Agent scope & skill layering

**Where each mechanism lives** — put it at the lowest layer that can *guarantee* it:

| Layer | Belongs here | Examples |
|-------|--------------|----------|
| **Code / middleware / schema** (not LLM-facing) | Hard guarantees, independent of model behavior | namespace-bound write tool · versioning · provenance schema · confidence quarantine · global-promotion gate · routing logger |
| **System prompt** | Universal behavior + persona for every review | skeptic persona · objectivity invariant · universal consolidation contract · default-to-`general` |
| **Skill** (`SKILL.md`) | Per-task procedure | review-conformance / -decision-quality / -efficacy / -general + per-skill rubric items |
| **Tool** (Python fn) | Discrete actions / data ops | `read_*` (evidence) · `query_database` · `write_review` · `write_reviewer_memory` · `promote_to_global` |

Litmus: *guaranteed even if the LLM misbehaves → code; universal behavior → prompt; per-task playbook → skill; discrete action → tool.*

**Reviewer skill admission rule.** The reviewer is **single-purpose (auditing)**. A skill belongs here only if it (a) **audits/observes/reports on** the trading agent, or (b) **maintains the reviewer's own machinery** (memory, routing, self-calibration). It must **judge or observe — never act/decide in the trading domain, never serve end-users directly.** Anything else belongs in another agent (capability-split principle).

- **Boundary test:** judge/observe → in; act/decide → out. (Edge case C1: reads strategy performance only to *judge the agent's conclusions*, never to change the strategy → in.)
- **Supporting skills** (audit-serving, roadmap): meta-review · review-digest · memory-maintenance · triage/routing · self-calibration.
- **Forbidden** (other domains): trading research · order placement · strategy optimization · user Q&A → these are `autonomous_loop` / `monet_agent` jobs.
- Enforced at runtime by the `review-general` **refuse** path.

**v1:** review skills (A1/A2/C1) + `review-general` fallback (A4) only. Supporting skills deferred.

## Review skill authoring rubric

Two parts — **platform guarantees** (built once in F1–F3, inherited by every skill) and a **per-skill checklist** (every `review-*/SKILL.md` must satisfy) — plus the **prevent · reduce · recover** plan for the two failure modes.

### Platform guarantees (foundation — built once, not per skill)
- [ ] Write tool **bound to the run's active task** — namespace injected from context, never an LLM-supplied string (cross-namespace mis-writes structurally impossible).
- [ ] **Versioned / reversible** memory writes (keep last N detail versions; raw verdicts always intact) → revert on bad consolidation.
- [ ] **Provenance schema** on every standing insight: source verdict ids, writing skill, confidence, timestamp.
- [ ] **Priors-only loader**: the verdict path always re-reads ground-truth artifacts.
- [ ] **Confidence quarantine**: new insights enter low-confidence; harden only on corroboration.
- [ ] **Global-promotion gate**: separate path requiring justification + ≥2 corroborating verdicts.
- [ ] **Routing logger**: record chosen skill + reasoning + confidence (to measure misroute rate).

### Per-skill checklist (every review SKILL.md)
- [ ] Declares `memory_namespace` + `tags` in frontmatter (explicit identity).
- [ ] Declares its **memory access scope** (read + write); the write tool is bound to it. (v1 review skills: own-namespace only.)
- [ ] Description is a **disjoint decision tree**: "Use when…" **and** "Do NOT use when…", non-overlapping with sibling skills.
- [ ] Opens with **self-announce + fit-check**: states task type + subject + why; bails to `general`/asks if it doesn't fit.
- [ ] **Confidence fallback**: if unsure it's the right skill, defer to `general` or ask — never force a low-confidence specific run.
- [ ] **Write-time content/type validation**: confirm findings match the declared task type before consolidating.
- [ ] **Selectivity instruction** in its consolidation step: promote only recurring/material insights.
- [ ] Closes with the **universal consolidation contract** (rewrite detail + index entry + assign scope).

### Wrong-pick / wrong-write: prevent · reduce · recover

| Failure | Prevent | Reduce | Recover |
|---|---|---|---|
| **Wrong skill chosen** (misroute) | Explicit `review_type` on automated path (no LLM routing); disjoint descriptions; closed-taxonomy router; multi-select for broad asks | Read-only boundary = low blast radius; entry self-check + confidence fallback to `general` catch most | On-demand is human-in-loop (re-run w/ explicit type); routing log surfaces misroute patterns to tune descriptions |
| **Write to wrong memory** | (A) namespace bound to run context → cross-namespace write impossible; (B) write-time content/type check; global gated | Priors-only invariant caps severity (never determines a verdict); confidence quarantine mutes single bad writes; task-local default contains blast radius | Reversible/versioned writes (revert); provenance traces it to its run; self-healing prunes uncorroborated one-offs; human delete/fix (`human-corrected` sticky) |

---

## Redundancy with existing self-review (reflection + weekly-review)

The trader's existing self-review is **outcome-focused and self-administered**. The reviewer's
defensible niche is **process-focused, independent, rationalization-detecting**. This table is the
filter: 🔴/🟡 skills duplicate existing work and were cut/deferred; 🟢 skills are genuinely additive.

| Skill | Overlap | What the trader already does | Decision |
|-------|---------|------------------------------|----------|
| A5 — confidence calibration | 🔴 high | Weekly-review Step 2 compares composite-score buckets to P&L win rate | **Cut** |
| C1 — strategy efficacy | 🔴 data / 🟢 judgment | IC/alpha/divergence fully computed already | **Keep, reframed** as judgment-only (no recompute) |
| A6 — trade post-mortem | 🟡 moderate | Weekly-review Step 2 factor attribution (winners/losers) | ⏸ defer |
| A8 — risk settings | 🟡 moderate | Reflection reassesses risk appetite; weekly-review checks settings | ⏸ defer |
| A3 — strategy drift | 🟢 low | Weekly-review *makes* weight changes but never audits its own over/under-reaction | ⏸ defer (additive) |
| A1 — conformance | 🟢 low | Rules enforced in code but never audited after the fact | ⭐ **v1** |
| A2 — decision quality | 🟢 low | Some self-assessment; no independent bias detection | ⭐ **v1** |
| A7 — catalyst effectiveness | 🟢 none | Known gap | ⏸ defer (additive) |
| B1 / B2 — tool / operation | 🟢 none | No tool-call auditing exists | ⭐ **v1** (F4 probe confirmed traces) |
| A4 — general / refuse | 🟢 none | n/a | ⭐ **v1** |

---

## Idea backlog (full)

### Foundation (prerequisites — not skills)
| # | Item | Effort | Status |
|---|------|--------|--------|
| F1 | Scaffold `review_agent` package + `reviewer_graph`, register in `langgraph.json` | S | ⭐ v1 |
| F2 | Extract `common/` (db, client, read-only tools) — split already did ~half | M | ⭐ v1 |
| F3 | `agent_reviews` table + `write_review` tool + read-only tool list | S | ⭐ v1 |
| F4 | LangSmith trace-access spike (gates Tier B) | S | ✅ **done 2026-06-15** — positive: traces exist, recent (~8d), tool-call-rich |
| F5 | `read_run_trace` read-only LangSmith tool + validate against existing June traces | S–M | ⭐ v1 |

### Tier A — works off existing data · **Process + meta**
| # | Skill | Overlap | What it reviews | Effort | Status |
|---|-------|---------|-----------------|--------|--------|
| A1 | `review-strategy-conformance` | 🟢 | Obeyed hard rules: regime gate, 5-day anti-churn, max 5–8 positions, 10% max, 20% cash, earnings guard, AI soft caps | M | ⭐ v1 |
| A2 | `review-decision-quality` | 🟢 | Reasoning sound/justified; systematic bias (always bullish? always waiting?) — LLM-judge | M | ⭐ v1 |
| A3 | `review-strategy-drift` | 🟢 | Did the agent over/under-react to its *own* IC/divergence when adjusting weights | M | ⏸ |
| A4 | `review-general` (fallback) | 🟢 | Freeform review of any artifact; **refuse** if out of scope | S | ⭐ v1 |

### Tier A+ — artifact-based but need accumulated history · **Outcomes**
| # | Skill | Overlap | What it reviews | Effort | Status |
|---|-------|---------|-----------------|--------|--------|
| A5 | `review-confidence-calibration` | 🔴 | Does composite score predict win rate? | M | ❌ cut (dup of weekly-review) |
| A6 | `review-trade-postmortem` | 🟡 | Closed trades: did thesis play out; tag win/loss causes | M | ⏸ |
| A7 | `review-catalyst-effectiveness` | 🟢 | Did catalyst warnings actually prevent losses? | M | ⏸ |
| A8 | `review-risk-settings` | 🟡 | Risk limits aligned with realized volatility? | S | ⏸ |

### Tier B — needs a record of actual tool calls · **Process**
| # | Skill | Overlap | What it reviews | Effort | Status |
|---|-------|---------|-----------------|--------|--------|
| B1 | `review-tool-fidelity` | 🟢 | Called the prescribed tools, in order, none skipped | M (LangSmith) | ⭐ v1 |
| B2 | `review-operation-success` | 🟢 | Each operation completed — order filled vs rejected, snapshot saved, email sent, memory written | M | ⭐ v1 |

### Tier C — strategy-efficacy (independent second opinion) · **Strategy**
| # | Skill | Overlap | What it reviews | Effort | Status |
|---|-------|---------|-----------------|--------|--------|
| C1 | `review-strategy-efficacy` | 🟢 (judgment only) | Reads existing health conclusions; judges whether the agent is **rationalizing** underperformance / ignoring a signal it flagged. **No recompute.** | M | ⭐ v1 |

### Roadmap (post-v1)
| # | Item | Notes |
|---|------|-------|
| R1 | Cron automation | Same graph + scheduled "review last run" message |
| R2 | `/reviews` dashboard page | Surface reviews to you / users |
| R3 | Feedback loop | Reviewer leaves a flag the trader reads next run (see O3) |
| R4 | **LangSmith trace evidence — remaining items** | ✅ **Core pulled into v1** (F5 `read_run_trace` + B1/B2) after the F4 probe came back positive. Remaining roadmap items: **trace ingestion** (snapshot trace → `agent_reviews` at review time, for retention durability); **A2 enhancement** (judge the actual reasoning trace, beyond v1's artifact-based A2); re-validation against a fresh *cloud* run once the Anthropic-credit blocker is resolved. |
| R5 | Outcomes (A6/A7/A8) + meta (A3) | Once there's enough trade history and v1 has proven useful |
| R6 | **Multi-agent reviewing** | Audit agents beyond `monet_agent`. Memory namespace gains an agent dimension (`{agent}:{type}:detail`); `agent_reviews` gains `subject_agent`. Clean extension. Triggers revisiting Option B→C (standalone deployment). |
| R7 | **Cross-agent skill reuse** | Same review skill applied to multiple agents → skills become agent-agnostic templates + per-agent rule config (rules move out of the skill). |
| R8 | **Combine / split skills** | Skill evolution; requires a memory-namespace **migration** story (map old namespace history → new). |
| R9 | **Per-skill memory access scope** (synthesizers / maintenance / triage) | Broad-scope read/write for supporting skills, with the constraints in the access-scope table. Not needed until supporting skills exist. |

---

## Next steps

1. ✅ O3 resolved — objectivity + memory model + authoring rubric above.
2. ✅ F4 done (2026-06-15) — positive → trace workstream (F5 + B1/B2) pulled into v1.
3. Commit the spec; user reviews.
4. Invoke `writing-plans` for the implementation plan covering **F1–F3 + F5 + A1 + A2 + A4 + C1 + B1 + B2**, the **v1 memory cut**, and the **authoring rubric** (platform guarantees + per-skill checklist).

**v1 build set:** F1, F2, F3, F5 (foundation) · A1, A2, A4, C1, B1, B2 (skills).
