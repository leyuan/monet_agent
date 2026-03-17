# Verification Checklist

Ongoing checklist of features/behaviors to verify after deployment. When reviewing run quality, check pending items whose trigger conditions have been met.

---

## Pending Verification

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
