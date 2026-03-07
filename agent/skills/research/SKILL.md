# Research Phase

You are conducting the **research phase** of your autonomous trading loop.

## Stage-Aware Behavior

Before doing anything, read `agent_stage` from memory using `read_agent_memory("agent_stage")`. Your research depth depends on your current lifecycle stage:

| Stage | Screen Frequency | Deep Dives / Day | Watchlist Focus |
|-------|-----------------|-------------------|-----------------|
| **Explore** | Every run | 2+ companies | Aggressively expand to 15+ stocks |
| **Balanced** | Every 3 days | 1 company | Maintain and refine existing watchlist |
| **Exploit** | Only when replacing exited positions | 0-1 companies | Monitor held stocks and earnings only |

## Objective
Build deep, structured market intelligence using quantitative tools. No guessing from news headlines — use real data.

## Workflow

### 1. Market Health Check (every loop, every stage)
- Run `market_breadth()` to assess overall market regime (healthy bull, broad weakness, transitional, etc.)
- Run `sector_analysis("1mo")` to see which sectors are leading/lagging and the rotation signal (risk-on / risk-off)
- Get quotes for SPY, QQQ, and VIX to confirm directional bias
- **Event override**: If VIX > 30, flag this as a high-volatility event — temporarily boost research depth regardless of stage

### 2. Portfolio & Watchlist Event Check (every loop, every stage)
- Run `earnings_calendar()` with no arguments (auto-checks watchlist + positions)
- **Flag any earnings within 5 days** — these need immediate attention in the analysis phase
- Note upcoming catalysts that could affect existing positions

### 3. Deep Company Research (stage-dependent)
- **Explore stage**: Pick 2+ symbols from your watchlist that lack a recent `company_profile_{SYMBOL}` memory (or has one older than 7 days). Run `company_profile` and `peer_comparison` for each. Store results in memory.
- **Balanced stage**: Pick 1 symbol that needs a profile update. Run the same tools.
- **Exploit stage**: Only profile a company if you just exited a position and need a replacement, or if a held stock has a major catalyst. Otherwise, skip this step.
- **Rule: Never add to watchlist without running `company_profile` first**

### 4. Stock Discovery (stage-dependent)
- **Explore stage**: Run `screen_stocks` every loop. Use thesis-driven criteria matched to market conditions:
  - Healthy bull / risk-on → "momentum" or "growth"
  - Broad weakness / risk-off → "value" or "oversold"
  - Transitional → "quality" (resilient companies)
  - For any interesting results, run `company_profile` before adding to watchlist
  - Update `last_screen_date` in memory
- **Balanced stage**: Check `read_agent_memory("last_screen_date")` — only screen if it's been more than 3 days
- **Exploit stage**: Skip screening entirely unless you have fewer than 3 watchlist items or just exited a position

### 5. Targeted News (only for specific events)
- Use `internet_search` only for specific questions: "What happened with [company] earnings?", "Why did [sector] drop today?"
- **Never use `internet_search` for stock screening or discovery** — use `screen_stocks` instead

### 6. Record Findings
- Write a journal entry of type "research" summarizing:
  - Market regime and rotation signal
  - Key sector moves
  - Any earnings alerts
  - Company deep-dive findings (if done)
  - Screen results (if done)
  - Current stage and how it influenced research depth
- Update `market_outlook` memory with current assessment

## Anti-Patterns (DO NOT)
- Do NOT search for "trending stocks" or "best stocks to buy" — this produces random noise
- Do NOT run `screen_stocks` every loop in balanced/exploit stage
- Do NOT add to watchlist without `company_profile` first
- Do NOT rely on news articles for stock selection — use quantitative data
- Do NOT skip `market_breadth` and `sector_analysis` — these set the context for everything else
