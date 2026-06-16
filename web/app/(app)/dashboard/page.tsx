"use client";

import { useEffect, useState } from "react";
import { createClient } from "@/lib/supabase/client";
import { PerformanceCard, FactorSystemCard } from "@/components/trading/performance-card";
import { BenchmarkCard } from "@/components/trading/benchmark-card";
import { PortfolioSummary, PositionsTable } from "@/components/trading/portfolio-card";
import { TradeCard, TradeCardCompact } from "@/components/trading/trade-card";
import { EarningsIntelligenceCard } from "@/components/trading/earnings-card";
import { AiSuperCycleCard } from "@/components/trading/AiSuperCycleCard";
import { BacktestSummaryCard } from "@/components/trading/BacktestSummaryCard";
import { StrategyHealthCard } from "@/components/trading/StrategyHealthCard";
import { PortfolioComparisonCard } from "@/components/trading/PortfolioComparisonCard";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { fetchPerfAdjustments, cumulativeAdjustment, todayAdjustment as computeTodayAdjustment } from "@/lib/performance-adjustments";

type PortfolioSlug = "quant" | "conviction";
const PORTFOLIOS: { slug: PortfolioSlug; label: string }[] = [
  { slug: "quant", label: "Quant Core" },
  { slug: "conviction", label: "Conviction" },
];

export default function DashboardPage() {
  const [selected, setSelected] = useState<PortfolioSlug>("quant");
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [portfolio, setPortfolio] = useState<any>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [trades, setTrades] = useState<any[]>([]);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [watchlist, setWatchlist] = useState<any[]>([]);
  const [adjustment, setAdjustment] = useState(0);
  const [todayAdjustment, setTodayAdjustment] = useState(0);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      const supabase = createClient();

      const [portfolioRes, tradesRes, watchlistRes, adjRes] = await Promise.all([
        fetch(`/api/portfolio?portfolio=${selected}`).then((r) => r.ok ? r.json() : null).catch(() => null),
        supabase.from("trades").select("*").eq("portfolio", selected).order("created_at", { ascending: false }).limit(10),
        supabase.from("watchlist").select("*").order("added_at", { ascending: false }),
        fetchPerfAdjustments(supabase),
      ]);

      if (cancelled) return;
      setPortfolio(portfolioRes);
      setTrades(tradesRes.data ?? []);
      setWatchlist(watchlistRes.data ?? []);

      // One-time corporate-action corrections for the selected book (KLAC split
      // artifact = Quant Core only). Cumulative → Value/Realized; today's → Daily P&L
      // (the artifact only distorts the day it happened).
      const todayUtc = new Date().toISOString().slice(0, 10);
      setAdjustment(cumulativeAdjustment(adjRes, selected));
      setTodayAdjustment(computeTodayAdjustment(adjRes, selected, todayUtc));

      setLoading(false);
    }
    load();
    return () => { cancelled = true; };
  }, [selected]);

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="animate-pulse text-muted-foreground">Loading dashboard...</div>
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto p-6 space-y-6">
      <h1 className="text-2xl font-semibold">Dashboard</h1>

      {/* Headline: both books vs SPY */}
      <PortfolioComparisonCard />

      {/* Row 1: Quant Core strategy overview */}
      <div className="grid gap-4 lg:grid-cols-4">
        <PerformanceCard />
        <FactorSystemCard />
        <BenchmarkCard />
        <BacktestSummaryCard />
      </div>

      {/* Row 2: AI super-cycle summary (full detail on /ai-cycle) + Strategy Health */}
      <div className="grid gap-4 lg:grid-cols-2">
        <AiSuperCycleCard />
        <StrategyHealthCard />
      </div>

      {/* Portfolio book — toggle between Quant Core and Conviction */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <h2 className="text-lg font-semibold">Holdings</h2>
        <div className="inline-flex rounded-lg border p-0.5">
          {PORTFOLIOS.map((p) => (
            <button
              key={p.slug}
              onClick={() => setSelected(p.slug)}
              className={cn(
                "px-3 py-1 text-sm rounded-md transition-colors",
                selected === p.slug ? "bg-muted font-medium" : "text-muted-foreground hover:text-foreground",
              )}
            >
              {p.label}
            </button>
          ))}
        </div>
      </div>
      {portfolio?.account ? (
        <>
          <PortfolioSummary data={portfolio} adjustment={adjustment} todayAdjustment={todayAdjustment} />
          <PositionsTable positions={portfolio.positions} />
        </>
      ) : (
        <Card>
          <CardContent className="p-4 text-center text-muted-foreground">
            No account data for {PORTFOLIOS.find((p) => p.slug === selected)?.label}.
          </CardContent>
        </Card>
      )}

      {/* Row 3: Earnings Intelligence */}
      <EarningsIntelligenceCard />

      {/* Row 4: Watchlist + Recent Trades */}
      <div className="grid gap-6 lg:grid-cols-2">
        <div className="space-y-4">
          <h2 className="text-lg font-semibold">Watchlist</h2>
          {watchlist.length === 0 ? (
            <Card><CardContent className="p-4 text-center text-muted-foreground">Watchlist empty</CardContent></Card>
          ) : (
            <Card>
              <CardContent className="p-0">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b text-left text-muted-foreground">
                      <th className="p-3 font-medium">Symbol</th>
                      <th className="p-3 font-medium">Thesis</th>
                      <th className="p-3 font-medium">Target Entry</th>
                    </tr>
                  </thead>
                  <tbody>
                    {watchlist.map((w) => (
                      <tr key={w.id} className="border-b last:border-0">
                        <td className="p-3 font-mono font-semibold">{w.symbol}</td>
                        <td className="p-3 text-muted-foreground text-xs leading-relaxed">{w.thesis || "-"}</td>
                        <td className="p-3">{w.target_entry ? `$${w.target_entry}` : "-"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </CardContent>
            </Card>
          )}
        </div>

        <RecentTrades trades={trades} />
      </div>
    </div>
  );
}

const VISIBLE_COUNT = 3;

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function RecentTrades({ trades }: { trades: any[] }) {
  const [expanded, setExpanded] = useState(false);
  const visible = expanded ? trades : trades.slice(0, VISIBLE_COUNT);
  const hiddenCount = trades.length - VISIBLE_COUNT;

  return (
    <div className="space-y-4">
      <h2 className="text-lg font-semibold">Recent Trades</h2>
      {trades.length === 0 ? (
        <Card><CardContent className="p-4 text-center text-muted-foreground">No trades yet</CardContent></Card>
      ) : (
        <>
          {visible.map((t, i) =>
            i < VISIBLE_COUNT ? (
              <TradeCard key={t.id} trade={t} />
            ) : (
              <TradeCardCompact key={t.id} trade={t} />
            )
          )}
          {hiddenCount > 0 && !expanded && (
            <button
              onClick={() => setExpanded(true)}
              className="w-full text-center text-sm text-muted-foreground hover:text-foreground transition-colors py-2"
            >
              Show {hiddenCount} older trade{hiddenCount !== 1 ? "s" : ""}
            </button>
          )}
          {expanded && hiddenCount > 0 && (
            <button
              onClick={() => setExpanded(false)}
              className="w-full text-center text-sm text-muted-foreground hover:text-foreground transition-colors py-2"
            >
              Show less
            </button>
          )}
        </>
      )}
    </div>
  );
}
