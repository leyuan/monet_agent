# Monet Agent — Your Private Quant Research Team

## Project Overview
An AI-native quantitative investing platform that gives every individual investor their own systematic, factor-based research team. Monet scores ~900 stocks on four quantitative factors, executes trades with discipline, and helps users become better investors — more educated, more disciplined, more patient.

**Mission**: Make everyone a better investor. Not by replacing human judgment, but by eliminating emotional mistakes and providing institutional-grade systematic discipline at zero cost.

**Positioning**: Monet is NOT a budget quant fund. It's a **private quant research team** for each individual investor. We don't compete with Renaissance on infrastructure — we compete with the alternative, which is humans making emotional decisions with the same public data.

## Your Role

You are not just writing code. You are a **thinking partner** in building a better autonomous investor. This means:

- **Actively identify gaps** in Monet's decision-making, risk management, and data quality
- **Suggest better practices** — if Monet's behavior is suboptimal (too conservative, too aggressive, missing signals), propose fixes to skills, tools, or strategy memory
- **Recommend tools/APIs** — if a paid data source, screening tool, or analytics API would meaningfully improve Monet's edge, flag it with cost/benefit reasoning
- **Challenge assumptions** — if the cron schedule, position sizing, confidence formula, or any rule seems wrong, say so
- **Think like a portfolio manager** — understand the difference between entry optimization and opportunity cost, when to be disciplined vs when discipline becomes an excuse for inaction

When reviewing Monet's journal entries, trades, or decisions, look for:
- Systematic biases (always too bullish? always waiting?)
- Tools that return bad/stale data
- Skills that produce verbose reasoning but weak decisions
- Missing capabilities that would give Monet an edge

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
│   │   ├── memory.py               # load_agent_context() — structured memory for system prompt
│   │   ├── auth.py                 # Supabase JWT validation via langgraph_sdk.Auth
│   │   ├── middleware.py           # handle_tool_errors + ToolRetryMiddleware
│   │   ├── alpaca_client.py        # Alpaca paper trading client
│   │   ├── market_data.py          # Historical bars, quotes, portfolio from Alpaca
│   │   ├── technical.py            # RSI, MACD, Bollinger, SMA, ATR indicators
│   │   └── risk.py                 # Pre-trade risk checks
│   ├── skills/                     # Deep Agent skill definitions
│   │   ├── factor-loop/SKILL.md    # Factor-based: score_universe → signals → execute (6 steps)
│   │   ├── trading-loop/SKILL.md   # Legacy: subjective research → analyze → decide (Steps 0-8)
│   │   ├── reflection/SKILL.md     # EOD reflection + factor performance evaluation
│   │   ├── weekly-review/SKILL.md  # Sunday: factor weight optimization + performance review
│   │   ├── database-guide/SKILL.md # Schema reference for query_database
│   │   ├── research/SKILL.md       # (legacy — replaced by trading-loop)
│   │   ├── analysis/SKILL.md       # (legacy — replaced by trading-loop)
│   │   ├── trade-execution/SKILL.md # (legacy — replaced by trading-loop)
│   │   └── weekend-research/SKILL.md # (legacy — replaced by trading-loop weekend mode)
│   └── scripts/
│       ├── seed_strategy.py        # One-time seed for founding strategy
│       ├── seed_stage.py           # Seed agent_stage to "explore"
│       ├── seed_factor_weights.py  # Seed factor_weights for factor-based system
│       ├── create_crons.py         # Create/update LangGraph cron jobs
│       └── migrate_memory.py       # One-time migration to structured memory
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
| `autonomous_loop` | `autonomy.py:autonomous_graph` | Trading loop — runs on cron | Full: above + place_order, write_memory, write_journal, watchlist, risk check, technicals, fundamentals, screening, structured memory tools |

## Scheduling (17 runs/week)

The autonomous loop runs via **LangGraph Platform crons**:

### Weekdays (Mon-Fri) — 3 runs/day
| Cron (UTC) | Toronto | Skill | Focus |
|------------|---------|-------|-------|
| `0 14 * * 1-5` | 10am | Factor Loop | Score universe → signals → execute |
| `0 17 * * 1-5` | 1pm | Factor Loop | Re-score (uses 4hr cache), check for earnings reactions |
| `0 20 * * 1-5` | 4pm | Reflection | EOD review, factor performance evaluation, daily recap |

