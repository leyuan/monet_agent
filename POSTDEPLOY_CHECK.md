# Verification Checklist

Ongoing checklist of features/behaviors to verify after deployment. When reviewing run quality, check pending items whose trigger conditions have been met.

---

## Pending Verification

### Memory read cost — `read_all_agent_memory` excludes audit history (Jul 7)
**Trigger**: Next factor-loop / reflection / weekly-review runs (any skill that calls `read_all_agent_memory()`). **Local test passed Jul 7**: default 100 keys / ~39K tok vs `include_audit=True` 850 keys / ~112K tok; 750 audit records held back.
- [ ] A factor-loop or reflection trace shows `read_all_agent_memory` returning the live-belief set (~40K tok) — NOT the ~104K blob; the Jul 3 17:00 factor loop's `read_all` + 2 blob re-reads pattern is gone
- [ ] Live-belief keys still present in the result: `market_regime`, `factor_weights`, `factor_rankings`, `conviction_universe`, `ai_bubble_risk`, `stock:*`
- [ ] No `decision:*` / `stopped:*` / `earnings_reaction:*` keys leak into the default result (`excluded` count > 0)
- [ ] `load_agent_context()` (system prompt) is unaffected — recent decisions (last 7 days) still render; it calls `db.read_all_memory` directly, not the tool
- [ ] Skills still behave correctly with beliefs-only memory (anti-churn / hold logic reads recent decisions from the system prompt or targeted `read_agent_memory`, not the full dump)
- [ ] **Audit path**: a call with `include_audit=True` returns the full table (all decision:*/stopped:* records) for a genuine full-history audit

### Memory read cost — batched `read_agent_memory_keys` (Jul 1)
**Trigger**: Next Conviction Loop runs (10am/1pm ET crons). **Local test passed Jul 1**: targeted 4-key read = 954 tok vs `read_all_agent_memory` = 104K tok (799 keys) → 109× smaller.
- [ ] Conviction loop Step 0 calls `read_agent_memory_keys([...])` (batched) and does NOT call `read_all_agent_memory`
- [ ] No `/large_tool_results/` offload for memory, and no `grep`/`read_file` against a memory blob in the trace
- [ ] Run's total input tokens drop sharply vs the ~3.6M baseline of the Jun 24 15:00 run (target: well under 1M); per-run cost falls from ~$1–2.45 toward ~$0.5
- [ ] All four keys (`conviction_universe`, `ai_capex_tracker`, `ai_cycle_durability`, `ai_bubble_risk`) come back populated; loop logic (exit checks, sizing) still fires correctly
- [ ] **Failure mode**: a missing key returns `value: None` without erroring the loop
- [ ] Factor loop / reflection runs (which still use `read_all_agent_memory` if any) are unaffected — no import or registration errors

### Conviction — staged entries + active management (Jun 29)
**Trigger**: Next "Conviction Loop" runs. **Local dry-run passed Jun 29** (manage_cycle_positions on live book: thesis intact, WDC −10% → ADD 9 sh, MU/SNDK hold; book cash only ~$5.6k confirms the over-deployment the staging fixes).
- [ ] `size_cycle_position()` now deploys ~66% of the tier target (returns `deployed_pct`/`reserve_pct`) and writes `conviction_plan:{SYMBOL}` with `target_pct` + `entry_price`
- [ ] A new Conviction entry lands at the STARTER size (≈deployed_pct of book), not the full tier target; cash is preserved for adds
- [ ] `manage_cycle_positions("conviction")` returns add/trim/hold per holding; ADD only when ≥8% below entry AND thesis_intact AND room below target AND cash available
- [ ] **Critical**: when the thesis is broken (force `ai_capex_tracker.guidance_direction="decelerating"`), manage_cycle_positions recommends NO adds (HOLD with "thesis BROKEN" reason) — never averages down; Step 1 hard-exit sells instead
- [ ] Deeper dip (≥15% below entry) sizes a larger add (deep_multiplier) but stays capped by remaining room to target and by book cash
- [ ] TRIM fires when a name is ≥40% above entry (sells trim_fraction); refilled cash becomes available for the next dip add
- [ ] Cooldowns: a name added on one run is not re-added the next (add_cooldown_days); trims respect trim_cooldown_days — derived from the trades log
- [ ] Cold-start (positions with no `conviction_plan`): target defaults to medium 30%; oversized legacy positions (e.g. SNDK ~40%) get no adds (no room) and don't error
- [ ] Conviction loop Step 3.5 executes the recommended adds/trims via `place_order(..., portfolio="conviction", risk_overrides=CONVICTION_RISK_OVERRIDES)` and journals the reason

