# How Monet Decides to Trade & Forms Its Strategy

Traced from source (not from CLAUDE.md) on 2026-06-29. File:line refs point at the
implementation so this can be re-verified as code moves. Three parts:

1. [How it decides to make a trade](#1-how-it-decides-to-trade-one-factor-loop-run) — the per-run factor loop
2. [How it forms its strategy](#2-how-it-forms-its-strategy-two-layers) — the two adaptation layers
3. [Where the LLM adds value vs pure quant](#3-where-the-llm-adds-value-vs-pure-quant)

The one-sentence model: **a deterministic factor pipeline gated by hard risk rules makes
every buy/sell call; the strategy behind it tunes its weights weekly via a clamped,
human-gated IC loop and changes its algorithm only through offline backtests; the LLM is a
bounded co-pilot that can hit the brakes anytime but touch the throttle only once per run.**

---

## 1. How it decides to trade (one factor-loop run)

Skill: `agent/skills/factor-loop/SKILL.md`. The left-to-right spine is deterministic; the
only sanctioned LLM override is the earnings-reaction read in Step 3.5.

```
┌──────────────────────────────────────────────────────────────────────────┐
│  STEP 0  reconcile_positions() → writes stopped:{SYM} re-entry guards      │
│          load memory + journal + factor_weights                            │
└──────────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  STEP 1  MARKET REGIME    breadth · sector · SPY/QQQ/VIX                    │
│          VIX>30 → cash buffer 20%→30%, cap 6 positions                      │
└──────────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌──────────── STEP 2  SCORE THE UNIVERSE (deterministic) ────────────────────┐
│   ~900 stocks (S&P500 + S&P400)                                            │
│        │  compute momentum on ALL                                          │
│        ▼                                                                   │
│   pre-filter TOP 150 by momentum ──► fetch fundamentals (only these)       │
│        │   compute_factor_scores()                                         │
│   ┌─────────────┬─────────────┬─────────────┬───────────────┐             │
│   │ MOMENTUM    │ QUALITY     │ VALUE       │ EPS_REVISION  │             │
│   │ 12m-1m/3m/1m│ margin/ROE/ │ inv. fwd-PE │ (placeholder  │             │
│   │ .4/.3/.3    │ debt        │ in-sector   │  50 for now)  │             │
│   └─────────────┴─────────────┴─────────────┴───────────────┘             │
│        │  composite = .35·mom + .30·qual + .20·val + .15·eps               │
│        ▼                                                                   │
│   enrich_eps_revisions(top 20) ─► MERGE real EPS ─► RECOMPUTE composite    │
│                                                     + RE-RANK 1..N         │
└────────────────────────────────────────┬───────────────────────────────────┘
                                         │  generate_factor_rankings()
                                         ▼
┌──────────── SCORES ──► SIGNALS  (no LLM) ──────────────────────────────────┐
│   HELD stock:                          NOT-HELD stock:                     │
│   ┌────────────────────────┐           ┌──────────────────────────────┐   │
│   │ rank>100 OR eps<30 ?    │           │ rank≤20 AND composite>70 ?    │   │
│   │   YES → SELL            │           │   NO  → HOLD (skip)           │   │
│   │   NO, rank≤50 → HOLD    │           │   YES ↓                       │   │
│   │       rank 51-100 →HOLD │           │ eps<30 ?        → ENTRY BLOCK  │   │
│   │       (monitoring)      │           │ stopped:{SYM} &  → RE-ENTRY    │   │
│   │ (≥5-day min hold        │           │   delta not met?   BLOCKED    │   │
│   │  unless stopped)        │           │   else          → BUY         │   │
│   └────────────────────────┘           └──────────────────────────────┘   │
└────────────────────────────────────────┬───────────────────────────────────┘
                                         ▼ STEP 3  earnings / catalyst filter
                                         │  remove BUYs w/ earnings ≤5 days
                                         │  (LLM earnings-reaction read here)
                                         ▼
┌──────────── STEP 4  EXECUTE  (SELL first, then BUY by rank) ───────────────┐
│   each trade ─►  check_risk()  (runs INSIDE place_order)                   │
│                  ┌───────────────────────────────────────┐                │
│                  │ 0. REGIME  VIX>26 & breadth<30% → BLOCK │               │
│                  │            VIX≥25 or breadth≤50% → 7%   │               │
│                  │ 1. position ≤10% (or 7%)               │                │
│                  │ 2. exposure ≤80%                        │               │
│                  │ 3. daily loss > -$500   → BLOCK         │               │
│                  │ 4. cash only (no margin)                │               │
│                  │ 5. earnings ≤2 days     → BLOCK         │               │
│                  └───────────────┬───────────────────────┘                │
│                        approved? │ NO → reject                             │
│                                  ▼ YES                                     │
│                  place_order()  — composite → order type:                  │
│                     >80   → MARKET                                         │
│                     70-80 → LIMIT −1%                                      │
│                     60-70 → LIMIT −3%                                      │
│                     stop = clamp(ATR(14)×2.0, 3%, 8%) else 5%              │
│                     take-profit ≈ +15%   (bracket order)                  │
│   sizing: max 8 positions · 10% each · 20% cash buffer                     │
└────────────────────────────────────────┬───────────────────────────────────┘
                                         ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  STEP 5  RECORD  update_stock_analysis · record_decision (conf=comp/100)   │
│          save factor_rankings snapshot · journal entry                     │
└──────────────────────────────────────────────────────────────────────────┘
```

### Code anchors

| Stage | Function | Location |
|-------|----------|----------|
| Score universe | `score_universe(top_n=30)` → `compute_factor_scores` | `tools/factors.py:36`, `factor_scoring.py:217` |
| Pre-filter / fundamentals | top-150-by-momentum then fetch | `tools/factors.py:128-145` |
| Composite blend | `.35/.30/.20/.15` | `factor_scoring.py:283-288`, weights `tools/_shared.py:11` |
| EPS merge + re-rank | `generate_factor_rankings` | `tools/factors.py:420`, merge `446-472` |
| BUY gate | rank≤20 AND composite>70 AND eps≥30 | `tools/factors.py:509-531` |
| SELL gate | rank>100 OR eps<30 | `tools/factors.py:489` |
| Re-entry guard | `_check_reentry_delta` | `tools/factors.py:340-416` |
| Order type / stop | `place_order` | `tools/trading.py:78-93`, ATR stop `123-141` |
| Risk gate | `check_risk` (Check 0 regime → Check 5 earnings) | `risk.py:12`, regime `182-227` |
| Active config | `BASELINE_VARIANT` (`short_mom_atr`) | `factor_scoring.py:53-68` |

### Key numeric thresholds

- Composite weights: momentum 0.35 / quality 0.30 / value 0.20 / eps 0.15
- Momentum sub-weights: 0.4 / 0.3 / 0.3 over windows (252,22) / (63,0) / (21,0) — i.e. 12m-ex-1m, 3m, 1m
- Pre-filter: top 150 by momentum
- BUY: rank ≤ 20 AND composite > 70 AND eps_revision ≥ 30 (and not re-entry/earnings/catalyst blocked)
- SELL: rank > 100 OR eps_revision < 30 (held ≥ 5 days unless stopped)
- HOLD bands: top 50 = healthy; 51–100 = monitoring
- Order type: >80 market · 70–80 limit −1% · 60–70 limit −3%
- Stop: ATR(14)×2.0 clamped [3%, 8%], else fixed 5%; take-profit ≈ +15%
- Risk caps: position 10% (→7% elevated regime) · exposure 80% · daily loss $500 · cash-only
- Regime gate: hard block VIX>26 & breadth<30%; caution VIX≥25 or breadth≤50%
- Earnings: hard block ≤2 days (code); skill removes BUYs with earnings ≤5 days
- Portfolio: max 8 positions, 20% cash buffer

> **Nuance:** `score_universe()` fills `eps_revision` with a placeholder 50. The real EPS
> scores are merged only inside `generate_factor_rankings()`, which then recomputes the
> composite and re-ranks — so the ranks driving signals reflect enriched EPS, not the first pass.

---

## 2. How it forms its strategy (two layers)

"Strategy" is split across stores and adapts on two layers with different cadences and gates.

```
                        ┌────────────────────────────────────────┐
                        │        WHAT "STRATEGY" IS               │
                        ├────────────────────────────────────────┤
                        │ factor_weights  .35/.30/.20/.15  (memory)│
                        │ BASELINE_VARIANT lookbacks+ATR   (code)  │
                        │ risk_settings   10%/80%/$500     (table) │
                        └────────────────────────────────────────┘

 LAYER 1 — WEIGHTS: adapts WEEKLY, auto-proposed, agent-applied, tightly clamped
 ─────────────────────────────────────────────────────────────────────────────
                                                  ┌─────────────────────────┐
   live trading ──► P&L, equity_snapshots ──────► │  WEEKLY REVIEW (Sunday) │
        ▲                                          └────────────┬────────────┘
        │                                                       │ Step 8 FIRST
        │                                                       ▼
        │                                     audit_factor_ic()
        │                                     Spearman IC, factor vs fwd
        │                                     5/10/20/60d return, 3 mo
        │                                     → strategy_health  (drift flags:
        │                                        SIGN FLIP / DRAG / …)
        │                                                       │ Step 3
        │                                                       ▼
        │                                suggest_factor_weight_adjustment()
        │                                  signal = 0.6·IC20 + 0.4·IC60
        │                                  losers → floor 0.10
        │                                  winners → split rest ∝ signal
        │                                  clamp ±0.05/audit, bound [0.10,0.45]
        │                                  ───► PROPOSAL ONLY (no auto-apply)
        │                                                       │
        │                                            agent reviews / overrides
        │                                                       ▼
        └───────────── write_agent_memory("factor_weights", …) ◄┘


 LAYER 2 — ALGORITHM: changes only OFFLINE, manual promotion
 ─────────────────────────────────────────────────────────────────────────────
   idea (new lookback / stop method)
        ▼
   add FactorVariant in backtest/variants.py
        │  same compute_factor_scores() as live  (no drift)
        ▼
   backtest/runner.py  ── day-by-day sim, risk held constant (SimRules) ──►
        │   alpha · Sharpe · maxDD · win% · stop-hit%
        ▼
   beats baseline?  ──NO──► discard
        │ YES
        ▼
   MANUAL code edit: promote to BASELINE_VARIANT in factor_scoring.py
        │   (e.g. short_mom_atr: +29.3% vs +24.0% alpha, v1.4)
        ▼
   now live ───────────────────────────────────────────────┐
                                                            ▼
 DAILY GUARDRAIL                                  check_live_vs_backtest_divergence()
 ─────────────────────────────────────────────────────────────────────────────
   live 30d annualized alpha  vs  persisted backtest alpha
     ratio < -1.0 → major_underperformance → "re-run audit + backtest"
     ratio > +1.0 → major_outperformance   → "don't touch it"
     else          → aligned
```

### Code anchors

| Piece | Location |
|-------|----------|
| Seeded weights `.35/.30/.20/.15` | `scripts/seed_factor_weights.py:10-17`; default `tools/_shared.py:11` |
| `BASELINE_VARIANT` (algorithm config) | `factor_scoring.py:53-68` |
| `risk_settings` seed | `scripts/seed_strategy.py:86-98` |
| IC audit (Spearman, 5/10/20/60d, 3mo) | `tools/strategy_health.py:14-279`; persists `factor_ic_runs` + `strategy_health` |
| Drift flags (SIGN FLIP / DRAG / …) | `tools/strategy_health.py:240-262` |
| Weight proposal algorithm | `tools/strategy_health.py:416-604` (signal `:489`, clamps `:499-560`) |
| Live-vs-backtest divergence | `tools/strategy_health.py:283-412` (statuses `:383-399`) |
| Weekly-review orchestration | `agent/skills/weekly-review/SKILL.md` (Step 8 before Step 3) |
| Backtest variants / runner / sim rules | `backtest/variants.py`, `backtest/runner.py`, `backtest/engine.py:36-48` |

### Weight-proposal algorithm (exact)

1. `signal = 0.6·IC(20d) + 0.4·IC(60d)` per factor (momentum/quality/value). `eps_revision`
   is not measured by the audit → hardcoded `signal = 0.01` (`strategy_health.py:495`).
2. Constants: `floor=0.10`, `cap=0.45`, `max_shift=0.05`/audit, `min_signal=0.005`.
3. Winners (signal ≥ 0.005) vs losers; losers each get the 0.10 floor first.
4. `remaining = 1.0 − 0.10·len(losers)` split among winners ∝ signal (fallback equal-weight 0.25).
5. Clamp each target to ±0.05 from current, then to [0.10, 0.45]; iterate renormalize+reclamp ≤5×.
6. Returns a **proposal** — does NOT auto-apply. Agent must call `write_agent_memory("factor_weights", …)`.

> **The two-layer takeaway:** factor *weights* adapt weekly (auto-proposed, agent-applied,
> clamped ±0.05/audit, bounded [0.10, 0.45]); the underlying *algorithm* changes only through
> an offline backtest comparison and a manual code-level promotion. The daily divergence check
> catches a promoted strategy that stops tracking its backtest.

---

## 3. Where the LLM adds value vs pure quant

The quant pipeline makes the money; the LLM mostly prevents the pipeline from making mistakes
that backtested rules can't see. Its authority is **deliberately asymmetric** — at five of six
injection points it can only reduce risk.

```
        PURE-QUANT SPINE                          LLM JUDGMENT INJECTIONS
     (deterministic, makes the call)            (bounded overlays, mostly veto-only)

  STEP 1  regime numbers          ◄───── ① INTERPRET "why" (event vs structural)
  VIX / breadth / sectors                 sets cash-buffer posture, narrative only

  (no quant equivalent)           ◄───── ② CAP  assess_ai_bubble_risk / durability
                                          score>80 → ≤1 new AI/semi BUY this run
                                          ── can only REDUCE buys, never block SELL

  STEP 2  score_universe →                (LLM does NOT touch — scoring/ranking
  composite → rank → BUY/SELL/HOLD         is pure Python)

  STEP 3  candidate BUY list      ◄───── ③ VETO  catalyst intel (FDA/launch/suit
                                          ≤3d) → avoid_entry removes BUY
                                  ◄───── ④ OVERRIDE ★ (the ONLY upward one)
                                          earnings-reaction read: "beat but soft
                                          guidance = one-time item → HOLD not SELL";
                                          "transformative → BUY even if composite<70"
                                          ── capped at 1–2 trades/run

  STEP 4  check_risk() +                   (LLM does NOT touch — risk gates + ATR
  place_order() sizing/stops               stops are code, enforced against the LLM)

  STEP 5 / reflection             ◄───── ⑤ NARRATE thesis, journal, attribution,
                                          aggregate domain-expert user insights

  WEEKLY suggest_factor_weight_   ◄───── ⑥ GATE  review proposal (n<8 → halve delta,
  adjustment() → PROPOSAL                  regime override) then write factor_weights
                                          ── "IC proposes, agent disposes"
```

| # | Injection | Skill step | Power | What pure rules can't do |
|---|-----------|-----------|-------|--------------------------|
| ① | Regime interpretation | Step 1 | interpret | A number says "VIX 28"; only language reads *why* and whether to fear it |
| ② | AI-bubble / concentration | Step 1.5 | cap | "Is this froth?" is qualitative, not a backtestable factor |
| ③ | Catalyst avoidance | Step 3.25 | veto | Knowing an FDA decision/suit lands in 3 days needs reading the world |
| ④ ★ | **Earnings-reaction read** | Step 3.5 | **override** | Parsing guidance qualitatively in real time — the irreplaceable edge |
| ⑤ | Thesis / reflection | Step 5, weekly | narrate | Writing theses; aggregating user domain expertise into signals |
| ⑥ | Weight-change gate | Weekly Step 3 | gate | Sanity-checking a noisy IC estimator against sample size + regime |

### The design principle

- The LLM can **reduce risk freely** — veto a buy (③), cap concentration (②), tighten the
  weight delta (⑥). Five of six powers can only make the portfolio *more* cautious.
- It can **add risk in exactly one place** — the transformative-earnings override (④), capped
  at 1–2 trades/run.
- It **cannot touch** the capital-protection core: scoring, ranking, sizing, risk checks, and
  ATR stops are pure code, enforced even against the LLM (`check_risk` runs inside `place_order`).

The quant spine is the engine; the LLM is the co-pilot who can hit the brakes anytime but can
only touch the throttle once per run.
