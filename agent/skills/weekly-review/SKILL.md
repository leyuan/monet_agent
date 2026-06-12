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

### 3. Factor Weight Optimization (IC-driven, with override)

**This step runs AFTER Step 8 (audit_factor_ic) so the IC data is fresh.** If you're doing Step 3 before Step 8, skip Step 3 and come back after the audit.

**Algorithm: IC proposes, agent disposes.**

1. Call `suggest_factor_weight_adjustment()`. Returns proposed weights based on the latest IC audit:
   - Factors with strong positive IC at 20-60d → upweighted proportionally
   - Factors with negative IC → pushed toward the 0.10 floor
   - Max shift ±0.05 per audit (anti-thrashing)
   - Bounds [0.10, 0.45]
   - Sum renormalized to 1.0

2. Review the proposal. The tool returns per-factor `rationale` and `factor_signals`. Read them.

3. **When to override the proposal** (document reason in the journal):
   - **Regime context**: high-VIX environment (>25 sustained) — keep more weight in quality even if momentum IC is marginally higher (quality drawdowns are smaller)
   - **Sample size**: if the audit's sample_size per factor/horizon is < 8, treat the IC as noisy. Prefer small adjustments (half the proposed delta).
   - **Big swings**: if any proposed delta is ≥0.05 AND it's the same direction as last week, halve it. Persistent trends are real; one-off readings aren't.
   - **EPS revision**: not measured by audit_factor_ic (no historical data). Treat as neutral positive and preserve current weight unless you have live evidence it's working.

4. Apply the final weights (yours or the proposal's) via:
   ```python
   write_agent_memory("factor_weights", {
       "momentum": 0.35,   # new weights
       "quality": 0.30,
       "value": 0.20,
       "eps_revision": 0.15,
       "adjusted_at": "YYYY-MM-DD",
       "reason": "IC suggestion: momentum +0.02, value -0.03 (value IC -0.08 at 60d). Kept eps_revision flat per skill guidance.",
       "ic_snapshot": {  # optional — record what IC looked like when decision was made
           "momentum_20d": 0.025,
           "quality_20d": -0.01,
           "value_60d": -0.08,
       }
   })
   ```

5. **Do NOT skip writing if nothing changes.** Always write a new entry so the `adjusted_at` timestamp reflects "last reviewed" not "last changed". Use reason="IC stable, no adjustment" if holding.

**Hard limits (never override these):**
- Total must equal 1.00
- No factor < 0.10 or > 0.45
- Changes > ±0.05 per audit require a two-line written justification referencing specific IC evidence

This closes the feedback loop: IC → proposed weights → agent review → applied weights → next week's live P&L → next week's IC. The strategy adapts to market regime without you having to manually tune it.

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

**Catalyst Review:**
- Check `upcoming_catalysts` memory — remove past events, flag stale ones
- Were any catalysts this week correctly anticipated? Did the guard help?
- Update catalyst list if needed via `write_agent_memory("upcoming_catalysts", ...)`

### 7. AI Cycle Durability Assessment

Run `assess_ai_cycle_durability()` to score the current AI capex cycle. This tool:
- Measures 5 signals: stack breadth, infra momentum, memory demand, equipment demand, capex trajectory
- Compares each AI infrastructure layer's 3-month return vs SPY
- Reads the `ai_capex_tracker` memory for hyperscaler capex direction
- Persists results to `ai_cycle_durability` memory for the dashboard card

Review the result and note in the Step 9 journal: what changed since last week (layers
participating/lagging, momentum shifts), which stocks/layers drive the score, and whether
the cycle phase warrants portfolio action.

> **No separate weekly email.** The AI cycle headline now ships inside the single daily
> digest (`send_daily_subscription_emails`), so do NOT call `send_weekly_cycle_report`.

**Capex tracker (now automated)**: The `ai_capex_tracker` memory is refreshed every day by
`compute_ai_capex_trend()` in the AI cycle refresh, which pulls actual quarterly capex from
financials. You do NOT hand-write it. If a hyperscaler reported earnings this week and you
have a clear read on forward guidance, you may refresh it with your qualitative view:
```
compute_ai_capex_trend(
    forward_guidance_direction="raising" | "maintaining" | "cutting",
    forward_guidance_summary="<one-line read from the latest calls>",
)
```

### 8. Strategy Health Audit (Factor IC)

Run `audit_factor_ic()` — the early-warning system for strategy degradation. This computes fresh IC (rank correlation between factor scores and forward returns) over the past 3 months and compares to prior weekly audits.

**Runtime**: 3-5 minutes (downloads prices + top-300 fundamentals). This is the one long tool call per week; budget for it.

**Review the drift_flags list in the result**:
- `SIGN FLIP` on any factor → the factor has reversed direction (bull/bear regime flip or arbitraged away). Investigate before next week's factor weight decisions.
- `SIGNIFICANCE LOSS` → a previously meaningful factor has collapsed toward zero. It may no longer be pulling weight in the composite.
- `COMPOSITE NEGATIVE` at 60d → the total scoring system has no predictive edge right now. Do NOT adjust weights wildly — sometimes composite IC is temporarily negative in transitional regimes.
- `DRAG: <factor>` → a specific factor has IC < −0.02 at 60d. Candidate for weight reduction in Step 3.

**Use IC data to inform Step 3 factor weight adjustments**. Factors with stronger positive IC at 20-60d horizons should get higher weights. Factors with persistently negative IC should be reduced toward 0.10 (the floor).

**Important**: IC is statistical — a single reading isn't conclusive. Only act on drift when the same signal appears across 2+ consecutive audits, OR when the magnitude is extreme (|delta| > 0.05 in a single audit). One bad week isn't a trend.

Write findings into the Step 9 journal entry — don't create a separate entry.

### 9. Write Weekly Review Journal
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
