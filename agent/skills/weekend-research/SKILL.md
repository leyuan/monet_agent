# Weekend Research Phase (Saturday)

You are conducting the **Saturday batch research** session. Markets are closed — this is your time for deep, unhurried analysis.

## Stage-Aware Behavior

Read `agent_stage` from memory using `read_agent_memory("agent_stage")`. Weekend research depth scales with stage:

| Stage | Companies to Profile | Sector Analysis | Watchlist Review |
|-------|---------------------|-----------------|-----------------|
| **Explore** | 3-5 new companies | Full sector deep dives (3mo + 6mo) | Expand aggressively |
| **Balanced** | 2-3 companies | Focused on held sectors | Maintain and refine |
| **Exploit** | 1-2 (replacements only) | Monitor held sectors | Prune weak candidates |

## Objective
Use the weekend to do batch deep dives that weekday loops don't have time for. Build the knowledge base that drives better weekday decisions.

## Workflow

### 1. Sector Deep Analysis
- Run `sector_analysis("3mo")` AND `sector_analysis("6mo")` for trend identification
- Compare short vs long-term sector performance to spot rotation
- Identify sectors gaining momentum vs fading
- Write sector-level thesis to memory (e.g., `sector_thesis_technology`, `sector_thesis_energy`)

### 2. Batch Company Deep Dives
Based on your stage, select companies to profile:

**Finding candidates**:
- Check watchlist for items without `company_profile_{SYMBOL}` in memory
- Review recent screen results for interesting names not yet profiled
- In explore stage, also run a fresh `screen_stocks` with a different criteria than your last screen

**For each company**:
1. Run `company_profile(symbol)` for full fundamentals
2. Run `peer_comparison(symbol)` for competitive positioning
3. Run `technical_analysis(symbol)` for chart setup
4. Run `fundamental_analysis(symbol)` for valuation metrics
5. Store profile in memory as `company_profile_{SYMBOL}`
6. Add to watchlist with preliminary price targets if it passes your quality filter
7. Store rationale in memory as `watchlist_rationale_{SYMBOL}`

### 3. Watchlist Price Target Review
- Run `manage_watchlist(action="list")` to see all entries
- For each watchlist item:
  - Get current quote via `get_stock_quote(symbol)`
  - Compare current price to `target_entry` and `target_exit`
  - Note which stocks are approaching entry targets (within 5%)
  - Flag any that have moved significantly since last analysis
- Update targets that seem stale or mis-calibrated

### 4. Record Weekend Research
- Write a comprehensive journal entry of type "research" covering:
  - Sector rotation analysis and thesis
  - Each company deep-dive summary
  - Watchlist status: which stocks are near targets
  - Stage-specific notes on knowledge gaps to fill
- Update `market_outlook` with weekend assessment

## Anti-Patterns (DO NOT)
- Do NOT rush through profiles — weekend is for depth, not speed
- Do NOT skip `peer_comparison` — understanding relative positioning is critical
- Do NOT add to watchlist without `company_profile` first
- Do NOT ignore sector trends — they drive most stock movements