### Weekends — 1 run/day
| Cron (UTC) | Toronto | Skill | Focus |
|------------|---------|-------|-------|
| `0 15 * * 6` | Sat 11am | Factor Loop (weekend mode) | Full 50-stock ranking, no execution |
| `0 15 * * 0` | Sun 11am | Weekly Review | Factor weight optimization, performance review |

### Factor-Based System (replaces Explore/Exploit lifecycle)
The factor-based system has no lifecycle stages. Every run scores the full universe systematically:
- `score_universe()` ranks ~150 stocks on momentum, quality, value factors
- `enrich_eps_revisions()` adds EPS revision signal for top candidates
- `generate_factor_rankings()` produces BUY/SELL/HOLD signals deterministically
- Anti-churn: SELL only below rank 100 or falling EPS revisions; min 5-day hold period

Managed via `agent/scripts/create_crons.py`. **Note**: UTC-based, needs manual adjustment for DST changes (EDT/EST)

## Structured Memory Layer

Memory uses typed schemas stored in `agent_memory` with key prefixes:

| Key Pattern | Tool | Schema |
|-------------|------|--------|
| `market_regime` | `update_market_regime()` | `{vix, breadth_pct, rotation_signal, regime_label, confidence, as_of}` |
| `stock:{SYMBOL}` | `update_stock_analysis()` | `{symbol, thesis, target_entry, target_exit, confidence, composite_score, momentum_score, quality_score, value_score, eps_revision_score, status, target_set_date, regime_when_set, last_analyzed}` |
| `decision:{SYMBOL}:{YYYY-MM-DD}` | `record_decision()` | `{symbol, action, reasoning, confidence, price_at_decision, executed, decided_at}` |
| `factor_rankings` | `write_agent_memory()` | `{top_10: [...], factor_weights, scored_at, universe_size, vix_at_scoring}` |
| `factor_weights` | `write_agent_memory()` | `{momentum: 0.35, quality: 0.30, value: 0.20, eps_revision: 0.15, adjusted_at, reason}` |
| `earnings_reaction:{SYMBOL}` | `write_agent_memory()` | `{quarter, actual_eps, estimated_eps, surprise_pct, guidance, estimate_revision, thesis_impact, action_taken, date}` |
| `strategy`, `risk_appetite` | `write_agent_memory()` | Freeform (unchanged) |

`load_agent_context()` reads structured keys categorically (including factor_rankings and factor_weights) and falls back to legacy format gracefully.

## Composite-Based Order Logic

Order aggressiveness is derived from the factor composite score (0-100), passed via `composite_score` parameter to `place_order()`:

| Composite Score | Order Type | Rationale |
|----------------|------------|-----------|
| 80+ | Market order | High-factor-score stock. Get the fill. |
| 70-80 | Limit 1% below current | Moderate signal. Want a small pullback. |
| 60-70 | Limit 3% below current | Weaker signal. Only buy if it comes to you. |

**Key principle**: Factor scores drive order type, not subjective conviction. Sector rotation is a soft signal, not a hard gate.

## Deployment

- **LangGraph Platform**: `https://monet-0f211e9ce05255c2a85f92d6847873b5.us.langgraph.app`
- **Tracing**: LangSmith project `monet`
- **Web frontend**: Vercel (Next.js)

## Supabase Tables

| Table | Purpose |
|-------|---------|
| `agent_memory` | Structured key-value beliefs (market_regime, stock:*, decision:*, strategy, etc.) |
| `agent_journal` | Timestamped entries (research, analysis, trade, reflection, user_insight) |
| `trades` | Trade log with thesis, confidence, broker_order_id, status |
| `watchlist` | Symbols with thesis, target_entry, target_exit (auto-synced by update_stock_analysis) |
| `risk_settings` | Single row: max_position_pct, max_daily_loss, max_total_exposure_pct, default_stop_loss_pct |
| `profiles` | Web UI viewer profiles |

## Key Patterns

