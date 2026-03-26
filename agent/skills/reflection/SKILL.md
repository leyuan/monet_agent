# Reflection Phase (Standalone EOD)

You are conducting the **end-of-day reflection**. This is a review of today's activity AND an opportunity to adapt — tighten protective brackets, cancel stale orders, update beliefs. No new research or new entries, but actively manage existing positions.

**Tone: Be concise and data-driven.** No self-grading (no letter grades), no "lessons learned" sections, no strategic proposals or multi-paragraph commentary. State the facts, take action where warranted, move on.

## Step 0: Load Context (ALWAYS DO THIS FIRST)

1. **Run `reconcile_positions()` FIRST** — detects any bracket stop-loss or take-profit fills that Alpaca executed since the last run. Records exits in trades table and writes a journal entry.
2. Run `read_all_agent_memory()` to load all persistent beliefs
3. Read today's journal entries:
   ```sql
   SELECT entry_type, title, content, symbols, created_at FROM agent_journal
   WHERE created_at >= CURRENT_DATE ORDER BY created_at
   ```
4. Read today's decisions:
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

### 3b. Position Protection & Bracket Management (TAKE ACTION)
For each held position, run `position_health_check(symbol)`. It returns `peak_pnl_pct` (highest P&L since entry) and `drawdown_from_peak_pct` (how far current price is below the peak).

**Protection check:**
- If `protected: false` → `attach_bracket_to_position()` immediately

**Bracket tightening — act on these, don't just note them:**

Review the peak P&L and drawdown for each position. If a position has run up and is now giving back gains, tighten the bracket to lock in profits. To tighten: cancel the existing protective order first (`cancel_order`), then `attach_bracket_to_position()` with the new levels.

| Condition | Action | New Stop | New TP |
|-----------|--------|----------|--------|
| Peak ≥10%, drawdown from peak ≥5% | **Tighten** | Entry price (breakeven) | Keep current TP |
| Peak ≥12%, drawdown from peak ≥5% | **Tighten** | +5% above entry | Lower TP to +12% |
| Peak ≥5% AND VIX >26 | **Tighten** | Entry price (breakeven) | Keep current TP |
| Peak <5% or drawdown <3% | No action | — | — |

**Only tighten upward.** Before acting, compare the proposed new stop to the existing stop (from `position_health_check` → protective order data). If the existing stop is already at or above the proposed level, skip — the bracket is already tight enough. Never loosen a stop. This prevents daily cancel/re-attach churn on positions that were already tightened.

Log each actual adjustment in the journal: "Tightened AMAT stop from $320 → $338 (breakeven) after peak +12.4%, now +8.9%, drawdown -3.1%."

### 4. Factor Performance Evaluation
- For each trade today: note composite score, fill price, and current P&L in a single line
- One-sentence summary: did high-composite stocks (80+) outperform today? Yes/no + data.
- Do NOT write multi-paragraph analysis or grade yourself — just the numbers.

### 5. Factor Weight Assessment
- One-line observation per factor: is it contributing to winners or losers?
- If nothing notable, write "No weight observations today" and move on
- Save deeper analysis for the weekly review — do NOT propose weight changes here

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
Create a journal entry of type "reflection". Keep it **tight — data table + bullet points only**:
- Portfolio summary: equity, daily P&L, alpha vs SPY (2-3 lines)
- Position table: symbol, entry, current, P&L%, composite score, status (HOLD/WATCH)
- Factor observations: 1-2 bullet points max, only if something notable happened
- Tomorrow's focus: 1-2 bullets
- Set `run_source='eod_reflection'`

**HARD LIMIT: 2500 characters max.** Count your characters before writing. If over the limit, cut the factor observations and tomorrow's focus sections first.

**Do NOT include**: self-assessment grades, lessons learned, strategic proposals, "what went well / what could improve", bull/bear scenario planning, or verbose commentary. Save that for the weekly review.

### 10. Send Daily Recap (LAST STEP — weekdays only)
Call `send_daily_recap()` to create a recap thread in the chat tab. This gives the user a summary without digging through journal entries.

Then call `send_daily_subscription_emails()` to email the same day's summary to active subscribers. If email delivery is not configured, note that and move on. Do NOT skip this step.

## Reflection Principles
- Be honest about mistakes — don't rationalize bad trades
- Focus on whether the factor system is producing good signals, not individual outcomes
- Small, incremental observations > overhauls
- **The reflection is a daily log, not a strategy document.** Keep it under 400 words.
- Save deep analysis, weight change proposals, and strategic thinking for the **weekly review**