### Daily Digest — Key News section (Jun 23)
**Trigger**: Next daily subscription email send (`send_daily_subscription_emails()`), after an AI cycle refresh has populated `ai_cycle_signals`.
- [ ] Email renders a "Key News · AI super-cycle" section between the AI Super-Cycle band and Today's Trades
- [ ] Net-read sentence appears above the signal list when `ai_cycle_signals.net_read` is set
- [ ] Subject line leads with the day's top curated headline (`Monet · <headline> · <Mon D>`); long headlines truncate at a word boundary with `…`; **fallback**: no signals → `Monet Daily Digest - <full date>`
- [ ] Freshness gate: signals with a `date` older than 7 days are excluded from both the subject and the Key News list (undated/unparseable items are kept); **failure mode**: all signals stale → section omitted + subject falls back to dated title
- [ ] AI cycle refresh now stamps signals with the article's real publication date (not today) and drops items >7 days old / standing capex levels already shown on the AI Capex Trend card — confirm next refresh's `ai_cycle_signals.date` values are real pub dates
- [ ] Each signal shows a color-coded category pill (Supply Tight/Capacity Adds green, Guidance blue, Financing Strain amber, Demand Stress red) matching the dashboard CycleSignalsCard
- [ ] Headlines with a `url` are clickable; the ↗ arrow renders; headlines without a url render as plain text (no broken link)
- [ ] Only the top 4 signals are shown even when memory holds more
- [ ] Plain-text body includes the "Key news — AI super-cycle" block (open the text/plain part in a client that prefers it)
- [ ] **Failure mode**: `ai_cycle_signals` missing/empty or `signals: []` → section is omitted entirely, email still sends with the other sections intact (no empty header, no exception)
- [ ] HTML escaping holds for headlines/sources containing `&`, `<`, quotes (no broken markup)

### Two-Portfolio System — Increment 2: portfolio schema foundation (Jun 11)
**Trigger**: After applying migration `20260611000000_two_portfolio.sql` to Supabase.
- [ ] Migration applies cleanly; `trades.portfolio` and `equity_snapshots.portfolio` columns exist
- [ ] All pre-existing `trades` rows backfilled to `portfolio='quant'` (none null/empty)
- [ ] All pre-existing `equity_snapshots` rows backfilled to `portfolio='quant'`
- [ ] Composite unique `(portfolio, snapshot_date)` enforced; old `snapshot_date`-only unique dropped (insert two rows same date diff portfolio succeeds)
- [ ] Existing factor-loop run still records a `quant` equity snapshot and trades with no code changes (defaults work)
- [ ] `get_equity_snapshots()` and dashboard performance reads still return the Quant Core curve unchanged (failure mode: empty curve = portfolio filter regression)

### Two-Portfolio System — Increment 3: broker-layer parameterization (Jun 11)
**Trigger**: First autonomous run after deploy with `ALPACA_API_KEY_CONVICTION` set in the LangGraph Platform env. **Local REST check passed Jun 11** (Quant Core acct PA3VC3H1LYAS $106.5k; Conviction acct PA38Q4IRLZYN clean $100k).
- [ ] LangGraph Platform deployment has `ALPACA_API_KEY_CONVICTION` / `ALPACA_SECRET_KEY_CONVICTION` set (NOT just web/.env.local) — else `get_trading_client("conviction")` raises KeyError at runtime
- [ ] Existing factor loop still trades/records on Quant Core unchanged (all defaults = "quant")
- [ ] `get_portfolio("conviction")` returns the second account, not the first (distinct account_number)
- [ ] A `place_order(..., portfolio="conviction")` lands in the Conviction Alpaca account and writes `trades.portfolio='conviction'`
- [ ] `reconcile_positions("conviction")` only considers conviction trades (failure mode: a quant symbol shows up as a conviction ghost = portfolio filter missing)
- [ ] `check_risk(..., portfolio="conviction", risk_overrides={...})` reads Conviction equity and applies the relaxed limits