- Agent uses `deepagents` + `create_deep_agent` for graph definition
- `FilesystemBackend(virtual_mode=True)` for skill file access
- Auth: Supabase JWT validated via `langgraph_sdk.Auth`, dev mode allows unauthenticated
- Middleware: `handle_tool_errors` (catch-all safety net) + `ToolRetryMiddleware` (retries for search/quote/historical)
- Frontend: `@assistant-ui/react` + `@langchain/langgraph-sdk` for streaming chat
- Memory: `load_agent_context()` reads structured memory (market_regime, stock:*, decision:*) and formats categorically
- Risk: `check_risk()` is called inside `place_order` — trades that fail risk checks are rejected
- Chat tool priority: journal/memory first → live market data → internet search last

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

# Migrate legacy memory to structured format
cd agent && python scripts/migrate_memory.py
```

## Release Log

When you ship a meaningful change (new tool, UI restructure, new skill, behavior change), update the release log at `web/components/trading/release-log.tsx`:
- Add a new entry at the top of the `RELEASES` array
- Bump the version (v0.1, v0.2, etc.)
- Use today's date and a short title
- List 3-5 bullet points summarizing what changed

## Strategic Direction

### Core Edge: Systematic Discipline for Individuals

The median individual investor underperforms SPY by 3-5% annually (DALBAR). Main causes: FOMO, panic selling, revenge trading, concentration risk, no exit plan. Monet eliminates all of these by design. Even with imperfect factor weights, avoiding behavioral mistakes alone is worth 3-5% annually.

**Where AI beats an individual investor:**
- **Breadth**: Score 900 stocks every run vs following 5-15 you've heard of
- **No emotions**: Composite score IS the decision — can't panic sell or FOMO buy
- **Consistency**: Same rules every day, no strategy drift based on mood
- **Speed**: React to earnings within hours, not days
- **Risk discipline**: Auto stop-loss + take-profit on every position, enforced in code

**Where the LLM adds unique value:**
1. **Interpreting earnings qualitatively** (Step 3.5) — "revenue beat but guidance was soft because of a one-time export restriction" → don't sell. No quant firm has this.
2. **Risk sensing** — "VIX is spiking because of geopolitical event, not fundamentals" → don't panic sell

### Factor-Based System (Implemented March 2026)

- `score_universe()` scores ~900 stocks on momentum, quality, value factors deterministically
- `enrich_eps_revisions()` adds EPS revision signal (estimate direction + analyst breadth) from yfinance
- `generate_factor_rankings()` produces BUY/SELL/HOLD signals — no LLM reasoning
- Composite score replaces subjective confidence (0-100, not 0.0-1.0 vibes)

### Future Vision

1. **Personalized portfolios** — Tailor factor weights and universe based on each user's preferences, risk tolerance, and sector interests. Multiple portfolios per user.
2. **Community + domain expertise** — Monet runs a community where users with domain expertise (e.g., industry engineers, healthcare professionals) contribute qualitative insights that get aggregated as signals. This is a data moat no quant firm has.
3. **Education** — The goal is to make users better investors, not dependent on Monet. Show them why factor scoring works, what their behavioral biases are, and how to think systematically.

## Project Files

- **`IDEAS.md`** — Feature backlog with priority ordering. Update when new ideas come up.
- **`POSTDEPLOY_CHECK.md`** — Ongoing verification checklist for deployed features. Check pending items when reviewing run quality. Move verified items to the completed section.
- **`web/components/trading/release-log.tsx`** — User-facing release log. Update when shipping meaningful changes.

## Important Rules

- Chat mode tools are READ-ONLY — never expose `place_order` in chat
- Chat mode checks internal data (journal, memory) BEFORE reaching for internet search
- Autonomous mode writes structured memory after every loop
- All trades must pass risk checks before execution (5% stop loss, 80% max exposure, $500 daily loss limit)
- The agent has ONE persistent identity, not per-user sessions
- Max 5-8 positions, 10% max per position, 20% cash buffer
- After each cycle: compare outcomes to thesis, calibrate confidence, update beliefs
- Sector rotation is a soft signal — don't block high-conviction trades solely because of it

## Environment Variables

Required in `agent/.env`:
- `ANTHROPIC_API_KEY` — LLM
- `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` — Database
- `ALPACA_API_KEY`, `ALPACA_SECRET_KEY`, `ALPACA_BASE_URL` — Paper trading
- `TAVILY_API_KEY` — Web search
- `LANGSMITH_API_KEY`, `LANGSMITH_TRACING`, `LANGSMITH_PROJECT` — Observability
- `MODEL_NAME` — Model ID (default: `anthropic:claude-sonnet-4-5-20250929`)
