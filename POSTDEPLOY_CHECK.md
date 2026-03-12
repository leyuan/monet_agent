# Verification Checklist

Ongoing checklist of features/behaviors to verify after deployment. When reviewing run quality, check pending items whose trigger conditions have been met.

---

## Pending Verification

### Factor-Based Scoring Pipeline (first factor-loop run)
**Trigger**: First cron run using `/skills/factor-loop/SKILL.md`.
- [ ] `score_universe()` returns ~150 scored stocks in < 2 minutes
- [ ] All factor scores are 0-100 (momentum, quality, value, composite)
- [ ] `eps_revision_score` defaults to 50 before enrichment
- [ ] 4-hour cache works — second call in same window returns `cached: true`
- [ ] `enrich_eps_revisions()` processes 20 symbols without rate limit errors
- [ ] Finnhub calls stay under 60/min limit
- [ ] EPS revision scores: rising → 70-85, flat → 50, falling → 15-30
- [ ] `generate_factor_rankings()` produces correct BUY/SELL/HOLD signals
- [ ] BUY signals: top 20 by composite, not held, composite > 70
- [ ] SELL signals: held stocks below rank 100 OR eps_revision < 30
- [ ] HOLD signals: held stocks still in top 50
- [ ] Existing positions are evaluated (not auto-dumped)

### Composite-Based Order Types (first factor-loop trade)
**Trigger**: First BUY signal executed via factor-loop.
- [ ] `composite_score` parameter passed to `place_order()`
- [ ] Score > 80 → market order placed
- [ ] Score 70-80 → limit order 1% below current price
- [ ] Score 60-70 → limit order 3% below current price
- [ ] `confidence` auto-derived as `composite_score / 100`

### Anti-Churn Rules (accumulates over time)
**Trigger**: After factor-loop has been running for 1+ week.
- [ ] No positions sold within 5 trading days of purchase (unless stop-loss)
- [ ] SELL only triggers below rank 100 or falling EPS revisions
- [ ] Rankings are stable day-to-day (3m+12m momentum windows smooth out noise)

### Factor Rankings Memory (first factor-loop run)
**Trigger**: First completed factor-loop run.
- [ ] `factor_rankings` memory key written with top_10, factor_weights, scored_at
- [ ] `update_stock_analysis()` includes composite_score, momentum_score, quality_score, value_score, eps_revision_score
- [ ] `record_decision()` uses `composite_score / 100` as confidence
- [ ] Journal entry type is "market_scan" with `run_source="factor_loop"`

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

### Factor vs Legacy Comparison (1 week after parallel run)
**Trigger**: After running both factor-loop and trading-loop for 1 week.
- [ ] Compare journal entries: factor-loop has concise factor scores, not narrative essays
- [ ] Compare decision quality: do high-composite picks outperform subjective picks?
- [ ] Compare churn: factor system should have fewer trades due to anti-churn rules
- [ ] Decision: full cutover or continue parallel

---

## Verified (completed)

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
