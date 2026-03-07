# Monet Agent — Autonomous AI Investor

## Project Overview
An autonomous AI stock trading agent that makes its own trading decisions on a cron schedule (research -> analyze -> trade -> reflect). Uses Alpaca paper trading, has persistent memory in Supabase, and a Next.js web UI for monitoring/chat.

**Goal**: Beat the S&P 500 consistently with disciplined risk management. Not chasing home runs — systematic alpha through momentum + mean reversion on US large/mid-caps.

## Architecture

```
stock_agent/
├── agent/                          # Python backend (LangGraph + Deep Agents)
│   ├── langgraph.json              # Graph registry — 2 graphs in 1 deployment
│   ├── src/stock_agent/
│   │   ├── agent.py                # Chat graph (read-only, exposed to users)
│   │   ├── autonomy.py             # Autonomous graph (full trading tools)
│   │   ├── tools.py                # AUTONOMOUS_TOOLS + CHAT_TOOLS definitions
│   │   ├── db.py                   # Supabase CRUD (memory, journal, trades, watchlist, risk)
│   │   ├── supabase_client.py      # Supabase singleton client
│   │   ├── memory.py               # load_agent_context() for chat system prompt
│   │   ├── auth.py                 # Supabase JWT validation via langgraph_sdk.Auth
│   │   ├── middleware.py           # handle_tool_errors + ToolRetryMiddleware
│   │   ├── alpaca_client.py        # Alpaca paper trading client
│   │   ├── market_data.py          # Historical bars, quotes, portfolio from Alpaca
│   │   ├── technical.py            # RSI, MACD, Bollinger, SMA, ATR indicators
│   │   └── risk.py                 # Pre-trade risk checks
│   ├── skills/                     # Deep Agent skill definitions
│   │   ├── research/SKILL.md       # Stage-aware market research
│   │   ├── analysis/SKILL.md       # Analysis + price target setting
│   │   ├── trade-execution/SKILL.md # Price-target-driven execution
│   │   ├── reflection/SKILL.md     # Daily reflection + stage counter updates
│   │   ├── weekend-research/SKILL.md # Saturday batch deep dives
│   │   ├── weekly-review/SKILL.md  # Sunday full review + stage management
│   │   └── database-guide/SKILL.md
│   └── scripts/
│       ├── seed_strategy.py        # One-time seed for founding strategy
│       ├── seed_stage.py           # Seed agent_stage to "explore"
│       └── create_crons.py         # Create/update LangGraph cron jobs
├── web/                            # Next.js frontend
│   └── app/
│       ├── (app)/dashboard/        # Portfolio, trades, watchlist
│       ├── (app)/chat/             # Chat with agent (LangGraph streaming)
│       ├── (app)/journal/          # Agent's reflections feed
│       ├── (app)/activity/         # Merged feed of trades + journal
│       └── (auth)/login|signup/    # Supabase auth pages
└── supabase/                       # Database migrations
```

## Two Graphs, One Deployment

Both graphs are registered in `langgraph.json` and run in a single LangGraph Platform deployment:

| Graph | File | Purpose | Tools |
|-------|------|---------|-------|
| `monet_agent` | `agent.py:graph` | Chat mode — users ask questions | Read-only: search, quotes, portfolio, outlook, journal, trades |
| `autonomous_loop` | `autonomy.py:autonomous_graph` | Trading loop — runs on cron | Full: above + place_order, write_memory, write_journal, watchlist, risk check, technicals, fundamentals, screening |

## Scheduling (17 runs/week)

The autonomous loop runs via **LangGraph Platform crons** with an explore/exploit lifecycle:

### Weekdays (Mon-Fri) — 3 runs/day
| Cron (UTC) | Toronto | Phases | Focus |
|------------|---------|--------|-------|
| `0 14 * * 1-5` | 10am | Research | Market health, earnings, news scan |
| `0 17 * * 1-5` | 1pm | Research + Analysis | Deep company dive, set price targets |
| `0 20 * * 1-5` | 4pm | Execution + Reflection | Check targets, trade if hit, daily reflection |

