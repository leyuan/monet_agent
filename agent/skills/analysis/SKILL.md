# Analysis Phase

You are conducting the **analysis phase** of your autonomous trading loop.

## Stage-Aware Behavior

Read `agent_stage` from memory using `read_agent_memory("agent_stage")`. Your analysis approach varies by stage:

| Stage | Candidates | Price Target Style | Focus |
|-------|-----------|-------------------|-------|
| **Explore** | 2-5 from research | Wide targets (learning the stock's range) | Building conviction, understanding patterns |
| **Balanced** | 2-3 from watchlist | Moderate targets | Refining entries, comparing to peers |
| **Exploit** | 1-2 near targets | Tight targets (confident in valuation) | Precision entries, position management |

## Objective
Perform deep technical and fundamental analysis on candidate stocks from your research, and set actionable price targets on the watchlist.

## Workflow

### 1. Select candidates
- Review your most recent research journal entry
- Identify candidates worth deep analysis (count depends on stage — see table above)
- Prioritize watchlist items near entry targets
- **Check for imminent earnings** — if a stock reports within 5 days, flag it and consider risk

### 2. Technical analysis (for each candidate)
- Run `technical_analysis` to get RSI, MACD, Bollinger Bands, SMAs, volume
- Look for convergence of bullish/bearish signals
- Identify support and resistance levels
- Check if price is at a key technical level

### 3. Fundamental analysis (for each candidate)
- Run `fundamental_analysis` to get P/E, revenue, earnings, debt
- Compare valuations to sector averages
- Check analyst targets and recommendations
- Assess growth trajectory

### 4. Competitive analysis (for each candidate)
- Check if `company_profile_{SYMBOL}` exists in memory — if not, run `company_profile` first
- Run `peer_comparison(symbol)` to see how the stock ranks vs competitors
- Key questions:
  - Is the valuation premium/discount justified by business quality?
  - Is margin better or worse than peers? Why?
  - Is the stock gaining or losing market share (revenue growth vs peers)?
  - Where does it rank on ROE and debt levels?
- A stock trading at a premium to peers needs superior growth or margins to justify it
- A stock at a discount to peers is only a value opportunity if the business is stable

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

Update the watchlist entry with computed targets:
```
manage_watchlist(action="add", symbol="AAPL", thesis="...", target_entry=185.0, target_exit=225.0)
```

### 6. Synthesize thesis
- For each candidate, form a clear bull case and bear case
- Assign a confidence score (0.0-1.0)
- Determine entry price, target exit, and stop loss
- Factor in earnings timing — avoid entering right before earnings unless thesis is event-driven

### 7. Record analysis
- Write a journal entry of type "analysis" for each candidate analyzed
- Update watchlist entries with new target prices (done in step 5)
- Store rationale in memory (e.g. `watchlist_rationale_AAPL`)

## Confidence Scoring Guide
- **0.8-1.0**: Strong conviction — multiple technical and fundamental signals align, peer comparison favorable
- **0.6-0.8**: Moderate conviction — good setup but some uncertainty, average vs peers
- **0.4-0.6**: Low conviction — mixed signals, worth watching
- **Below 0.4**: Skip — not enough edge
