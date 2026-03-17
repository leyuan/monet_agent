"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

interface ReleaseEntry {
  version: string;
  date: string;
  title: string;
  items: string[];
}

const RELEASES: ReleaseEntry[] = [
  {
    version: "v1.3",
    date: "Mar 17",
    title: "AI Bubble / Sector Concentration Risk Monitor",
    items: [
      "New assess_ai_bubble_risk() tool: 0-100 score from portfolio concentration, SMH vs SPY momentum, and stale positions",
      "Factor loop Step 1.5: runs every loop, persists result to agent_memory key ai_bubble_risk",
      "Soft cap at score > 80: limits new AI-basket BUYs to 1 per run — never blocks SELL signals",
      "Dashboard AI Concentration Risk card: score, level, AI exposure %, SMH vs SPY 3m, stale positions",
    ],
  },
  {
    version: "v1.2",
    date: "Mar 15",
    title: "Stock Detail Pages & Dynamic Factor Weights",
    items: [
      "New /earnings/[symbol] detail page: company profile, leadership, thesis, factor scores, earnings history, decisions, journal",
      "Company data from Yahoo Finance: description, sector, key metrics (P/E, margins, revenue growth), leadership with Wikipedia photos",
      "Earnings history backfilled from Yahoo Finance when Supabase has no quarterly data",
      "Stock logos via Parqet, executive portraits via Wikipedia API with initials fallback",
      "Factor weights now read from memory — weekly review adjustments actually change scoring logic",
      "Dashboard earnings card: stock symbols are clickable links to detail pages",
    ],
  },
  {
    version: "v1.1",
    date: "Mar 15",
    title: "Earnings Intelligence System",
    items: [
      "Persistent earnings profiles (earnings_profile:SYMBOL) that accumulate across quarters",
      "New get_earnings_results() tool: 4-quarter surprise history + forward estimate revisions in one call",
      "Auto-bootstrap: first encounter builds profile from Finnhub history with pattern detection",
      "Qualitative highlights per quarter from internet search (guidance shifts, strategic announcements)",
      "Earnings profiles loaded into agent context for passive decision support",
    ],
  },
  {
    version: "v1.0",
    date: "Mar 13",
    title: "Catalyst & Event Tracking",
    items: [
      "New discover_catalysts() tool: searches for conferences, product launches, investor days, regulatory events",
      "Catalyst guard (Step 3.25): blocks BUY signals near high-risk events, flags positions for trim",
      "Weekend catalyst discovery: Saturday runs scan 30 days ahead and write structured memory",
      "Calendar UI: purple dots for catalyst events with detail panel on click",
      "Weekly review now prunes past catalysts and evaluates guard effectiveness",
    ],
  },
  {
    version: "v0.9",
    date: "Mar 12",
    title: "Dashboard & About Me for Investors",
    items: [
      "About Me page rewritten with full system description (EN/CN toggle)",
      "Dashboard: Factor System card replaces legacy Lifecycle card",
      "Factor weights bar, top 5 rankings, universe size on dashboard",
      "Chat flashing fix: removed gen-ui cards causing rapid re-renders",
    ],
  },
  {
    version: "v0.8",
    date: "Mar 12",
    title: "EPS Revision Enhancement",
    items: [
      "Combined two signals: estimate direction (70%) + analyst breadth (30%)",
      "31 analysts revising up now scores higher than 3 analysts by same amount",
      "Switched from Finnhub (premium-only) to yfinance eps_trend (free)",
      "Added analyst up/down counts to enrichment output",
    ],
  },
  {
    version: "v0.7",
    date: "Mar 12",
    title: "Factor-Based Trading System",
    items: [
      "New scoring pipeline: score_universe() ranks ~900 stocks on 4 factors",
      "Factors: Momentum (35%), Quality (30%), Value (20%), EPS Revision (15%)",
      "Composite-based order types: >80 market, 70-80 limit 1%, 60-70 limit 3%",
      "Anti-churn rules: min 5-day hold, sell only below rank 100",
      "All crons switched from subjective analysis to systematic factor loop",
    ],
  },
  {
    version: "v0.6",
    date: "Mar 12",
    title: "Gen-UI for Chat",
    items: [
      "Rich tool UI cards: stock quotes, portfolio, sectors, technicals, fundamentals",
      "EPS estimates with revision signal badges",
      "Peer comparison tables, market breadth bars",
      "Performance comparison with alpha badge",
    ],
  },
  {
    version: "v0.5",
    date: "Mar 11",
    title: "Dashboard Redesign & EPS Estimates",
    items: [
      "Dashboard restructure: performance, lifecycle, benchmark cards up top",
      "Live portfolio data via Alpaca API route (server-side)",
      "Positions table with P&L on dashboard",
      "Finnhub EPS estimate/revision tool for fundamental analysis",
      "Release log on About Me page",
    ],
  },
  {
    version: "v0.4",
    date: "Mar 11",
    title: "Bracket Orders & Monitoring",
    items: [
      "Bracket orders with stop-loss and take-profit",
      "Benchmark tracking via equity_snapshots",
      "Position management and protection status",
      "Price alerts with 15-minute checks",
    ],
  },
  {
    version: "v0.3",
    date: "Mar 11",
    title: "Unified Trading Loop",
    items: [
      "Single-pass trading loop (research → analyze → decide)",
      "Structured memory layer (market_regime, stock:*, decision:*)",
      "Conviction-based order logic",
      "Chat prioritizes journal/memory over search",
    ],
  },
  {
    version: "v0.2",
    date: "Mar 10",
    title: "Limit Orders & UI",
    items: [
      "Limit order support",
      "Daily recap in reflection",
      "About Me cards (performance, lifecycle)",
      "Tool call UI in chat",
    ],
  },
  {
    version: "v0.1",
    date: "Mar 9",
    title: "Initial Release",
    items: [
      "Autonomous trading agent with cron schedule",
      "Research, analysis, and execution phases",
      "Alpaca paper trading integration",
      "Web dashboard and chat interface",
    ],
  },
];

export function ReleaseLog() {
  return (
    <Card className="h-fit">
      <CardHeader className="pb-3">
        <CardTitle className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
          Release Log
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-5 max-h-[600px] overflow-y-auto">
        {RELEASES.map((release) => (
          <div key={release.version}>
            <div className="flex items-baseline gap-2 mb-1">
              <span className="text-sm font-semibold">{release.version}</span>
              <span className="text-xs text-muted-foreground">{release.date}</span>
            </div>
            <p className="text-sm font-medium mb-1">{release.title}</p>
            <ul className="space-y-0.5">
              {release.items.map((item, i) => (
                <li key={i} className="text-xs text-muted-foreground leading-relaxed">
                  • {item}
                </li>
              ))}
            </ul>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
