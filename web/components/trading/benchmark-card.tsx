"use client";

import { useEffect, useState } from "react";
import { createClient } from "@/lib/supabase/client";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

interface Snapshot {
  snapshot_date: string;
  portfolio_cumulative_return: number;
  spy_cumulative_return: number;
  alpha: number | null;
  deployed_pct: number;
}

const STARTING_EQUITY = 100_000;

export function BenchmarkCard() {
  const [snapshots, setSnapshots] = useState<Snapshot[]>([]);
  const [liveReturnPct, setLiveReturnPct] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      const supabase = createClient();
      const [snapshotRes, portfolioRes] = await Promise.all([
        supabase
          .from("equity_snapshots")
          .select("snapshot_date, portfolio_cumulative_return, spy_cumulative_return, alpha, deployed_pct")
          .order("snapshot_date", { ascending: true })
          .limit(90),
        fetch("/api/portfolio").then((r) => r.ok ? r.json() : null).catch(() => null),
      ]);

      setSnapshots((snapshotRes.data as Snapshot[] | null) ?? []);

      if (portfolioRes?.account?.equity) {
        const equity = parseFloat(portfolioRes.account.equity);
        if (equity > 0) {
          setLiveReturnPct(((equity - STARTING_EQUITY) / STARTING_EQUITY) * 100);
        }
      }

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
          <Skeleton className="h-16 w-full mt-2" />
        </CardContent>
      </Card>
    );
  }

  const latest = snapshots.length > 0 ? snapshots[snapshots.length - 1] : null;
  const earliest = snapshots.length > 0 ? snapshots[0] : null;
  const deployedPct = latest?.deployed_pct ?? 0;
  const portfolioReturn = liveReturnPct ?? latest?.portfolio_cumulative_return ?? 0;
  const spyReturn = latest?.spy_cumulative_return ?? 0;
  const alpha = portfolioReturn - spyReturn;
  const isMeaningful = latest?.alpha != null;
  const sinceLabel = earliest?.snapshot_date
    ? new Date(earliest.snapshot_date).toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" })
    : null;

  return (
    <Card>
      <CardContent className="p-8 flex flex-col items-center gap-1">
        {isMeaningful ? (
          <p
            className={cn(
              "text-4xl font-bold tracking-tight",
              alpha > 0 ? "text-green-600" : alpha < 0 ? "text-red-500" : "text-muted-foreground"
            )}
          >
            {alpha > 0 ? "+" : ""}{alpha.toFixed(2)}%
          </p>
        ) : (
          <p className="text-4xl font-bold tracking-tight text-muted-foreground">—</p>
        )}
        <p className="text-sm text-muted-foreground">
          {isMeaningful
            ? <>Alpha vs SPY{sinceLabel ? <span className="text-xs ml-1 opacity-60">since {sinceLabel}</span> : null}</>
            : `${Math.round(deployedPct)}% deployed — alpha not yet meaningful`}
        </p>

        {/* Sparkline */}
        {snapshots.length > 1 && (
          <div className="w-full mt-3">
            <Sparkline data={snapshots} />
          </div>
        )}

        <div className="flex gap-4 text-xs text-muted-foreground mt-2">
          <span>Portfolio: <span className={cn("font-medium", portfolioReturn >= 0 ? "text-green-600" : "text-red-500")}>{portfolioReturn >= 0 ? "+" : ""}{portfolioReturn.toFixed(2)}%</span></span>
          <span>SPY: <span className={cn("font-medium", spyReturn >= 0 ? "text-green-600" : "text-red-500")}>{spyReturn >= 0 ? "+" : ""}{spyReturn.toFixed(2)}%</span></span>
        </div>
      </CardContent>
    </Card>
  );
}

function Sparkline({ data }: { data: Snapshot[] }) {
  const width = 200;
  const height = 40;
  const padding = 2;

  const allValues = data.flatMap((d) => [d.portfolio_cumulative_return, d.spy_cumulative_return]);
  const min = Math.min(...allValues);
  const max = Math.max(...allValues);
  const range = max - min || 1;

  function toPath(values: number[]): string {
    return values
      .map((v, i) => {
        const x = padding + (i / (values.length - 1)) * (width - 2 * padding);
        const y = height - padding - ((v - min) / range) * (height - 2 * padding);
        return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
      })
      .join(" ");
  }

  const portfolioPath = toPath(data.map((d) => d.portfolio_cumulative_return));
  const spyPath = toPath(data.map((d) => d.spy_cumulative_return));

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="w-full h-10" preserveAspectRatio="none">
      <path d={spyPath} fill="none" stroke="currentColor" strokeWidth="1.5" className="text-muted-foreground/40" />
      <path d={portfolioPath} fill="none" stroke="currentColor" strokeWidth="2" className="text-primary" />
    </svg>
  );
}
