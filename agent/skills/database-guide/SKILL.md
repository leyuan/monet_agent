# Database Guide

Reference for the Stock Agent's database schema and how to use it.

## Tables

### `agent_memory`
Key-value store for persistent beliefs.
- `key` (text, unique): e.g. 'market_outlook', 'strategy', 'risk_appetite', 'watchlist_rationale_AAPL'
- `value` (jsonb): Structured data
- Use `read_agent_memory(key)` and `write_agent_memory(key, value)` tools

### `agent_journal`
Timestamped activity log.
- `entry_type`: 'research', 'analysis', 'trade', 'reflection', 'market_scan'
- `title`: Brief descriptive title
- `content`: Full markdown content
- `symbols`: Array of related tickers
- Use `write_journal_entry()` and `get_my_journal()` tools

### `trades`
Full trade history.
- Records every order placed with thesis and confidence
- Automatically linked to journal entries
- Status tracked: pending, filled, cancelled, etc.

### `watchlist`
Active symbols being monitored.
- `symbol`: Unique ticker
- `thesis`: Why watching
- `target_entry`/`target_exit`: Price targets
- Use `manage_watchlist()` tool

### `risk_settings`
Single row with risk parameters.
- `max_position_pct`: Max % of equity in one position
- `max_daily_loss`: Max daily loss in dollars
- `max_total_exposure_pct`: Max % of equity exposed
- `default_stop_loss_pct`: Default stop loss percentage
