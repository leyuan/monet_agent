"use client";

import { useEffect, useState } from "react";
import { createClient } from "@/lib/supabase/client";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

interface PerformanceData {
  overallReturn: number;
  currentEquity: number;
  startingEquity: number;
  dailyPnl: number;
  filledTrades: number;
  sinceDate: string | null;
}

export function PerformanceCard() {
  const [data, setData] = useState<PerformanceData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      const supabase = createClient();

      const STARTING_EQUITY = 100_000;

      const [tradesRes, portfolioRes, firstSnapshotRes] = await Promise.all([
        supabase
          .from("trades")
          .select("id", { count: "exact", head: true })
          .in("status", ["filled", "OrderStatus.FILLED", "OrderStatus.PARTIALLY_FILLED"]),
        fetch("/api/portfolio").then((r) => r.ok ? r.json() : null).catch(() => null),
        supabase
          .from("equity_snapshots")
          .select("snapshot_date")
          .order("snapshot_date", { ascending: true })
          .limit(1)
          .maybeSingle(),
      ]);

      const acct = portfolioRes?.account;
      const currentEquity = acct?.equity ? parseFloat(acct.equity) : 0;
      const dailyPnl = acct?.equity && acct?.last_equity
        ? parseFloat(acct.equity) - parseFloat(acct.last_equity)
        : 0;
      const startingEquity = STARTING_EQUITY;
      const overallReturn = currentEquity > 0
        ? ((currentEquity - startingEquity) / startingEquity) * 100
        : 0;

      setData({
        overallReturn,
        currentEquity,
        startingEquity,
        dailyPnl,
        filledTrades: tradesRes.count ?? 0,
        sinceDate: firstSnapshotRes.data?.snapshot_date ?? null,
      });
      setLoading(false);
    }
    load();
  }, []);

  if (loading) {
    return (
      <Card>
        <CardContent className="p-8 flex flex-col items-center gap-3">
          <Skeleton className="h-10 w-28" />
          <Skeleton className="h-4 w-24" />
          <Skeleton className="h-3 w-36 mt-2" />
        </CardContent>
      </Card>
    );
  }

  if (!data) return null;

  const { overallReturn, currentEquity, startingEquity, sinceDate } = data;
  const sign = overallReturn > 0 ? "+" : "";
  const formatted = `${sign}${overallReturn.toFixed(2)}%`;
  const sinceLabel = sinceDate
    ? new Date(sinceDate).toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" })
    : null;
  const fmt = (n: number) =>
    n.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });

  return (
    <Card>
      <CardContent className="p-8 flex flex-col items-center gap-3">
        <p
          className={cn(
            "text-4xl font-bold tracking-tight",
            overallReturn > 0
              ? "text-green-600"
              : overallReturn < 0
                ? "text-red-500"
                : "text-muted-foreground"
          )}
        >
          {formatted}
        </p>
        <p className="text-sm text-muted-foreground">
          Overall Return{sinceLabel ? <span className="text-xs ml-1 opacity-60">since {sinceLabel}</span> : null}
        </p>

        {currentEquity > 0 && (
          <div className="flex items-center gap-3 text-xs text-muted-foreground mt-1">
            <span>{fmt(startingEquity)}</span>
            <span className="text-muted-foreground/40">&rarr;</span>
            <span className="font-semibold text-foreground">{fmt(currentEquity)}</span>
          </div>
        )}

      </CardContent>
    </Card>
  );
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
interface FactorRanking {
  rank: number;
  symbol: string;
  composite_score: number;
  momentum_score: number;
  quality_score: number;
  value_score: number;
  eps_revision_score: number;
}

interface FactorData {
  weights: { momentum: number; quality: number; value: number; eps_revision: number } | null;
  topRankings: FactorRanking[];
  scoredAt: string | null;
  universeSize: number | null;
}

