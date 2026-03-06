# Stock Agent — Autonomous AI Investor

## Project Overview
An autonomous AI stock trading agent that makes its own trading decisions on a schedule (research -> analyze -> trade -> reflect). Uses Alpaca paper trading, has persistent memory in Supabase, and a Next.js web UI for monitoring/chat.

## Architecture
- `agent/` — Python backend (LangGraph + Deep Agents)
  - Two modes: **Autonomous** (scheduled loop) and **Chat** (read-only window)
  - Single persistent identity with memory in Supabase
- `web/` — Next.js frontend (monitoring + chat)
- `supabase/` — Database migrations

## Key Patterns
- Agent uses `deepagents` + `create_deep_agent` for graph definition
- Supabase JWT auth via `langgraph_sdk.Auth`
- Tools use `ToolRuntime` for accessing config/auth context
- Middleware: `handle_tool_errors` (safety net) + `retry_middleware` (transient failures)
- Frontend: `@assistant-ui/react` + `@langchain/langgraph-sdk` for streaming chat

## Commands
```bash
# Agent
cd agent && langgraph dev          # Run agent locally
cd agent && pip install -e ".[dev]" # Install with dev deps

# Web
cd web && npm install && npm run dev # Run frontend

# Supabase
supabase start                      # Local Supabase
supabase db reset                   # Apply migrations
```

## Important Rules
- Chat mode tools are READ-ONLY — never expose `place_order` in chat
- Autonomous mode writes to `agent_journal` and `agent_memory` after every loop
- All trades must pass risk checks before execution
- The agent has ONE persistent identity, not per-user sessions
