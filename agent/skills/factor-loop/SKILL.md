# Factor-Based Trading Loop

You are running the **factor-based trading loop** — a systematic, quantitative approach to stock selection and trading. Factor scoring is deterministic Python; your role is orchestration, earnings interpretation, and execution.

**Key principle**: Factor scores drive decisions. You do NOT form subjective theses, generate bull/bear cases, or score confidence via vibes. The composite score IS the confidence.

**The factor system is sector-agnostic.** If the `strategy` memory contains a sector focus (e.g. "AI infrastructure"), that is a legacy preference — it does NOT override factor rankings. A materials stock ranked #4 with composite 80 gets the same treatment as a tech stock ranked #4. The only valid filters are: factor rank, earnings guard, catalyst guard, VIX regime rules, and risk checks. Never block a BUY signal because it's "outside the mandate."

## Step 0: Load Context (ALWAYS DO THIS FIRST)

1. Run `read_all_agent_memory()` to load all persistent beliefs
2. Read your last 3 journal entries:
   ```sql
   SELECT entry_type, title, content, symbols, created_at FROM agent_journal ORDER BY created_at DESC LIMIT 3
   ```
3. Check for user insights (last 3 days):
   ```sql
   SELECT title, content, symbols, created_at FROM agent_journal
   WHERE entry_type = 'user_insight' AND created_at >= NOW() - INTERVAL '3 days'
   ORDER BY created_at DESC
   ```
4. **Check POSTDEPLOY_CHECK.md for pending items whose trigger is today or has passed.**
   Read the file at `skills/../../../POSTDEPLOY_CHECK.md` (relative to the agent root). For each pending item whose trigger condition is met this run, verify it during the appropriate step and note the result in Step 5's journal entry (one bullet per verified item). Do not block trading to verify — work checks into steps that already run the relevant tool.

---

## Step 1: Market Regime Check

- Run `market_breadth()` to assess overall market regime
- Run `sector_analysis("1mo")` to see sector leadership/rotation
- Get quotes for SPY, QQQ, and VIX (via `get_stock_quote`)
- Call `update_market_regime()` with findings

**VIX regime adjustment**: If VIX > 30:
- Increase cash buffer from 20% to 30%
- Note this for Step 4 — the generate_factor_rankings tool will use 8 max positions but you should limit to 6

---

## Step 1.5: AI Bubble / Concentration Risk Check

Call `assess_ai_bubble_risk()`. It uses the live portfolio you already fetched in Step 1
and downloads SMH vs SPY data internally.

Store the result: `write_agent_memory("ai_bubble_risk", result)`

**Do NOT use this to block BUY signals or force SELLs.** The factor composite IS the decision.

Use it as follows:
- Score ≤ 60: Proceed normally. Optionally note score in journal.
- Score 61–80: Note "AI sector heat elevated (score: X, SMH RSI: Y, breadth: Z%)" in the Step 5 journal recap section.
- Score > 80: Apply ONE soft cap — execute at most 1 new BUY from the AI/semi basket this run
  (not per day — per run). Still execute all SELL signals normally.

---

## Step 2: Score Universe

This is the core of the factor loop. Three tool calls, in sequence:

### 2a. Score the universe
```
score_universe(top_n=30)
```
Returns ~150 scored stocks ranked by composite factor score (momentum + quality + value). Takes ~75 seconds on first call, cached for 4 hours.

### 2b. Enrich top candidates with EPS revisions
```
enrich_eps_revisions(symbols=[top 20 symbols from 2a])
```
Calls Finnhub for EPS estimate revision data. Rising revisions = strong buy signal.

### 2c. Generate actionable signals
```
generate_factor_rankings(
    universe_scores=[full rankings from 2a],
    eps_enrichment=[enrichment from 2b],
    held_symbols=[symbols from portfolio]
)
```
Returns BUY, SELL, and HOLD signals with position sizing.

---

## Step 3: Earnings Guard

For each BUY signal from Step 2:
- Run `earnings_calendar(symbols=[buy signal symbols])`
- **Remove any BUY signal where earnings are within 5 days** — binary risk

### Step 3.25: Catalyst Intelligence

Check `upcoming_catalysts` from memory (loaded in Step 0). Identify any catalyst that is **happening today, happened since last run, or is within 3 days** and overlaps with held positions or BUY candidates.

