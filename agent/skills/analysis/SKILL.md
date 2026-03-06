# Analysis Phase

You are conducting the **analysis phase** of your autonomous trading loop.

## Objective
Perform deep technical and fundamental analysis on candidate stocks from your research.

## Workflow

1. **Select candidates**
   - Review your most recent research journal entry
   - Identify 2-5 stocks worth deep analysis
   - Prioritize watchlist items near entry targets

2. **Technical analysis** (for each candidate)
   - Run `technical_analysis` to get RSI, MACD, Bollinger Bands, SMAs, volume
   - Look for convergence of bullish/bearish signals
   - Identify support and resistance levels
   - Check if price is at a key technical level

3. **Fundamental analysis** (for each candidate)
   - Run `fundamental_analysis` to get P/E, revenue, earnings, debt
   - Compare valuations to sector averages
   - Check analyst targets and recommendations
   - Assess growth trajectory

4. **Synthesize thesis**
   - For each candidate, form a clear bull case and bear case
   - Assign a confidence score (0.0-1.0)
   - Determine entry price, target exit, and stop loss

5. **Record analysis**
   - Write a journal entry of type "analysis" for each candidate analyzed
   - Update watchlist entries with new target prices
   - Store rationale in memory (e.g. `watchlist_rationale_AAPL`)

## Confidence Scoring Guide
- **0.8-1.0**: Strong conviction — multiple technical and fundamental signals align
- **0.6-0.8**: Moderate conviction — good setup but some uncertainty
- **0.4-0.6**: Low conviction — mixed signals, worth watching
- **Below 0.4**: Skip — not enough edge
