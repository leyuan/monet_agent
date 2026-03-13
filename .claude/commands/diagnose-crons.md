# Diagnose Cron Jobs

Run a comprehensive diagnostic of the Monet Agent's autonomous cron job health. Check for errors, execution gaps, verify recent fixes, and propose improvements.

## Step 1: Check Cron Configuration

Query the LangGraph Platform for all registered crons:

```bash
cd agent && python -c "
import asyncio, os
from dotenv import load_dotenv
from langgraph_sdk import get_client

load_dotenv()

async def main():
    client = get_client(
        url='https://monet-0f211e9ce05255c2a85f92d6847873b5.us.langgraph.app',
        api_key=os.environ['LANGSMITH_API_KEY'],
    )
    crons = await client.crons.search()
    print(f'Total crons: {len(crons)} (expected: 5)')
    for c in crons:
        print(f'  Schedule: {c[\"schedule\"]}  |  Next: {c.get(\"next_run_date\", \"unknown\")}  |  ID: {c[\"cron_id\"]}')

asyncio.run(main())
"
```

Verify:
- There should be exactly **5 crons**: `0 14 * * 1-5`, `0 17 * * 1-5`, `0 20 * * 1-5`, `0 15 * * 6`, `0 15 * * 0`
- All `next_run_date` values should be in the future
- Flag any missing schedules

## Step 2: Check Today's Execution

Query today's journal entries and trades:

```sql
-- Today's journal entries
SELECT entry_type, title, metadata->>'run_source' as run_source,
  created_at AT TIME ZONE 'America/New_York' as et_time,
  LENGTH(content) as content_len, symbols
FROM agent_journal
WHERE created_at >= CURRENT_DATE
ORDER BY created_at;

-- Today's trades
SELECT symbol, side, quantity, status, confidence, created_at
FROM trades WHERE created_at >= CURRENT_DATE ORDER BY created_at;

-- Today's memory updates
SELECT key, updated_at AT TIME ZONE 'America/New_York' as et_time
FROM agent_memory WHERE updated_at >= CURRENT_DATE ORDER BY updated_at DESC;
```

Expected weekday pattern:
- **10am ET**: factor_loop → market_scan journal, factor_rankings memory updated
- **1pm ET**: factor_loop → market_scan journal (uses 4hr cache)
- **4pm ET**: eod_reflection → reflection journal, equity_snapshot recorded

Expected weekend:
- **Saturday 11am**: factor_loop_weekend → market_scan with top 50, catalyst discovery, upcoming_catalysts memory
- **Sunday 11am**: weekly_review → reflection with factor weight assessment

## Step 3: Check Run Quality

For the latest factor loop run, verify:

```sql
-- Latest factor loop journal
SELECT content FROM agent_journal
WHERE metadata->>'run_source' = 'factor_loop'
ORDER BY created_at DESC LIMIT 1;
```

Check:
- [ ] Factor rankings table present with top 10 (Rank, Symbol, Sector, Composite, M, Q, V, E)
- [ ] BUY/SELL/HOLD signals generated
- [ ] Earnings guard applied (stocks with earnings within 5 days blocked)
- [ ] Catalyst guard applied if `upcoming_catalysts` memory exists
- [ ] **No sector filtering** — signals NOT blocked by "AI infrastructure mandate" or sector preference
- [ ] Journal is concise (< 3000 chars, no essays)
- [ ] `run_source` is "factor_loop" in metadata

## Step 4: Check Recent Execution History (14 days)

```sql
SELECT
  DATE(created_at AT TIME ZONE 'America/New_York') as run_date,
  EXTRACT(DOW FROM created_at AT TIME ZONE 'America/New_York') as dow,
  COUNT(*) as entries,
  ARRAY_AGG(DISTINCT metadata->>'run_source') as sources,
  MIN(created_at AT TIME ZONE 'America/New_York') as first_entry,
  MAX(created_at AT TIME ZONE 'America/New_York') as last_entry
FROM agent_journal
WHERE created_at >= NOW() - INTERVAL '14 days'
GROUP BY DATE(created_at AT TIME ZONE 'America/New_York'),
         EXTRACT(DOW FROM created_at AT TIME ZONE 'America/New_York')
ORDER BY run_date DESC;
```

For each day, verify against expected schedule:
- **Weekdays (DOW 1-5)**: Should have 3 runs (factor_loop × 2 + eod_reflection)
- **Saturday (DOW 6)**: 1 run (factor_loop_weekend)
- **Sunday (DOW 0)**: 1 run (weekly_review)

Flag gaps — days where expected runs are missing.

## Step 5: Check for Errors

```sql
SELECT entry_type, title, LEFT(content, 300) as preview,
  created_at AT TIME ZONE 'America/New_York' as et_time
FROM agent_journal
WHERE created_at >= NOW() - INTERVAL '7 days'
  AND (content ILIKE '%error%' OR content ILIKE '%failed%'
    OR content ILIKE '%exception%' OR content ILIKE '%unable to%'
    OR content ILIKE '%blocked%' OR content ILIKE '%outside mandate%')
ORDER BY created_at DESC;
```

