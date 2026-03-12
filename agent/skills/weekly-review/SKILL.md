# Weekly Review Phase (Sunday)

You are conducting the **Sunday weekly review**. This is your most important session — assess factor system performance, evaluate weight adjustments, and review portfolio health.

## Step 0: Load Context (ALWAYS DO THIS FIRST)

1. Run `read_all_agent_memory()` to load all persistent beliefs
2. Read this week's journal entries:
   ```sql
   SELECT entry_type, title, content, symbols, created_at FROM agent_journal
   WHERE created_at >= CURRENT_DATE - INTERVAL '7 days' ORDER BY created_at DESC LIMIT 15
   ```
3. Read `factor_rankings` and `factor_weights` from memory for current state

## Workflow

### 1. Portfolio Performance Review
- Run `get_portfolio_state` to get current holdings
- Run `get_performance_comparison(days=7)` for week-over-week portfolio vs SPY
- Run `get_performance_comparison(days=30)` for monthly context and max drawdown
- Query recent trades:
  ```sql
  SELECT symbol, side, quantity, confidence, status, thesis, created_at
  FROM trades WHERE created_at >= NOW() - INTERVAL '7 days'
  ORDER BY created_at DESC
  ```
- Note alpha (portfolio return minus SPY return)

### 2. Factor System Evaluation
This is the most important part of the weekly review.

**Signal quality analysis:**
- For each trade this week, look up the composite score at time of entry
- Compare: did high-composite entries (80+) produce better P&L than lower ones (60-70)?
- Track win rate by composite score bucket
- Compare factor-driven decisions vs any earnings-reaction overrides

**Factor attribution:**
- Which factor contributed most to winners? (momentum? quality? EPS revision?)
- Which factor was associated with losers?
- Are any factors consistently misleading in the current regime?

**Ranking stability:**
- Compare this week's top 20 to last week's `factor_rankings` snapshot
- How many stocks entered/exited the top 20?
- High turnover might indicate momentum regime shift

### 3. Factor Weight Optimization
Based on the evaluation above, consider adjusting factor weights:

Current weights (from `factor_weights` memory):
- Momentum: 0.35
- Quality: 0.30
- Value: 0.20
- EPS Revision: 0.15

**Adjustment rules:**
- Only change weights by ±0.05 per week — no dramatic shifts
- Total must equal 1.00
- No single factor above 0.45 or below 0.10
- In high-VIX environments (>25 sustained), shift weight from momentum to quality
- If EPS revisions are consistently adding alpha, increase their weight

If adjusting, update `factor_weights` memory:
```
write_agent_memory("factor_weights", {
    "momentum": 0.35,
    "quality": 0.30,
    "value": 0.20,
    "eps_revision": 0.15,
    "adjusted_at": "YYYY-MM-DD",
    "reason": "..."
})
```

### 4. Sector Concentration Check
- From current positions + buy signals, check sector distribution
- Flag if >40% of positions are in one sector
- This isn't a hard block — just a risk awareness check
- Note in journal if concentration is high

### 5. User Insights Review
```sql
SELECT title, content, symbols, created_at FROM agent_journal
WHERE entry_type = 'user_insight' AND created_at >= NOW() - INTERVAL '7 days'
ORDER BY created_at DESC
```
- How many insights were submitted?
- Did any lead to useful earnings interpretation or risk awareness?
- Note this in journal for accountability

### 6. Strategy Assessment
- Is the factor system producing alpha vs SPY?
- Are we churning positions (selling too quickly)?
- Are we missing opportunities (holding cash when signals exist)?
- Review risk settings: are they appropriate for current regime?
- Update `strategy` memory with any observations

### 7. Write Weekly Review Journal
Create a comprehensive journal entry of type "reflection" covering:
- Weekly alpha vs SPY
- Factor system evaluation: which factors worked, which didn't
- Factor weight changes (if any) and reasoning
- Sector concentration status
- Trade count and win rate
- Key learnings for next week
- Honest self-assessment: is the systematic approach working?
- Set `run_source='weekly_review'`

## Review Principles
- Be data-driven — look at actual P&L by factor score bucket
- Small weight adjustments > big overhauls
- The goal is systematic alpha, not occasional home runs
- If the factor system isn't working after 4+ weeks, the issue might be deeper than weights
- Track whether factor-driven trades outperform earnings-reaction overrides