### Two-Portfolio System — Increment 4: automated capex signal + cycle history (Jun 11)
**Trigger**: First autonomous run that calls `compute_ai_capex_trend()` + `record_ai_cycle_snapshot()` (wired into the Increment-5 daily refresh). **Local data check passed Jun 11**: capex retrieved for all 7 names, hyperscaler YoY ~+80% → accelerating.
- [ ] `compute_ai_capex_trend()` runs without error; `agent_memory.ai_capex_tracker` updated with `guidance_direction`, `hyperscaler_total_yoy`, `memory_yoy`, `per_name`
- [ ] Direction reads `accelerating` while hyperscaler capex YoY is strongly positive (currently ~+80%)
- [ ] `assess_ai_cycle_durability()` Signal 5 now reads the AUTOMATED tracker (capex_signal.direction matches compute_ai_capex_trend output, not the old manual value)
- [ ] SNDK failure mode: sparse/zero SNDK capex does NOT break the tool (per-name try/except → memory_yoy still computes from MU/WDC)
- [ ] `record_ai_cycle_snapshot()` writes one row to `ai_cycle_snapshots` for today with cycle_score, phase, capex_direction, hyperscaler_capex_yoy
- [ ] Re-running same day upserts (no duplicate snapshot_date rows)
- [ ] When the agent passes `forward_guidance_direction="cutting"`, the blended direction downgrades vs the financial-only direction

### Two-Portfolio System — Increment 5: AI Super-Cycle page + daily refresh (Jun 12)
**Trigger**: Deploy web + run `python scripts/create_crons.py` to register the daily AI cycle refresh cron. **Local verify passed Jun 12**: page renders, real data seeded (durability 42, capex +80.5% accelerating, heat 20), 1 history snapshot for 2026-06-12.
- [ ] `/ai-cycle` appears in the sidebar nav (Cpu icon) and renders the three cards + history chart
- [ ] AI Capex Trend card shows hyperscaler YoY headline + per-name demand/supply rows (MSFT/GOOGL/AMZN/META, MU/WDC/SNDK)
- [ ] History chart populates as snapshots accrue (needs ≥2 days for a line; 1 day shows a point)
- [ ] Daily cron "AI Cycle Refresh (9:30 AM ET)" exists after create_crons.py and fires — writes a new `ai_cycle_snapshots` row each day
- [ ] The refresh agent runs internet_search and passes a real `forward_guidance_direction` into compute_ai_capex_trend (check the journal entry run_source='ai_cycle_refresh' notes guidance)
- [ ] RLS: `ai_cycle_snapshots` readable by authenticated app users; anon `/api/ai-cycle` returns empty history (security check)
- [ ] **DEPLOY DEP**: `create_crons.py` must be re-run for the new cron to exist; the ai-cycle-refresh skill ships with the agent deploy