Flag:
- Tool errors (search, quote, scoring failures)
- Sector bias language ("outside mandate", "outside AI infrastructure") — this was fixed Mar 13, should not appear after
- SPY data errors ($0 close) — fixed Mar 13
- Earnings calendar failures

## Step 6: Check Memory Freshness

```sql
SELECT key,
  updated_at AT TIME ZONE 'America/New_York' as last_updated,
  ROUND(EXTRACT(EPOCH FROM (NOW() - updated_at)) / 3600) as hours_ago
FROM agent_memory
WHERE key IN ('market_regime', 'strategy', 'risk_appetite', 'factor_rankings',
  'factor_weights', 'upcoming_earnings', 'upcoming_catalysts')
ORDER BY updated_at DESC;
```

Flag:
- `market_regime` not updated in 24h on a weekday → factor loop isn't writing regime
- `factor_rankings` not updated in 24h on a weekday → scoring pipeline broken
- `upcoming_catalysts` missing or > 8 days old → weekend catalyst discovery not running
- `factor_weights` > 14 days old → weekly review not adjusting weights
- `strategy` should show `approach: "factor_based_systematic"` (not legacy AI infrastructure)

Quick check on strategy:
```sql
SELECT value->>'approach' as approach, value->>'universe' as universe
FROM agent_memory WHERE key = 'strategy';
```

## Step 7: Check Equity Snapshots

```sql
SELECT snapshot_date, portfolio_equity, spy_close,
  portfolio_cumulative_return, spy_cumulative_return, alpha, deployed_pct
FROM equity_snapshots ORDER BY snapshot_date DESC LIMIT 7;
```

Flag:
- `spy_close = 0` → yfinance fallback failed (bug)
- `spy_cumulative_return = -100` → bad SPY data poisoned cumulative calc
- Missing dates on weekdays → EOD reflection didn't call `record_daily_snapshot()`
- `portfolio_equity = 0` → Alpaca API failure

## Step 8: Verification Checklist

Read `POSTDEPLOY_CHECK.md` at the project root.

For each item in **Pending Verification**:
1. Check if the trigger condition has been met
2. If yes, verify each checkbox by querying the database
3. Mark items as `[x]` if verified, or flag failures
4. Move fully verified sections to **Verified** with today's date
5. If a check fails, note what went wrong and propose a fix

Key verification queries:
```sql
-- Check sector bias fix
SELECT title, content FROM agent_journal
WHERE metadata->>'run_source' = 'factor_loop'
  AND created_at > '2026-03-13 21:00:00+00'
  AND (content ILIKE '%outside mandate%' OR content ILIKE '%outside AI%')
ORDER BY created_at DESC LIMIT 5;

-- Check catalyst memory
SELECT key, updated_at, value->>'fetched_at' as fetched
FROM agent_memory WHERE key = 'upcoming_catalysts';

-- Check SPY snapshots after fix
SELECT snapshot_date, spy_close, spy_cumulative_return
FROM equity_snapshots WHERE snapshot_date > '2026-03-13'
ORDER BY snapshot_date;

-- Check earnings reaction memories
SELECT key, value FROM agent_memory WHERE key LIKE 'earnings_reaction:%';

-- Check factor scores on stock analyses
SELECT key, value->>'composite_score' as composite,
  value->>'momentum_score' as momentum, value->>'quality_score' as quality,
  value->>'value_score' as value_score, value->>'eps_revision_score' as eps_rev
FROM agent_memory WHERE key LIKE 'stock:%'
ORDER BY (value->>'composite_score')::float DESC NULLS LAST;
```

Update the checklist file with findings.

## Step 9: Generate Report

Summarize findings:

### Health Score: X/10

### Cron Status
- [ ] All 5 crons registered
- [ ] Next run dates are correct
- [ ] No stale/orphaned crons

### Today's Runs
- List each run with time, type, and key actions taken
- Note any trades placed and their status
- Flag any blocked signals and whether the block was valid

### Execution Gaps (last 14 days)
- List any dates where expected runs didn't happen
- Identify if gaps are systematic vs random

### Errors & Bias
- Tool/data errors found
- Any remaining sector bias language (should be zero after Mar 13 fix)
- SPY data quality

### Memory Health
- Which memories are fresh vs stale?
- Any critical memories missing?

### Verification Checklist Summary
- Items verified today
- Items that failed
- Items still pending (trigger not yet met)

### Proposals
Based on findings, propose:
1. **Fixes needed** — any bugs or data issues to address
2. **Skill improvements** — factor loop, reflection, or weekly review changes
3. **Schedule adjustments** — timing or frequency changes
4. **Monitoring gaps** — things that should be tracked but aren't
