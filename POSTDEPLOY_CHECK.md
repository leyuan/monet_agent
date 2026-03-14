# Verification Checklist

Ongoing checklist of features/behaviors to verify after deployment. When reviewing run quality, check pending items whose trigger conditions have been met.

---

## Pending Verification

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
**Trigger**: First Sunday weekly review after factor system is active.
- [ ] Factor attribution analysis performed (which factor drove winners/losers?)
- [ ] Ranking stability assessed (turnover in top 20 vs last week)
- [ ] Factor weight adjustment considered (±0.05 max per week)
- [ ] If adjusted, `factor_weights` memory updated with reason

### Sector-Agnostic Fix (Monday Mar 16 10am factor loop)
**Trigger**: First weekday factor-loop trading run after full strategy memory cleanup (Mar 14).
- [x] Strategy memory shows `approach: "factor_based_systematic"` and sector-agnostic `core_themes`
- [x] Legacy fields removed: `validated`, `confidence_scoring` formula, tech-focused `pre_trade_checklist`
- [ ] NEM, AA, or other non-tech stocks in top rankings are NOT blocked by "AI infrastructure mandate"
- [ ] BUY signals generated purely on composite score threshold, regardless of sector
- [ ] Journal entry does NOT contain "outside mandate" or "outside AI infrastructure" language

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
**Trigger**: First 4pm reflection after yfinance SPY fix deployed (Mar 13).
- [ ] `equity_snapshots` for today has non-zero `spy_close`
- [ ] `spy_cumulative_return` is reasonable (not -100%)
- [ ] Benchmark card in UI shows correct SPY return

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
**Trigger**: Once portfolio is >50% deployed.
- [ ] Alpha shows a real number instead of "—"
- [ ] `deployed_pct` column populated in equity_snapshots
- [ ] Alpha is reasonable (not -22% from cash drag)

### Catalyst Guard in Factor Loop (Monday Mar 16 or later)
**Trigger**: First weekday factor loop with `upcoming_catalysts` memory populated.
- [ ] Step 3.25 reads catalyst memory and logs any guard actions
- [ ] GTC (Mar 16-19) recognized as `hold_through` for held semi positions
- [ ] No false blocks — `hold_through` events don't prevent BUY signals

---

## Verified (completed)

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
