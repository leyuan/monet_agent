"use client";

import { useEffect, useState } from "react";
import { createClient } from "@/lib/supabase/client";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

interface SnapRow {
  snapshot_date: string;
  portfolio: string;
  portfolio_cumulative_return: number | null;
  spy_cumulative_return: number | null;
}

interface Point {
  date: string;
  quant: number | null;
  conviction: number | null;
  spy: number | null;
}

function LatestStat({ label, value, color }: { label: string; value: number | null; color: string }) {
  const has = value !== null && value !== undefined;
  return (
    <div className="flex flex-col">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className={cn("text-lg font-semibold tabular-nums", has ? color : "text-muted-foreground")}>
        {has ? `${value! >= 0 ? "+" : ""}${value!.toFixed(2)}%` : "—"}
      </span>
    </div>
  );
}

export function PortfolioComparisonCard() {
  const [points, setPoints] = useState<Point[]>([]);
  const [adjusted, setAdjusted] = useState(0);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      const supabase = createClient();
      const [snapRes, adjRes] = await Promise.all([
        supabase
          .from("equity_snapshots")
          .select("snapshot_date, portfolio, portfolio_cumulative_return, spy_cumulative_return")
          .order("snapshot_date", { ascending: true })
          .limit(400),
        supabase.from("agent_memory").select("value").eq("key", "performance_adjustments").maybeSingle(),
      ]);

      const rows = (snapRes.data as SnapRow[] | null) ?? [];
      // Merge by date: quant return, conviction return, and one SPY line (prefer quant's longer history).
      const byDate = new Map<string, Point>();
      for (const r of rows) {
        const p = byDate.get(r.snapshot_date) ?? { date: r.snapshot_date, quant: null, conviction: null, spy: null };
        if (r.portfolio === "quant") {
          p.quant = r.portfolio_cumulative_return;
          p.spy = r.spy_cumulative_return;
        } else if (r.portfolio === "conviction") {
          p.conviction = r.portfolio_cumulative_return;
          if (p.spy === null) p.spy = r.spy_cumulative_return;
        }
        byDate.set(r.snapshot_date, p);
      }
      const merged = [...byDate.values()].sort((a, b) => a.date.localeCompare(b.date));

      // Add back one-time corporate-action corrections: a fixed-$ artifact shifts
      // cumulative return by amount/$100k pp for every point on/after its date.
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const adjs: any[] = (adjRes.data?.value as { adjustments?: any[] } | undefined)?.adjustments ?? [];
      setAdjusted(adjs.reduce((s, a) => s + Math.abs(Number(a.amount ?? 0)), 0));
      for (const p of merged) {
        for (const a of adjs) {
          if (!a.date || a.amount == null || p.date < a.date) continue;
          const pp = Number(a.amount) / 1000; // amount / $100k * 100
          const book = a.portfolio ?? "quant";
          if (book === "quant" && p.quant !== null) p.quant += pp;
          if (book === "conviction" && p.conviction !== null) p.conviction += pp;
        }
      }
      setPoints(merged);
      setLoading(false);
    }
    load();
  }, []);

  if (loading) {
    return (
      <Card>
        <CardContent className="p-6">
          <Skeleton className="h-4 w-56 mb-4" />
          <Skeleton className="h-72 w-full" />
        </CardContent>
      </Card>
    );
  }

  const latest = points.length ? points[points.length - 1] : null;
  const latestConviction = [...points].reverse().find((p) => p.conviction !== null)?.conviction ?? null;

  return (
    <Card>
      <CardContent className="p-6">
        <div className="flex items-start justify-between mb-4 flex-wrap gap-4">
          <div>
            <p className="text-xs text-muted-foreground uppercase tracking-wide font-medium">
              Quant Core vs Conviction vs SPY
            </p>
            <p className="text-xs text-muted-foreground mt-1">
              Cumulative return since each book&apos;s inception
              {adjusted > 0 && (
                <span className="text-muted-foreground/70"> · incl. +${(adjusted / 1000).toFixed(1)}k KLAC split-artifact correction</span>
              )}
            </p>
          </div>
          <div className="flex gap-6">
            <LatestStat label="Quant Core" value={latest?.quant ?? null} color="text-foreground" />
            <LatestStat label="Conviction" value={latestConviction} color="text-indigo-500" />
            <LatestStat label="SPY" value={latest?.spy ?? null} color="text-muted-foreground" />
          </div>
        </div>

        {points.length === 0 ? (
          <div className="h-72 flex items-center justify-center text-sm text-muted-foreground">
            No equity history yet.
          </div>
        ) : (
          <div className="h-72">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={points}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                <XAxis
                  dataKey="date"
                  tickFormatter={(v) => String(v).slice(5)}
                  interval="preserveStartEnd"
                  minTickGap={40}
                  fontSize={10}
                />
                <YAxis tickFormatter={(v) => `${v.toFixed(0)}%`} fontSize={10} />
                <Tooltip formatter={(v) => (typeof v === "number" ? `${v.toFixed(2)}%` : String(v ?? ""))} />
                <Legend wrapperStyle={{ fontSize: "12px" }} />
                <Line type="monotone" dataKey="quant" name="Quant Core" stroke="#111827" strokeWidth={2} dot={false} connectNulls />
                <Line type="monotone" dataKey="conviction" name="Conviction" stroke="#6366f1" strokeWidth={2} dot={false} connectNulls />
                <Line type="monotone" dataKey="spy" name="SPY" stroke="#9ca3af" strokeWidth={1.5} strokeDasharray="4 2" dot={false} connectNulls />
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