### Weekends — 1 run/day
| Cron (UTC) | Toronto | Phases | Focus |
|------------|---------|--------|-------|
| `0 15 * * 6` | Sat 11am | Weekend Research + Analysis | Batch deep dives (3-5 companies), sector analysis |
| `0 15 * * 0` | Sun 11am | Weekly Review | Performance, strategy, stage management, weekly priorities |

### Explore/Exploit Lifecycle
Agent tracks maturity via `agent_stage` memory (`explore` → `balanced` → `exploit`):
- **Explore**: Screen aggressively, 2+ deep dives/day, build watchlist to 15+, rarely trade (0.8+ confidence)
- **Balanced**: Maintain research cadence, check price targets actively, trade at 0.6+ confidence
- **Exploit**: Focus on position management, research only for new catalysts or replacements

Managed via `agent/scripts/create_crons.py`. **Note**: UTC-based, needs manual adjustment for DST changes (EDT/EST)

## Deployment

- **LangGraph Platform**: `https://monet-0f211e9ce05255c2a85f92d6847873b5.us.langgraph.app`
- **Tracing**: LangSmith project `monet`
- **Web frontend**: Vercel (Next.js)

## Supabase Tables

| Table | Purpose |
|-------|---------|
| `agent_memory` | Key-value persistent beliefs (strategy, market_outlook, risk_appetite, etc.) |
| `agent_journal` | Timestamped entries (research, analysis, trade, reflection, market_scan) |
| `trades` | Trade log with thesis, confidence, broker_order_id, status |
| `watchlist` | Symbols with thesis, target_entry, target_exit |
| `risk_settings` | Single row: max_position_pct, max_daily_loss, max_total_exposure_pct, default_stop_loss_pct |
| `profiles` | Web UI viewer profiles |

## Key Patterns

- Agent uses `deepagents` + `create_deep_agent` for graph definition
- `FilesystemBackend(virtual_mode=True)` for skill file access
- Auth: Supabase JWT validated via `langgraph_sdk.Auth`, dev mode allows unauthenticated
- Middleware: `handle_tool_errors` (catch-all safety net) + `ToolRetryMiddleware` (retries for search/quote/historical)
- Frontend: `@assistant-ui/react` + `@langchain/langgraph-sdk` for streaming chat
- Memory: `load_agent_context()` reads strategy/outlook/risk_appetite and formats into chat system prompt
- Risk: `check_risk()` is called inside `place_order` — trades that fail risk checks are rejected

## Commands

```bash
# Agent (local dev)
cd agent && langgraph dev          # Run agent locally
cd agent && pip install -e ".[dev]" # Install with dev deps

# Web
cd web && npm install && npm run dev # Run frontend

# Supabase
supabase start                      # Local Supabase
supabase db reset                   # Apply migrations

# Seed founding strategy
cd agent && python scripts/seed_strategy.py

# Seed explore/exploit stage
cd agent && python scripts/seed_stage.py

# Update cron jobs
cd agent && python scripts/create_crons.py
```

## Important Rules

- Chat mode tools are READ-ONLY — never expose `place_order` in chat
- Autonomous mode writes to `agent_journal` and `agent_memory` after every loop
- All trades must pass risk checks before execution (5% stop loss, 80% max exposure, $500 daily loss limit)
- The agent has ONE persistent identity, not per-user sessions
- Max 5-8 positions, 10% max per position, 20% cash buffer
- After each cycle: compare outcomes to thesis, calibrate confidence, update beliefs

## Environment Variables

Required in `agent/.env`:
- `ANTHROPIC_API_KEY` — LLM
- `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` — Database
- `ALPACA_API_KEY`, `ALPACA_SECRET_KEY`, `ALPACA_BASE_URL` — Paper trading
- `TAVILY_API_KEY` — Web search
- `LANGSMITH_API_KEY`, `LANGSMITH_TRACING`, `LANGSMITH_PROJECT` — Observability
- `MODEL_NAME` — Model ID (default: `anthropic:claude-sonnet-4-5-20250929`)
