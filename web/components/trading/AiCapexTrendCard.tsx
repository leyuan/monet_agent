"use client";

import { useEffect, useState } from "react";
import { createClient } from "@/lib/supabase/client";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

interface CapexName {
  latest: number | null;
  yoy_pct: number | null;
  qoq_pct: number | null;
  period: string | null;
  immaterial?: boolean;
}

interface AiCapexData {
  guidance_direction: string;
  financial_direction: string;
  hyperscaler_total_yoy: number | null;
  memory_yoy: number | null;
  per_name: Record<string, CapexName>;
  forward_guidance_direction: string | null;
  forward_guidance_summary: string | null;
  summary: string;
  as_of: string;
}

const HYPERSCALERS = ["MSFT", "GOOGL", "AMZN", "META"];
const MEMORY = ["MU", "WDC", "SNDK"];

function dirLabel(dir: string): string {
  switch (dir) {
    case "accelerating": return "Accelerating";
    case "stable": return "Stable";
    case "decelerating": return "Decelerating";
    default: return "Pending";
  }
}

function dirColor(dir: string): string {
  switch (dir) {
    case "accelerating": return "text-green-500";
    case "stable": return "text-yellow-500";
    case "decelerating": return "text-red-500";
    default: return "text-muted-foreground";
  }
}

function fmtYoY(v: number | null): string {
  if (v === null || v === undefined) return "—";
  const sign = v >= 0 ? "+" : "";
  return `${sign}${v.toFixed(0)}%`;
}

function fmtB(v: number | null): string {
  if (v === null || v === undefined) return "—";
  return `$${(v / 1e9).toFixed(1)}B`;
}

function NameRow({ sym, d }: { sym: string; d: CapexName | undefined }) {
  return (
    <div className="flex items-center justify-between text-sm">
      <span className="font-medium">{sym}</span>
      <div className="flex items-center gap-3 tabular-nums">
        <span className="text-muted-foreground w-14 text-right">{fmtB(d?.latest ?? null)}</span>
        <span
          className={cn(
            "w-12 text-right font-medium",
            (d?.yoy_pct ?? 0) > 0 ? "text-green-500" : (d?.yoy_pct ?? 0) < 0 ? "text-red-500" : "text-muted-foreground",
          )}
        >
          {fmtYoY(d?.yoy_pct ?? null)}
        </span>
      </div>
    </div>
  );
}

export function AiCapexTrendCard() {
  const [data, setData] = useState<AiCapexData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      const supabase = createClient();
      const { data: row } = await supabase
        .from("agent_memory")
        .select("value")
        .eq("key", "ai_capex_tracker")
        .maybeSingle();
      if (row?.value) setData(row.value as AiCapexData);
      setLoading(false);
    }
    load();
  }, []);

  if (loading) {
    return (
      <Card>
        <CardContent className="p-6 flex flex-col gap-3">
          <Skeleton className="h-4 w-40" />
          <Skeleton className="h-10 w-28" />
          <Skeleton className="h-24 w-full" />
        </CardContent>
      </Card>
    );
  }

  if (!data) {
    return (
      <Card>
        <CardContent className="p-6 flex flex-col gap-1">
          <p className="text-xs text-muted-foreground uppercase tracking-wide font-medium">
            AI Capex Trend
          </p>
          <p className="text-muted-foreground text-sm mt-2">No data yet — runs in the daily AI cycle refresh.</p>
        </CardContent>
      </Card>
    );
  }

  const asOf = data.as_of
    ? new Date(data.as_of).toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })
    : null;

  return (
    <Card>
      <CardContent className="p-6 flex flex-col gap-3">
        <p className="text-xs text-muted-foreground uppercase tracking-wide font-medium">
          AI Capex Trend
        </p>

        {/* Headline direction + hyperscaler YoY */}
        <div className="flex items-end gap-2">
          <span className={cn("text-4xl font-bold tabular-nums leading-none", dirColor(data.guidance_direction))}>
            {fmtYoY(data.hyperscaler_total_yoy)}
          </span>
          <span className={cn("text-sm font-semibold mb-0.5", dirColor(data.guidance_direction))}>
            {dirLabel(data.guidance_direction)}
          </span>
        </div>
        <p className="text-xs text-muted-foreground -mt-1">Hyperscaler capex, YoY</p>

        {/* Hyperscalers (demand) */}
        <div className="space-y-1 pt-1">
          <p className="text-[11px] uppercase tracking-wide text-muted-foreground/70 font-medium">Demand — Hyperscalers</p>
          {HYPERSCALERS.map((s) => (
            <NameRow key={s} sym={s} d={data.per_name?.[s]} />
          ))}
        </div>

        {/* Memory (supply) — hide names with immaterial/incomplete capex data */}
        <div className="space-y-1">
          <p className="text-[11px] uppercase tracking-wide text-muted-foreground/70 font-medium">
            Supply — Memory {data.memory_yoy !== null && <span className="normal-case">({fmtYoY(data.memory_yoy)} YoY)</span>}
          </p>
          {MEMORY.filter((s) => {
            const d = data.per_name?.[s];
            return d && !d.immaterial && d.latest != null;
          }).map((s) => (
            <NameRow key={s} sym={s} d={data.per_name?.[s]} />
          ))}
        </div>

        {/* Forward guidance */}
        {data.forward_guidance_summary && (
          <p className="text-xs text-muted-foreground border-t pt-2">
            <span className="font-medium text-foreground">Guidance: </span>
            {data.forward_guidance_summary}
          </p>
        )}

        {asOf && (
          <p className="text-xs text-muted-foreground border-t pt-2 mt-1">Updated {asOf}</p>
        )}
      </CardContent>
    </Card>
  );
}