### Two-Portfolio System — Increment 6: Conviction strategy (Jun 12)
**Trigger**: After deploy + `create_crons.py`, the first "Conviction Loop (11 AM ET)" run. **Local sizing check passed Jun 12**: size_cycle_position("MU") returned 41/30/20 sh for high/medium/starter, 20% ATR stop.
- [ ] Conviction cron exists and fires AFTER the 9:30am AI cycle refresh (fresh signals)
- [ ] Step 1 hard-exit check runs BEFORE entries every loop (journal shows exit evaluation even when flat)
- [ ] Entry gate correctly blocks when durability is maturing/cooling — UNLESS capex is accelerating and the "stale capex sub-signal" exception is explicitly invoked in the journal
- [ ] A Conviction entry lands in the conviction Alpaca account (PA38Q4IRLZYN) with `trades.portfolio='conviction'`, 20-40% sizing, wide 10-20% stop
- [ ] `risk_overrides=CONVICTION_RISK_OVERRIDES` lets the 40% position through (a 40% position would FAIL Quant Core's 10% limit — confirms override path works)
- [ ] Hard exit fires end-to-end: force `ai_capex_tracker.guidance_direction="decelerating"` → next loop sells all Conviction positions
- [ ] Conviction equity curve recorded separately via `record_daily_snapshot(portfolio="conviction")`
- [ ] **Behavior note**: once live, Conviction trades AUTONOMOUSLY on paper. With durability currently 42/maturing but capex accelerating, the first run may enter MU under the stale-capex exception — confirm that's desired.

### Two-Portfolio System — Increment 7: dashboard multi-portfolio UI (Jun 12)
**Trigger**: Deploy web. **Local verify passed Jun 12**: /api/portfolio?portfolio=quant → $97,980/6 pos, ?portfolio=conviction → $100k/0 pos; dashboard compiles; tsc 0 errors.
- [ ] Dashboard "Holdings" toggle switches summary/positions/trades between Quant Core and Conviction
- [ ] Headline PortfolioComparisonCard plots Quant Core + SPY now, and Conviction once it has snapshots
- [ ] BenchmarkCard + PerformanceCard still show ONLY Quant Core (pinned `portfolio="quant"`) — failure mode: numbers jump when Conviction starts trading = filter regression
- [ ] /api/portfolio?portfolio=conviction routes to the conviction Alpaca account (equity $100k, distinct from quant)
- [ ] Vercel env has `ALPACA_API_KEY_CONVICTION` / `ALPACA_SECRET_KEY_CONVICTION` (else the conviction toggle 500s in prod)
- [ ] Recent Trades under the toggle shows only the selected book's trades (`trades.portfolio` filter)

### Stock-split data integrity — KLAC 10:1 (Jun 12)
**Issue**: KLAC executed a 10:1 split 2026-06-12. `stock:KLAC` memory held pre-split target_entry $2173.53 / target_exit $2595.85 (set Jun 11) → live ~$247 read as a phantom ~90% gap. **Fixed Jun 12**: targets corrected to $217.35 / $259.59, thesis stamped. Scanned all ~40 stored symbols — only KLAC split since Apr 1, no other stale records.
**Hardening**: added explicit `auto_adjust=True` to the 5 `yf.download` return/momentum calls (tools.py:204,496,616,899,4201) + `market_data.get_historical_bars` — previously relied on yfinance's version-dependent default. Verified KLAC 1y return computes correctly (+185%, not −90%).
- [ ] Next factor loop: KLAC momentum/score is sane (no split artifact); re-analysis overwrites stock:KLAC with fresh adjusted targets

### Stock-split root-cause fix — split-aware position handling (Jun 12, needs deploy)
**What shipped**: Discovered the ~$7.7k drop was a real artifact — KLAC's bracket stop fired on the 10:1 split (paper broker adjusted price, not share count). Cleaned up state (cleared stopped:KLAC false guard, reset stock:KLAC status, journaled the artifact, seeded `splits_processed`). **Code fix**: `reconcile_positions` now tags a stop that coincides with a split as `split_artifact` and does NOT write the `stopped:` re-entry guard; new `adjust_for_corporate_actions()` (factor-loop Step 0) divides stale stock:*/watchlist targets by the split ratio (idempotent via `splits_processed`) and flags held names that split.
**Trigger**: First factor loop after this deploys.
- [ ] Factor-loop Step 0 calls `adjust_for_corporate_actions()` before reconcile; logs adjusted targets / split flags
- [ ] Idempotency: re-running does NOT re-divide already-adjusted targets (KLAC:2026-06-12 in splits_processed → skipped)
- [ ] A stop firing on a split day is tagged `split_artifact` in trades.thesis and does NOT create a `stopped:{SYM}` guard
- [ ] KLAC re-enters the universe normally (no false stop block); next analysis writes correct post-split targets
- [ ] Held-name split flags surface in the loop output for stop review
- [ ] Known limitation: cannot prevent Alpaca paper's own mis-fire on the split tick (no advance split calendar) — we recognize + don't penalize re-entry rather than blocking the fill

### Two-Portfolio System — Increment 8: single daily digest email (Jun 12)
**Trigger**: Next EOD reflection (`send_daily_subscription_emails`). **Local render passed Jun 12**: both books + cycle headline + tagged trades rendered without send.
- [ ] Daily email shows BOTH books (Quant Core + Conviction) with equity / day P&L / return / vs SPY
- [ ] AI Super-Cycle headline line present (cycle phase + score, capex direction + hyperscaler YoY, heat level + score)
- [ ] Trades tagged [QUANT] / [CONV]
- [ ] Conviction shows "vs SPY —" until it has its own equity_snapshots (no crash on missing data)
- [ ] NO separate weekly cycle email goes out (weekly-review Step 7 no longer calls send_weekly_cycle_report; the Sunday review itself still runs)
- [ ] Subject reads "Monet Daily Digest" and only ONE email per subscriber per day

### Tier 1 Strategy Health Monitoring (first runs after Apr 17 deploy)
**Trigger**: Next Sunday weekly review + next EOD reflection. **Checked May 29 — IC audit half FAILING.**
- [ ] ❌ Weekly review Step 8 runs `audit_factor_ic()` without error — FAILS. Journals report "IC audit error, only 1 sample date, all IC null" for 5+ consecutive weeks (Weeks 8–12). Tool is erroring every Sunday.
- [ ] ❌ Row written to `factor_ic_runs` with variant_name='live_audit' — FAILS. **Zero `live_audit` rows have ever been persisted.** Table only holds the 4 backtest variants from the Apr 17 batch (max sample_size 18).
- [ ] ⚠️ `strategy_health` key appears with current_ic, drift_flags, sample_dates — PARTIAL. Key exists but frozen at assessed_date 2026-05-10 (19 days stale); IC values null; no robust sample_dates.
- [x] Weekly review Step 3 runs `suggest_factor_weight_adjustment()` — runs, but proposal is garbage (null IC in → noise out). Week 12 proposal was correctly REJECTED by the agent.
- [x] Agent applies (or overrides with documented reason) — agent overrides via empirical/P&L reasoning each week (human-in-loop working as designed; see factor_weights reason 05-24).
- [x] ✅ EOD reflection Step 2.5 runs `check_live_vs_backtest_divergence()` and persists to `strategy_divergence` — WORKING (content as_of 2026-05-28, status "aligned").
- [x] If status != "aligned", one-line note appears — N/A currently (status aligned). Divergence flag DID fire on 05-26 reflection ("Major Divergence Flag") so path is exercised.
- [ ] Dashboard `StrategyHealthCard` renders — not verified (no UI access this run).

**ROOT CAUSE TO FIX**: `audit_factor_ic()` only finds 1 usable cross-sectional date per run (→ null IC). Likely a date-window / price-alignment bug in the live audit path. Until fixed, the entire self-adjustment loop is dead — `suggest_factor_weight_adjustment()` has no valid signal, and weights have been held by discretionary override for 5+ weeks. Also note: `agent_memory.updated_at` does NOT bump on value updates (strategy_divergence content is 05-28 but updated_at stuck at 04-17) — freshness monitoring must read internal date fields, not updated_at.

### Promoted BASELINE_VARIANT (3-component momentum + ATR stops) — next factor loop run
**Trigger**: First factor-loop run after the Apr 17 promotion of short_mom_atr to BASELINE_VARIANT.
- [ ] `score_universe()` completes without error using the new momentum lookbacks `[(252,22), (63,0), (21,0)]` with weights `[0.4, 0.3, 0.3]`
- [ ] Rankings show movement from previous baseline (top-10 should shuffle by 2-5 positions; if identical, the new momentum component isn't wired in)
- [ ] `place_order()` for a new BUY computes ATR-based stop: stop_pct falls in [3%, 8%] and scales with the symbol's realized volatility
- [ ] Stop levels for low-vol names (large-cap tech like MSFT/AAPL) should cluster near 3% floor; high-vol energy/small-cap near 8% cap
- [ ] Factor loop journal entry notes "stop=atr" or equivalent — confirms live system is using new logic, not fixed 5%
- [ ] Over 4 weeks: stop-hit rate drops materially vs historical ~55% baseline (target: <45% based on backtest predicting 35%)

### Backtest UI surfacing (after Apr 17 deploy)
**Trigger**: Visit `/dashboard` and `/backtests` after Vercel redeploy.
- [ ] Dashboard Row 1 shows BacktestSummaryCard as 4th card with best-alpha variant + Sharpe + win rate
- [ ] BacktestSummaryCard links through to `/backtests` page on click
- [ ] `/backtests` page renders IC heatmap with 4 variants × 4 factors × 4 horizons
- [ ] Run comparison table shows 4+ completed runs sorted by alpha
- [ ] Clicking a row opens RunDetail with equity curve (Recharts) + trade log
- [ ] Factor IC `|t|≥2` markers correctly highlight statistically significant cells
- [ ] About Me page has new "Backtest Lab — The Scientific Method" section with 4 pillar cards

### Systematic Backtesting System (verified Apr 17)
Completed — first run showed baseline +24.0% alpha, short_mom_atr +29.3% alpha, stop-hit rate 55% → 35%. Promoted short_mom_atr to live via BASELINE_VARIANT update.

### Position Reconciliation (next factor loop run — Mar 21)
**Trigger**: First factor-loop run after `reconcile_positions()` deployed (Mar 20).
- [ ] `reconcile_positions()` called in Step 0 without error
- [ ] Detects MU/NVDA/TSM bracket exits that were missed (already stopped out on Alpaca)
- [ ] Exit trades recorded in trades table with `order_class: bracket_fill`
- [ ] Protective orders updated to `OrderStatus.FILLED`
- [ ] Journal entry written noting the bracket exits with entry/exit prices and P&L
- [ ] Subsequent steps operate on correct position count (6, not 8)
- [ ] No false positives — doesn't flag positions that are actually held

### AI Sector Heat Score (next factor loop run — Mar 18)
**Trigger**: First factor-loop run after `assess_ai_bubble_risk()` deployed (Mar 17).
- [ ] `assess_ai_bubble_risk()` called in Step 1.5 without error
- [ ] `ai_bubble_risk` memory key written (check `SELECT value FROM agent_memory WHERE key = 'ai_bubble_risk'`)
- [ ] Result contains: `score`, `level`, `smh_rsi`, `smh_vs_200ma_pct`, `basket_breadth_pct`, `nvda_forward_pe`
- [ ] Score is plausible (not 0 or 100 from a data error)
- [ ] Score ≤ 60: run proceeds normally; score 61–80: journal recap notes "AI sector heat elevated"; score > 80: at most 1 AI-basket BUY executed
- [ ] Dashboard AI Sector Heat card renders with score, RSI, 200MA gap, breadth %, and NVDA P/E
- [ ] NVDA forward P/E fallback works (uses AMD if NVDA P/E unavailable)

### Anti-Churn Rules (accumulates over time)
**Trigger**: After factor-loop has been running for 1+ week.
- [ ] No positions sold within 5 trading days of purchase (unless stop-loss)
- [ ] SELL only triggers below rank 100 or falling EPS revisions
- [ ] Rankings are stable day-to-day (3m+12m momentum windows smooth out noise)

### Updated About Me Page (after deploy)
**Trigger**: After Vercel redeploy with factor-based about-me component.
- [ ] Bio mentions "systematic, factor-based AI investor"
- [ ] Factor weights displayed (Momentum X%, Quality X%, Value X%, EPS Revision X%)
- [ ] Top 5 factor rankings shown with composite scores
- [ ] No reference to explore/balanced/exploit lifecycle
- [ ] Skills section shows factor-based capabilities

### Reflection with Factor Evaluation (next 4pm run after factor-loop)
**Trigger**: First 4pm reflection after a factor-loop run.
- [ ] Reflection evaluates factor performance (did high-composite stocks move favorably?)
- [ ] Factor weight assessment included (which factors contributing to winners?)
- [ ] No reference to stage management or subjective confidence calibration

### Weekly Review Factor Optimization (next Sunday run)
**Trigger**: First Sunday weekly review after factor system is active. **Verified Mar 17 (ran Mar 15).**
- [x] Factor attribution analysis performed — "Factor System First Test - Alpha in Adversity" reviewed momentum vs quality contributions
- [x] Ranking stability assessed — turnover in top 20 analyzed, MU held #1 throughout week
- [x] Factor weight adjustment considered — `factor_weights` updated Mar 15 (55h ago) ✅
- [x] `factor_weights` memory updated with reason — confirmed updated by weekly review ✅

### Sector-Agnostic Fix (Monday Mar 16 10am factor loop)
**Trigger**: First weekday factor-loop trading run after full strategy memory cleanup (Mar 14).
- [x] Strategy memory shows `approach: "factor_based_systematic"` and sector-agnostic `core_themes`
- [x] Legacy fields removed: `validated`, `confidence_scoring` formula, tech-focused `pre_trade_checklist`
- [x] NEM, AA, or other non-tech stocks in top rankings are NOT blocked — VAL #5 (Energy), AA #8 (Materials), MRK #9 (Healthcare), AMG #10 (Financials) all scored freely in Mar 17 rankings
- [x] BUY signals generated purely on composite score threshold — WDC BUY, no sector gate
- [x] Journal entry does NOT contain "outside mandate" or "outside AI infrastructure" language — verified zero matches post-Mar 13

**Note**: Mar 14 Saturday run still showed sector bias despite skill update — root cause was
legacy fields in strategy memory (`validated` said "AI infrastructure focus", `pre_trade_checklist`
said "Is tech outperforming?"). Full strategy memory replaced Mar 14.

### Catalyst Discovery (next Saturday run — Mar 21)
**Trigger**: First Saturday factor-loop weekend variant where agent actually calls `discover_catalysts()`.
- [x] `upcoming_catalysts` memory key written with events array (manually seeded Mar 14)
- [x] Each event has: symbol, date, category, significance, trading_implication
- [ ] Catalyst events appear as purple dots in calendar UI (verify after Vercel deploy)
- [ ] `discover_catalysts()` tool called autonomously by agent during weekend variant
- [ ] Agent interprets raw results and sets correct significance/trading_implication
- [ ] Weekend journal entry mentions catalyst discoveries

**Note**: Mar 14 Saturday run did NOT call discover_catalysts() — agent skipped the step.
Memory was manually seeded with GTC (Mar 16), AA J.P. Morgan (Mar 17), TSMC Symposium (Apr 15).
Tool query improved: uses company names + topic="general" for better search quality.
Verify agent calls it autonomously on Mar 21.

### SPY Close Fix (next 4pm EOD reflection)
**Trigger**: First 4pm reflection after yfinance SPY fix deployed (Mar 13). **Verified Mar 17.**
- [x] `equity_snapshots` for today has non-zero `spy_close` — Mar 16: $668.95, Mar 13: $662.29, Mar 12: $671.11, all valid
- [x] `spy_cumulative_return` is reasonable — Mar 16: -1.11% vs portfolio +0.73% = alpha +1.84% ✅
- [x] Benchmark card in UI shows correct SPY return — data is clean in equity_snapshots

### Post-Earnings Protocol (MU — March 19 morning run)
**Trigger**: MU reports earnings March 18 after market close. First 10am run on March 19 tests the new protocol.
- [ ] Agent treats MU as high-priority in Step 3.5 (earnings reaction)
- [ ] Runs `internet_search("MU earnings results Q2 2026")` for actual numbers
- [ ] LLM interprets earnings qualitatively (the speed edge)
- [ ] Decision logged with `source: earnings_reaction` in reasoning
- [ ] Max 1-2 earnings-driven actions in the run
- [ ] Compares actual EPS to the `eps_estimate: 8.9747` from `upcoming_earnings` memory
- [ ] Writes structured `earnings_reaction:MU` memory
- [ ] If thesis broken → SELL signal generated
- [ ] If thesis strengthened → fast-track BUY before analyst revisions

### Daily Recap Format (next 4pm run)
**Trigger**: Next weekday 4pm reflection.
- [ ] Recap appears in chat tab under user's conversations
- [ ] First message shows clean user prompt (not raw SQL instructions)
- [ ] Recap is ~150 words, focused on market/research/trades/watchlist
- [ ] No self-reflection or verbose diary entries

### Dashboard Restructure (manual check)
**Trigger**: After Vercel redeploy.
- [ ] Dashboard shows 3 top cards (Performance, Lifecycle, Benchmark)
- [ ] Portfolio summary shows live Alpaca data (equity, cash, buying power, P&L)
- [ ] Positions table renders current holdings
- [ ] Benchmark card shows "—" with "X% deployed" when <50% deployed
- [ ] Watchlist and trades still display correctly
- [ ] About Me page has ReleaseLog in right sidebar (no more Performance/Lifecycle cards)

### Alpha Calculation Fix (accumulates over time)
**Trigger**: Once portfolio is >50% deployed. **Verified Mar 17.**
- [x] Alpha shows a real number — Mar 16 alpha +1.84% (deployed 63%) ✅
- [x] `deployed_pct` column populated — Mar 16: 63.0%, Mar 13: 44.3%, Mar 12: 25.2% ✅
- [x] Alpha is reasonable — +1.84% reflects genuine outperformance, not cash drag distortion ✅

### Earnings Profile Bootstrap for New Positions (next 1-2 runs)
**Trigger**: MU, NVDA, CRUS added Mar 16-17; profiles bootstrap at max 3/run in Step 3.5a.
- [ ] `earnings_profile:MU` created (should be first — highest rank #1)
- [ ] `earnings_profile:NVDA` created
- [ ] `earnings_profile:CRUS` created
- [ ] All 8 positions have matching earnings profiles (currently 5/8: WDC, TSM, STX, LRCX, AMAT)
- [ ] New profiles appear in Earnings Intelligence card on dashboard

### Earnings Guard Hardening (next factor loop buying near earnings)
**Trigger**: After deploying yfinance fallback + hard block in risk.py.
- [ ] `earnings_calendar()` returns MU earnings date via yfinance fallback (Finnhub missed it)
- [ ] `upcoming_earnings` memory key includes MU after next run
- [ ] MU earnings appear on calendar UI (orange dot on March 18)
- [ ] Risk check hard-blocks any buy within 2 days of earnings (`approved: false`)
- [ ] 3-5 day earnings proximity shows as warning (not block)

### Catalyst Intelligence in Factor Loop (next weekday run)
**Trigger**: After deploying Step 3.25 rewrite + memory loader fix. **Verified Mar 17.**
- [x] Agent searches for active catalysts — GTC 2026 keynote (Mar 16) found and assessed
- [x] Journal includes "## Catalyst Watch" section — Mar 17 1pm journal shows full GTC analysis covering Jensen Huang's $1T Blackwell/Vera Rubin orders
- [x] Catalyst assessment covers all affected holdings — MU, AMAT, LRCX, WDC, STX, CRUS all mentioned
- [x] Catalysts do NOT override factor scores — WDC BUY was factor-driven (composite 86.5), GTC provided thesis support only
- [x] Medium-significance catalysts within 7 days appear in agent context ✅

### Catalyst Guard in Factor Loop (Monday Mar 16 or later)
**Trigger**: First weekday factor loop with `upcoming_catalysts` memory populated. **Verified Mar 17.**
- [x] Step 3.25 reads catalyst memory and logs guard actions — GTC referenced in Catalyst Watch section
- [x] GTC (Mar 16-19) recognized as `hold_through` — all semi positions held through GTC window, no premature sells
- [x] No false blocks — WDC BUY executed normally during GTC week, not blocked by catalyst guard ✅

---

## Verified (completed)

### Sector-Agnostic Fix (Verified Mar 17)
- [x] Strategy `approach: "factor_based_systematic"`, sector-agnostic universe
- [x] VAL (Energy), AA (Materials), MRK (Healthcare), AMG (Financials) all rank freely in top 10
- [x] Zero "outside mandate" / "outside AI infrastructure" language since Mar 13
- [x] BUY signals purely composite-score driven

### SPY Close Fix (Verified Mar 17)
- [x] spy_close non-zero on all snapshots since Mar 11
- [x] spy_cumulative_return reasonable (-1.11% as of Mar 16)

### Alpha Calculation Fix (Verified Mar 17)
- [x] Alpha +1.84% showing at 63% deployed
- [x] deployed_pct column fully populated

### Catalyst Intelligence in Factor Loop (Verified Mar 17)
- [x] "## Catalyst Watch" section in every factor loop journal
- [x] GTC assessed across all semiconductor holdings
- [x] Catalysts inform thesis but don't override factor scores

### Catalyst Guard in Factor Loop (Verified Mar 17)
- [x] GTC correctly treated as hold_through, no false blocks on BUYs

### Weekly Review Factor Optimization (Verified Mar 17)
- [x] Factor attribution performed Mar 15
- [x] Factor weights updated with reasoning

### Factor-Based Scoring Pipeline (March 12-14)
- [x] `score_universe()` returns ~150 scored stocks (903 universe)
- [x] All factor scores are 0-100
- [x] `enrich_eps_revisions()` processes 20 symbols
- [x] EPS revision scores: rising → 70-90, flat → 50-62, falling → 22-38
- [x] `generate_factor_rankings()` produces BUY/SELL/HOLD signals
- [x] BUY signals: top 20 by composite, composite > 70
- [x] HOLD signals: held stocks in top 50
- [x] Existing positions evaluated (not auto-dumped)

### Composite-Based Order Types (March 12-13)
- [x] `composite_score` parameter passed to `place_order()`
- [x] WDC (88.5) → market order, STX (78.7) → limit order, LRCX (78.0) → limit order
- [x] `confidence` auto-derived as `composite_score / 100`

### Factor Rankings Memory (March 12)
- [x] `factor_rankings` memory key written with top_10, factor_weights, scored_at
- [x] Journal entry type is "market_scan" with `run_source="factor_loop"`

### Reflection with Factor Evaluation (March 12-13)
- [x] Reflection evaluates factor performance (high-composite outperforming)
- [x] Factor weight assessment included
- [x] No reference to stage management

### Bracket Orders & Position Protection (March 11)
- [x] TSM position has bracket order (stop $335, target $410)
- [x] `position_health_check` reports `protected: true`

### Conviction-Based Orders (March 11)
- [x] TSM 0.845 confidence → market order (not limit 2% away)
- [x] MU/NVDA/LRCX below threshold → correctly waited

### Daily Recap Delivery (March 11)
- [x] `send_daily_recap` connects to LangGraph Platform (URL fix)
- [x] Thread created with correct user owner (auth fix)
- [x] Recap visible in chat conversation list

---

## How to Check Run Quality

```sql
-- Today's journal entries
SELECT entry_type, title, content, symbols, created_at
FROM agent_journal WHERE created_at >= CURRENT_DATE ORDER BY created_at;

-- Recent trades
SELECT symbol, side, quantity, order_type, limit_price, status, thesis, confidence
FROM trades WHERE created_at >= CURRENT_DATE ORDER BY created_at;

-- Structured memory updates
SELECT key, updated_at FROM agent_memory
WHERE updated_at >= CURRENT_DATE ORDER BY updated_at DESC;

-- Factor rankings snapshot
SELECT value FROM agent_memory WHERE key = 'factor_rankings';

-- Factor weights
SELECT value FROM agent_memory WHERE key = 'factor_weights';

-- Earnings tracking
SELECT value FROM agent_memory WHERE key = 'upcoming_earnings';
SELECT key, value FROM agent_memory WHERE key LIKE 'earnings_reaction:%';

-- Compare factor scores on stock analyses
SELECT key, value->>'composite_score' as composite, value->>'momentum_score' as momentum,
       value->>'quality_score' as quality, value->>'value_score' as value_score,
       value->>'eps_revision_score' as eps_rev
FROM agent_memory WHERE key LIKE 'stock:%' ORDER BY (value->>'composite_score')::float DESC NULLS LAST;
```