export function FactorSystemCard() {
  const [data, setData] = useState<FactorData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      const supabase = createClient();

      const [weightsRes, rankingsRes] = await Promise.all([
        supabase
          .from("agent_memory")
          .select("value")
          .eq("key", "factor_weights")
          .single(),
        supabase
          .from("agent_memory")
          .select("value")
          .eq("key", "factor_rankings")
          .single(),
      ]);

      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const weightsVal = weightsRes.data?.value as any;
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const rankingsVal = rankingsRes.data?.value as any;

      setData({
        weights: weightsVal
          ? {
              momentum: weightsVal.momentum ?? 0.35,
              quality: weightsVal.quality ?? 0.30,
              value: weightsVal.value ?? 0.20,
              eps_revision: weightsVal.eps_revision ?? 0.15,
            }
          : null,
        topRankings: rankingsVal?.top_10 ?? rankingsVal?.rankings ?? [],
        scoredAt: rankingsVal?.scored_at ?? null,
        universeSize: rankingsVal?.universe_size ?? null,
      });
      setLoading(false);
    }
    load();
  }, []);

  if (loading) {
    return (
      <Card>
        <CardContent className="p-6 space-y-4">
          <Skeleton className="h-4 w-32" />
          <Skeleton className="h-2 w-full" />
          <Skeleton className="h-3 w-full" />
        </CardContent>
      </Card>
    );
  }

  if (!data) return null;

  const top5 = data.topRankings.slice(0, 5);

  return (
    <Card>
      <CardContent className="p-6 space-y-4">
        <div className="flex items-center justify-between">
          <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            Factor System
          </p>
          {data.universeSize && (
            <p className="text-xs text-muted-foreground">
              {data.universeSize} stocks scored
            </p>
          )}
        </div>

        {/* Factor weights bar */}
        {data.weights && (
          <div className="space-y-1.5">
            <div className="flex h-2.5 rounded-full overflow-hidden">
              <div className="bg-blue-500" style={{ width: `${data.weights.momentum * 100}%` }} />
              <div className="bg-emerald-500" style={{ width: `${data.weights.quality * 100}%` }} />
              <div className="bg-amber-500" style={{ width: `${data.weights.value * 100}%` }} />
              <div className="bg-purple-500" style={{ width: `${data.weights.eps_revision * 100}%` }} />
            </div>
            <div className="flex justify-between text-[10px] text-muted-foreground">
              <span className="flex items-center gap-1">
                <span className="inline-block size-1.5 rounded-full bg-blue-500" />
                Mom {Math.round(data.weights.momentum * 100)}%
              </span>
              <span className="flex items-center gap-1">
                <span className="inline-block size-1.5 rounded-full bg-emerald-500" />
                Qual {Math.round(data.weights.quality * 100)}%
              </span>
              <span className="flex items-center gap-1">
                <span className="inline-block size-1.5 rounded-full bg-amber-500" />
                Val {Math.round(data.weights.value * 100)}%
              </span>
              <span className="flex items-center gap-1">
                <span className="inline-block size-1.5 rounded-full bg-purple-500" />
                EPS {Math.round(data.weights.eps_revision * 100)}%
              </span>
            </div>
          </div>
        )}

        {/* Top 5 rankings */}
        {top5.length > 0 && (
          <div className="space-y-1">
            {top5.map((r) => (
              <div key={r.symbol} className="flex items-center justify-between text-xs">
                <div className="flex items-center gap-2">
                  <span className="text-muted-foreground w-4">#{r.rank}</span>
                  <span className="font-semibold">{r.symbol}</span>
                </div>
                <span
                  className={cn(
                    "font-semibold tabular-nums",
                    r.composite_score >= 80
                      ? "text-green-600"
                      : r.composite_score >= 70
                        ? "text-yellow-600"
                        : "text-muted-foreground"
                  )}
                >
                  {r.composite_score?.toFixed(1)}
                </span>
              </div>
            ))}
          </div>
        )}

        {data.scoredAt && (
          <p className="text-[10px] text-muted-foreground/60">
            Last scored: {new Date(data.scoredAt).toLocaleString()}
          </p>
        )}
      </CardContent>
    </Card>
  );
}
