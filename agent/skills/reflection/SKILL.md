# Reflection Phase (Standalone EOD)

You are conducting the **end-of-day reflection**. This is a lightweight review of today's activity — no research, no trading.

## Step 0: Load Context (ALWAYS DO THIS FIRST)

1. Run `read_all_agent_memory()` to load all persistent beliefs
2. Read today's journal entries:
   ```sql
   SELECT entry_type, title, content, symbols, created_at FROM agent_journal
   WHERE created_at >= CURRENT_DATE ORDER BY created_at
   ```
3. Read today's decisions:
   ```sql
   SELECT key, value FROM agent_memory
   WHERE key LIKE 'decision:%' AND value->>'decided_at' >= CURRENT_DATE::text
   ORDER BY key
   ```

## Workflow

### 1. Review User Insights (last 7 days)
```sql
SELECT title, content, symbols, created_at FROM agent_journal
WHERE entry_type = 'user_insight' AND created_at >= NOW() - INTERVAL '7 days'
ORDER BY created_at DESC
```
- For each insight: does it challenge a thesis, raise a missed risk, or suggest an opportunity?
- If useful, incorporate into reflection and update relevant memory
- If not useful, skip silently

### 2. Record Daily Snapshot (CRITICAL — do this every weekday)
Call `record_daily_snapshot()` to log today's portfolio equity and SPY close. This builds the performance-vs-benchmark history used in weekly reviews and chat. Do NOT skip this.

### 3. Observation Window — Today's P&L
- Run `get_portfolio_state` to see current positions and P&L
- For any trades placed earlier today (from journal/decisions), check current status
- Compare the decision reasoning to what actually happened
- Note: intraday P&L on same-day trades is noisy — focus on whether the setup was sound

### 3b. Position Protection Check
For each held position, run `position_health_check(symbol)`:
- If `protected: false` → attach a stop-loss immediately via `attach_bracket_to_position()`
- If position is up 15%+ → tighten stop to breakeven or higher (trailing stop)
- If position approaching target_exit → consider trimming 50%

### 4. Factor Performance Evaluation
- Load today's `factor_rankings` from memory
- Load today's `decision:*` memory entries
- For each BUY/SELL decision today:
  - What was the composite score at time of signal?
  - Was the fill price reasonable vs the score-implied order type?
  - Did high-composite stocks move favorably today?
- Track: are high-composite stocks (80+) outperforming low-composite (60-70)?

### 5. Factor Weight Assessment
- Review factor weight performance:
  - Are momentum-driven picks outperforming quality-driven picks?
  - Are value picks catching up or continuing to lag?
  - Is EPS revision signal adding alpha vs the 50-default baseline?
- Note any observations for the weekly review to consider weight adjustments

### 6. Update Beliefs
- Revise `market_outlook` if today's data warrants it
- **ALWAYS reassess and write `risk_appetite`** — consider:
  - Current VIX level (>25 = reduce risk, <20 = normal)
  - Market breadth
  - Recent P&L and drawdown
  - Sector rotation signal
- Clean up stale `earnings_reaction:{SYMBOL}` memories (>7 days old)

### 7. Review & Cancel Stale Orders
- Run `get_open_orders()` to see pending orders
- For each: do you still believe in it? Has regime changed? Was it premature?
- Cancel orders that no longer make sense
- **Rule: Unfilled orders you no longer believe in are dead capital.**

### 8. Clean Up Watchlist
- Remove symbols that no longer fit factor criteria (dropped below rank 100)
- Update targets based on new factor scores
- Prune weak candidates

### 9. Write Reflection
Create a journal entry of type "reflection" covering:
- Performance summary (wins/losses, total P&L)
- Factor performance: did high-composite stocks outperform?
- Factor weight observations (for weekly review)
- Strategy observations (if any)
- Set `run_source='eod_reflection'`

### 10. Send Daily Recap (LAST STEP — weekdays only)
Call `send_daily_recap()` to create a recap thread in the chat tab. This gives the user a summary without digging through journal entries. Do NOT skip this step.

## Reflection Principles
- Be honest about mistakes — don't rationalize bad trades
- Focus on whether the factor system is producing good signals, not individual outcomes
- Small, incremental observations > overhauls
- **Evaluate signal quality**: Did factor-driven trades outperform? Are the weights right?
- Most loops should result in NO trades — factor scoring identifies opportunity, not urgency
