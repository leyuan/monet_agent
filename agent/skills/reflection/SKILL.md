# Reflection Phase

You are conducting the **reflection phase** of your autonomous trading loop.

## Objective
Review recent performance, learn from outcomes, refine your strategy, and manage the explore/exploit lifecycle.

## Workflow

### 1. Review recent trades
- Load recent trades and check their current status/P&L
- Compare actual outcomes to your original thesis
- Identify which trades worked and which didn't

### 2. Analyze performance patterns
- Are your high-confidence trades outperforming low-confidence ones?
- Which sectors or strategies are working?
- Are you properly sizing positions?
- Are stop losses being hit too often or not at all?

### 3. Update beliefs
- Revise your `market_outlook` memory based on what you've observed
- Update your `strategy` memory if patterns suggest changes
- Adjust `risk_appetite` if appropriate

### 4. Clean up watchlist
- Remove symbols that no longer fit your thesis
- Update target prices based on new analysis
- Add new opportunities discovered during review

### 5. Update Stage Counters (CRITICAL)
Read `agent_stage` from memory and update its counters:

1. **Count watchlist profiles**: Query memory for all keys matching `company_profile_*` pattern. Use `query_database` with:
   ```sql
   SELECT COUNT(*) as count FROM agent_memory WHERE key LIKE 'company_profile_%'
   ```
   This gives you `watchlist_profiles`.

2. **Count completed trades**: Query the trades table:
   ```sql
   SELECT COUNT(*) as count FROM trades WHERE status != 'canceled'
   ```
   This gives you `total_trades`.

3. **Increment `cycles_completed`** by 1.

4. **Check stage transitions**:
   - **Explore → Balanced**: `watchlist_profiles >= 15` AND `cycles_completed >= 30`
   - **Balanced → Exploit**: `total_trades >= 10` AND `watchlist_profiles >= 25`

5. **Write updated `agent_stage`** to memory:
   ```json
   {
     "stage": "explore",
     "started_at": "2026-03-07",
     "watchlist_profiles": 5,
     "total_trades": 0,
     "cycles_completed": 6
   }
   ```
   If transitioning to a new stage, update `stage` and `started_at` to today's date.

### 6. Write reflection
- Create a journal entry of type "reflection" covering:
  - Performance summary (wins/losses, total P&L)
  - Key lessons learned
  - Strategy adjustments
  - Outlook for next trading period
  - Confidence calibration (were your scores accurate?)
  - Current stage and progress toward next stage transition

## Reflection Principles
- Be honest about mistakes — don't rationalize bad trades
- Look for systematic errors, not just individual outcomes
- Update your mental models based on evidence
- Small, incremental strategy adjustments are better than overhauls
- **Evaluate activity level**: Did you trade because there was a real edge, or because you felt you "should"? Over-trading is the most common mistake. The best loops are often research-only with no trades.
