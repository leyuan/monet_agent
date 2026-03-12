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
