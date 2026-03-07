# Database Guide

Reference for the Stock Agent's database schema. Use the `query_database` tool to run SELECT queries.

## Tables

### `agent_memory`
Key-value store for persistent beliefs.
| Column | Type | Description |
|--------|------|-------------|
| `id` | uuid | Primary key |
| `key` | text (unique) | e.g. 'market_outlook', 'strategy', 'risk_appetite', 'watchlist_rationale_AAPL' |
| `value` | jsonb | Structured data (usually has a `summary` field) |
| `updated_at` | timestamptz | Last update time |

### `agent_journal`
Timestamped activity log.
| Column | Type | Description |
|--------|------|-------------|
| `id` | uuid | Primary key |
| `entry_type` | text | 'research', 'analysis', 'trade', 'reflection', 'market_scan' |
| `title` | text | Brief descriptive title |
| `content` | text | Full markdown content |
| `symbols` | text[] | Array of related tickers |
| `metadata` | jsonb | Extra data |
| `created_at` | timestamptz | Creation time |

### `trades`
Full trade history.
| Column | Type | Description |
|--------|------|-------------|
| `id` | uuid | Primary key |
| `symbol` | text | Ticker |
| `side` | text | 'buy' or 'sell' |
| `quantity` | numeric | Number of shares |
| `order_type` | text | 'market' or 'limit' |
| `limit_price` | numeric | Limit price (nullable) |
| `thesis` | text | Reasoning behind the trade |
| `confidence` | numeric | 0.0-1.0 confidence score |
| `broker_order_id` | text | Alpaca order ID |
| `status` | text | Order status |
| `journal_id` | uuid | Linked journal entry |
| `created_at` | timestamptz | Trade time |

### `watchlist`
Active symbols being monitored.
| Column | Type | Description |
|--------|------|-------------|
| `symbol` | text (unique) | Ticker |
| `thesis` | text | Why watching |
| `target_entry` | numeric | Entry price target |
| `target_exit` | numeric | Exit price target |
| `added_at` | timestamptz | When added |

### `risk_settings`
Single row with risk parameters.
| Column | Type | Description |
|--------|------|-------------|
| `id` | uuid | Primary key |
| `max_position_pct` | numeric | Max % of equity in one position |
| `max_daily_loss` | numeric | Max daily loss in dollars |
| `max_total_exposure_pct` | numeric | Max % of equity exposed |
| `default_stop_loss_pct` | numeric | Default stop loss percentage |

## Example Queries
```sql
-- Get watchlist
SELECT symbol, thesis, target_entry, target_exit FROM watchlist

-- Recent trades
SELECT symbol, side, quantity, confidence, status, created_at FROM trades ORDER BY created_at DESC LIMIT 10

-- Agent beliefs
SELECT key, value->>'summary' as summary FROM agent_memory

-- Journal entries by type
SELECT title, content, created_at FROM agent_journal WHERE entry_type = 'reflection' ORDER BY created_at DESC LIMIT 5
```
