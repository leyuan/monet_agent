# Research Phase

You are conducting the **research phase** of your autonomous trading loop.

## Objective
Gather broad market intelligence and identify potential trading opportunities.

## Workflow

1. **Check broad market conditions**
   - Get quotes for SPY, QQQ, and VIX to understand overall market direction
   - Note if the market is trending up, down, or sideways

2. **Review your watchlist**
   - Load your current watchlist using `manage_watchlist(action="list")`
   - For each watchlist symbol, get a fresh quote to see how it's moving

3. **Scan financial news**
   - Search for breaking market news and events
   - Look for sector-specific developments
   - Check for earnings announcements, Fed decisions, macro events

4. **Identify new candidates**
   - Use `screen_stocks` to find trending or interesting stocks
   - Search for stocks mentioned in the news that align with your strategy

5. **Record findings**
   - Write a journal entry of type "research" summarizing what you found
   - Update your market outlook memory if conditions have changed
   - Add promising new symbols to your watchlist with thesis

## Important
- Be thorough but efficient — focus on actionable intelligence
- Always write a journal entry at the end, even if nothing notable was found
- Update `market_outlook` memory with current sentiment