#### 3.25a: Research active catalysts
For each relevant catalyst (max 2 per run):
1. `internet_search("[symbol] [catalyst title] [date]")` — learn what actually happened or what's expected
2. Summarize in 2-3 bullet points: key announcements, market reaction, implications for the sector
3. Assess impact on **each held position** that the catalyst affects (not just the primary symbol — e.g., NVIDIA GTC affects all semiconductor holdings)

#### 3.25b: Apply to signals
- If a catalyst with `trading_implication: "avoid_entry"` is within 3 days: remove the BUY signal
- If `trading_implication: "catalyst_buy"`: keep signal, note catalyst as tailwind
- If `trading_implication: "reduce_before"` within 2 days: flag HOLD for potential trim in Step 4

#### 3.25c: Discipline check
**Catalysts do NOT override factor scores.** A great keynote doesn't turn a rank #50 stock into a buy. A disappointing conference doesn't force a sell on a rank #3 stock with strong factors. Catalysts provide **context for the journal** and may influence hold/trim decisions at the margin, but the composite score remains the primary signal. Note the catalyst impact in Step 5's journal entry — readers want to know you're aware of major events affecting the portfolio.

### Step 3.5: Earnings Reaction (the speed edge)

This is where the LLM adds real value — qualitative earnings interpretation before analyst revisions update.

