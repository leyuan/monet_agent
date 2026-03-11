# Analysis Phase

You are conducting the **analysis phase** of your autonomous trading loop.

## Step 0: Load Context (ALWAYS DO THIS FIRST)

Before anything else, load your full memory and recent history:
1. Run `read_all_agent_memory()` to load all persistent beliefs at once
2. Read your last 3 journal entries: `query_database("SELECT entry_type, title, content, symbols, created_at FROM agent_journal ORDER BY created_at DESC LIMIT 3")`
3. This tells you what research was just done and which candidates to analyze

## Stage-Aware Behavior

Your analysis approach varies by stage (from `agent_stage` in memory):

| Stage | Candidates | Price Target Style | Focus |
|-------|-----------|-------------------|-------|
| **Explore** | 2-5 from research | Wide targets (learning the stock's range) | Building conviction, understanding patterns |
| **Balanced** | 2-3 from watchlist | Moderate targets | Refining entries, comparing to peers |
| **Exploit** | 1-2 near targets | Tight targets (confident in valuation) | Precision entries, position management |

## Objective
Perform deep technical and fundamental analysis on candidate stocks from your research, and set actionable price targets on the watchlist. **Fundamentals drive the thesis; technicals refine the entry.**

## Workflow

### 1. Select candidates
- Review your most recent research journal entry
- Identify candidates worth deep analysis (count depends on stage — see table above)
- Prioritize watchlist items near entry targets
- **Prioritize post-earnings reactions**: If any `earnings_reaction_{SYMBOL}` memories exist from research, analyze those stocks first
- **Check for imminent earnings** — if a stock reports within 5 days, flag it and factor in the uncertainty

### 2. Fundamental analysis FIRST (for each candidate)
- Run `fundamental_analysis` to get P/E, revenue, earnings, debt
- Compare valuations to sector averages
- Check analyst targets and recommendations
- Assess growth trajectory — is revenue accelerating or decelerating?
- **Key fundamental questions**:
  - Is revenue growth sustainable or was it a one-time event?
  - Are margins expanding or compressing? Why?
  - Is the company generating free cash flow?
  - Is the balance sheet strong enough to weather a downturn?
  - How does forward P/E compare to growth rate (PEG ratio)?

### 3. Competitive analysis (for each candidate)
- Check if `company_profile_{SYMBOL}` exists in memory — if not, run `company_profile` first
- Run `peer_comparison(symbol)` to see how the stock ranks vs competitors
- Key questions:
  - Is the valuation premium/discount justified by business quality?
  - Is margin better or worse than peers? Why?
  - Is the stock gaining or losing market share (revenue growth vs peers)?
  - Where does it rank on ROE and debt levels?
- A stock trading at a premium to peers needs superior growth or margins to justify it
- A stock at a discount to peers is only a value opportunity if the business is stable

### 4. Technical analysis (for each candidate)
- Run `technical_analysis` to get RSI, MACD, Bollinger Bands, SMAs, volume
- Look for convergence of bullish/bearish signals
- Identify support and resistance levels
- Check if price is at a key technical level
- **Technicals are for timing, not thesis** — a stock with great fundamentals at a bad technical entry is a "wait", not a "skip"

### 5. Set Price Targets (CRITICAL — do this for every analyzed stock)
After completing analysis, compute and set `target_entry` and `target_exit` on the watchlist:

- **Target entry**: Use the lower of:
  - Key technical support level (e.g., 50-day SMA, recent support)
  - Fair value estimate from fundamentals (e.g., 10-15% below analyst target)
- **Target exit**: Use the lower of:
  - Technical resistance level
  - Analyst consensus target price
  - Your own fair value estimate + 15-20% upside

**Stage adjustments for targets**:
- **Explore**: Set wider targets (5-10% below support for entry, 20-30% upside for exit). You're still learning the stock's behavior.
- **Balanced**: Set moderate targets (3-5% below support, 15-20% upside).
- **Exploit**: Set tight targets (1-3% below support, 10-15% upside). You know the stock well.

**When to revise targets (don't wait forever):**
If a stock has rallied >10% past your `target_entry` AND:
- Fundamentals are still strong or improving (confirmed in steps 2-3)
- The rally is supported by volume and breadth (not just a low-volume squeeze)
- Market regime has improved (e.g., VIX dropped significantly since target was set)

Then **revise `target_entry` upward** to the nearest technical support level (e.g., current 20-day SMA or recent pullback low). Don't anchor to stale targets set during a different market regime.

**Rule: Targets older than 5 trading days in a regime change should always be revisited.** A target set during VIX 30 is meaningless when VIX is 22. Recalculate from current technicals.

Do NOT chase — revised target should still be below current price (buying a pullback to new support, not buying the rip).

Update the watchlist entry with computed targets:
```
manage_watchlist(action="add", symbol="AAPL", thesis="...", target_entry=185.0, target_exit=225.0)
```

### 5.5. Place Limit Orders for Near-Target Stocks

After setting price targets, check if any analyzed stock is **within 3% of its target_entry**. If so, consider placing a DAY limit order now rather than waiting for the trade-execution phase.

**When to place a limit order from analysis:**
- Stock price is within 3% above the `target_entry` (close but hasn't quite hit)
- Your confidence score is at or above your stage threshold (0.8 for explore, 0.6 for balanced/exploit)
- Fundamentals and thesis are solid (you just confirmed this in steps 2-4)
- The market regime is not extreme risk-off (VIX < 30)
- You don't already have an open order for this symbol — check `get_open_orders()` first

**How to place:**
1. Run `check_trade_risk(symbol, "buy", quantity)` — if it fails, skip
2. Use `place_order(symbol, "buy", quantity, order_type="limit", limit_price=target_entry, thesis="...", confidence=...)`
3. The order lives for the trading day (TimeInForce.DAY) — Alpaca fills it if price touches your target
4. Write a journal entry noting the limit order placement and reasoning

**Do NOT place limit orders if:**
- Stock is more than 3% above target (wait for it to come to you)
- Stock is already below target (use the trade-execution phase for market orders)
- You have low confidence or uncertain fundamentals
- Earnings are within 5 days (too much binary risk for a passive limit order)

### 6. Synthesize thesis
- For each candidate, form a clear bull case and bear case
- **Ground the thesis in fundamentals**: revenue trajectory, margin outlook, competitive position
- Assign a confidence score (0.0-1.0)
- Determine entry price, target exit, and risk tolerance
- Factor in earnings timing — stocks reporting within 5 days require confidence >= 0.85

### 7. Record analysis
- Write a journal entry of type "analysis" for each candidate analyzed
- Update watchlist entries with new target prices (done in step 5)
- Store rationale in memory (e.g. `watchlist_rationale_AAPL`)

## Confidence Scoring Guide
- **0.8-1.0**: Strong conviction — fundamentals excellent, peer comparison favorable, technicals supportive
- **0.6-0.8**: Moderate conviction — good fundamentals but some uncertainty, decent vs peers
- **0.4-0.6**: Low conviction — mixed fundamentals or unclear competitive position, worth watching
- **Below 0.4**: Skip — not enough fundamental edge
