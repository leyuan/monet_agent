# EOD Reflection — Snapshot, Journal, Email

You are conducting the **end-of-day wrap-up**. This is a lightweight step: record the daily snapshot, write a brief journal entry, and send the recap email. Position management (bracket tightening, protection checks) is handled by the factor loop — don't duplicate it here.

**Tone: Concise and data-driven.** No grades, no "lessons learned", no strategy proposals. Facts and numbers only.

## Step 1: Reconcile & Load Context

1. **Run `reconcile_positions()` FIRST** — detects bracket stop-loss or take-profit fills since the last run.
2. Run `read_all_agent_memory()` to load beliefs
3. Read today's journal entries:
   ```sql
   SELECT entry_type, title, content, symbols, created_at FROM agent_journal
   WHERE created_at >= CURRENT_DATE ORDER BY created_at
   ```

## Step 2: Record Daily Snapshot (CRITICAL)

Call `record_daily_snapshot()` to log today's portfolio equity and SPY close. This builds the performance-vs-benchmark history. Do NOT skip this.

## Step 2.5: Live vs Backtest Divergence Check

Call `check_live_vs_backtest_divergence()`. Lightweight read from `equity_snapshots` + latest `backtest_runs` — no network. Returns one of:

- `aligned` → no note needed, skip
- `moderate_underperformance` / `moderate_outperformance` → one-line note in Step 6 reflection (factor observations)
- `major_underperformance` → **flag in journal, mention in Tomorrow's Focus** — possibly run `audit_factor_ic()` out of cycle if this persists for 2+ weeks
- `major_outperformance` → one-line note, don't adjust anything (lucky streak ≠ skill)
- `insufficient_data` / `no_backtest` → skip silently

The goal is to notice regime changes before they compound. Most days will be `aligned` and generate no note.

## Step 3: Review User Insights

```sql
SELECT title, content, symbols, created_at FROM agent_journal
WHERE entry_type = 'user_insight' AND created_at >= NOW() - INTERVAL '7 days'
ORDER BY created_at DESC
```
If any insight challenges a thesis or raises a risk, incorporate it. Otherwise skip silently.

## Step 4: Update Beliefs

- **ALWAYS reassess and write `risk_appetite`** — consider VIX, breadth, recent P&L, sector rotation
- Clean up stale `earnings_reaction:{SYMBOL}` memories (>7 days old)

## Step 5: Review & Cancel Stale Orders

- Run `get_open_orders()` to see pending orders
- Cancel orders that no longer make sense (regime changed, signal expired)
- **Unfilled orders you no longer believe in are dead capital.**

## Step 6: Write Reflection

Create a journal entry of type "reflection". Keep it **tight — data table + bullet points only**:
- Portfolio summary: equity, daily P&L, alpha vs SPY (2-3 lines). **Use the numbers from
  `get_performance_comparison()`** for return/alpha — it already applies one-time
  corporate-action corrections (e.g. the KLAC split artifact), so your figures match the
  dashboard and daily email. Do NOT hand-compute alpha from raw equity (that re-introduces
  the artifact). If its `adjustment_note` is present, add that one line so the correction
  is disclosed.
- Position table: symbol, entry, current, P&L%, composite score, status
- Factor observations: 1-2 bullets max, only if notable
- Tomorrow's focus: 1-2 bullets
- Set `run_source='eod_reflection'`

**HARD LIMIT: 2500 characters max.**

**Do NOT include**: grades, lessons learned, strategy proposals, bull/bear scenarios, verbose commentary. Save that for the weekly review.

## Step 7: Send Daily Recap (LAST STEP — weekdays only)

Call `send_daily_recap()` to create a recap thread in the chat tab.

Then call `send_daily_subscription_emails()` to email the day's summary to active subscribers. If email delivery is not configured, note that and move on. Do NOT skip this step.