**Step 3.5a: Bootstrap earnings profiles for any stock without one**
For each held position or top-10 BUY candidate that lacks an `earnings_profile:SYMBOL` in memory:
1. Call `get_earnings_results(symbol)` — returns 4 quarters of surprise history + forward estimates
2. Derive `pattern` from the history (systematic_underestimation, volatile, reliable_beater, declining, turnaround)
3. Write `agent_insight` — one actionable sentence synthesizing what the pattern means for trading
4. Save: `write_agent_memory("earnings_profile:SYMBOL", { symbol, quarters_tracked, avg_surprise_pct, beat_streak, beat_rate, pattern, guidance_reliability, key_metric, history: [{quarter, surprise_pct, thesis_impact, action, highlights: []}], agent_insight, bootstrapped_at, last_updated })`
5. Max 3 bootstraps per run (don't burn all tokens on profiles)

**Step 3.5b: React to new earnings**
For stocks that reported since the last run (check `recent_surprises` from `earnings_calendar()` in Step 3):

Data gathering (structured FIRST, qualitative SECOND):
1. `get_earnings_results(symbol)` — actual_eps, estimated_eps, surprise_pct, summary stats
2. Read existing `earnings_profile:SYMBOL` — does this result fit the pattern?
3. `internet_search("[SYMBOL] earnings results Q[X] [year]")` — for qualitative highlights: management commentary, guidance details, strategic announcements. Extract 1-3 bullet highlights for the profile.

Decision framework:
- **Pattern continues** (e.g., reliable beater beats again): HOLD, update profile, no drama
- **Pattern breaks** (e.g., reliable beater misses): High alert — check qualitative context, consider SELL
- **Positive surprise + rising forward estimates**: thesis strengthened, fast-track BUY for non-held candidates
- **This is the speed edge**: act at 10am on overnight earnings, hours before estimate revisions update

After each reaction:
- Append new quarter to `earnings_profile:SYMBOL` history (with highlights from internet_search)
- Update stats (avg_surprise_pct, beat_streak, beat_rate)
- Revise `agent_insight` and `pattern` if warranted
- Write `record_decision()` with `source: earnings_reaction`

**Rules:**
- Max 1-2 earnings-driven trade actions per run
- Earnings overrides can bypass composite threshold if results are transformative
- Profile updates (no trade action) don't count toward the limit

---

## Step 4: Execute Signals

**Order: SELL first, then BUY in rank order.**

### Sells
For each SELL signal:
1. `check_trade_risk(symbol, "sell", quantity)`
2. `place_order(symbol, "sell", quantity, order_type="market")`
3. Anti-churn: Do NOT sell positions held < 5 trading days unless stop-loss hit

### Buys
For each BUY signal (after removing earnings-blocked ones):
1. `check_trade_risk(symbol, "buy", quantity)`
2. `place_order(symbol, "buy", quantity, composite_score=score, take_profit_price=..., stop_loss_price=...)`
   - The `composite_score` parameter auto-derives order type:
     - Score > 80 → Market order
     - Score 70-80 → Limit 1% below current
     - Score 60-70 → Limit 3% below current
   - Stop loss: 5% below entry
   - Take profit: 15% above entry (or use sector-appropriate target)

### Position Management
For each HOLD signal, run `position_health_check(symbol)`:
- If `protected: false` → `attach_bracket_to_position()` immediately
- If up 15%+ → tighten stop to breakeven
- If approaching target exit → consider trimming 50%

### Anti-Churn Rules
- **Hysteresis on SELL**: Only sell if rank drops below 100 (not just out of top 20), OR eps_revision < 30, OR stop-loss hit
- **Minimum hold period**: Don't sell positions held < 5 trading days unless stop-loss triggers
- **Smooth signals**: 3m+12m momentum windows are inherently stable — rankings won't whipsaw daily

---

## Step 5: Record

### Update stock analyses
For each signal acted on, call `update_stock_analysis()` with factor scores:
```
update_stock_analysis(
    symbol=...,
    thesis=f"Rank #{rank}: Momentum {mom}, Quality {qual}, Value {val}, EPS Rev {eps}",
    target_entry=current_price * 0.95,
    target_exit=current_price * 1.15,
    confidence=composite_score / 100,
    composite_score=composite_score,
    momentum_score=momentum_score,
    quality_score=quality_score,
    value_score=value_score,
    eps_revision_score=eps_revision_score,
)
```

### Record decisions
For every BUY/SELL/HOLD/WAIT, call `record_decision()`:
- `confidence` = `composite_score / 100`
- `reasoning` = factor-based summary, not narrative

### Save factor rankings snapshot
Pass through the EXACT objects from `score_universe()` output — do NOT rename or abbreviate fields:
```
write_agent_memory("factor_rankings", {
    "top_10": rankings[:10],  // each entry must include: rank, symbol, sector, composite_score, momentum_score, quality_score, value_score, eps_revision_score, current_price
    "factor_weights": weights,
    "scored_at": timestamp,
    "universe_size": ...,
    "vix_at_scoring": ...
})
```

### Write journal entry
Type: "market_scan" or "trade"
- **HARD LIMIT: 3000 characters max** — trim ruthlessly before writing. If your draft exceeds this, cut it.
- **MAX 400 words** — this is a factor log, not an essay
- Include: top 10 rankings table, signals generated, actions taken, regime summary
- **If active catalysts from Step 3.25**: add a "## Catalyst Watch" section (2-4 sentences) summarizing what happened, how it affects holdings, and whether it changes any thesis. This is where readers see that you're tracking real-world events, not just numbers.
- Do NOT write "Key Findings", "Insights", strategic commentary, or grades — just the data
- Do NOT repeat the full rankings table if one was written in the same day — a compact summary of changes is sufficient
- Set `run_source="factor_loop"` (or `"factor_loop_weekend"` on Saturday)

---

## Weekend Variant (Saturday)

On Saturday:
- Run `score_universe(top_n=50)` instead of 30 — broader view
- Still enrich top 20 with EPS revisions
- **No execution** — market is closed. Skip Step 4 entirely.
- Write a comprehensive journal entry with the full top 50 ranking
- Compare this week's rankings vs last week's (from `factor_rankings` memory)
- Note which stocks entered/exited the top 20

### Weekend Catalyst Discovery
After scoring, discover upcoming catalysts for the next 30 days:
1. Run `discover_catalysts(days_ahead=30)`
2. Review raw search results — for each genuine catalyst:
   - Assess `significance` (high/medium/low) based on historical impact of similar events
   - Set `trading_implication`: hold_through / avoid_entry / catalyst_buy / reduce_before
   - Write one-line `impact_thesis`
3. Write results: `write_agent_memory("upcoming_catalysts", { events: [...], fetched_at: ..., symbols_checked: [...] })`
4. Note discoveries in the weekend journal entry

---

## Anti-Patterns (DO NOT)

- Do NOT run `company_profile()`, `peer_comparison()`, or `fundamental_analysis()` in this loop — factor scores replace narrative analysis
- Do NOT generate subjective confidence scores — composite_score IS confidence
- Do NOT write multi-paragraph theses — factor summary string is sufficient
- Do NOT skip `enrich_eps_revisions()` — EPS revisions are the strongest alpha signal
- Do NOT override factor signals with "gut feel" — the whole point is systematic discipline
- Do NOT filter by sector or "mandate" — the factor system is sector-agnostic. If NEM ranks #4, it gets treated like any #4 stock.
- Do NOT sell on small rank changes — only sell below rank 100 or on falling EPS revisions
- The ONLY place for LLM judgment is Step 3.5 (earnings reaction) — everywhere else, follow the numbers
