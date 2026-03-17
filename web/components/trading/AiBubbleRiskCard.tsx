"use client";

import { useEffect, useState } from "react";
import { createClient } from "@/lib/supabase/client";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

interface AiBubbleRiskData {
  score: number;
  level: "low" | "moderate" | "elevated" | "high";
  smh_rsi: number;
  smh_vs_200ma_pct: number;
  basket_breadth_pct: number;
  nvda_forward_pe: number | null;
  action: string;
  as_of: string;
}

function scoreColor(level: string) {
  switch (level) {
    case "low":       return "text-green-500";
    case "moderate":  return "text-yellow-500";
    case "elevated":  return "text-orange-500";
    case "high":      return "text-red-500";
    default:          return "text-muted-foreground";
  }
}

function scoreLabel(level: string) {
  switch (level) {
    case "low":       return "Low";
    case "moderate":  return "Moderate";
    case "elevated":  return "Elevated";
    case "high":      return "High";
    default:          return "—";
  }
}

export function AiBubbleRiskCard() {
  const [data, setData] = useState<AiBubbleRiskData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      const supabase = createClient();
      const { data: row } = await supabase
        .from("agent_memory")
        .select("value")
        .eq("key", "ai_bubble_risk")
        .maybeSingle();

      if (row?.value) {
        setData(row.value as AiBubbleRiskData);
      }
      setLoading(false);
    }
    load();
  }, []);

  if (loading) {
    return (
      <Card>
        <CardContent className="p-6 flex flex-col gap-3">
          <Skeleton className="h-4 w-32" />
          <Skeleton className="h-10 w-20" />
          <Skeleton className="h-4 w-full" />
        </CardContent>
      </Card>
    );
  }

  if (!data) {
    return (
      <Card>
        <CardContent className="p-6 flex flex-col gap-1">
          <p className="text-xs text-muted-foreground uppercase tracking-wide font-medium">
            AI Sector Heat
          </p>
          <p className="text-muted-foreground text-sm mt-2">No data yet — runs after next factor loop.</p>
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
        {/* Eyebrow */}
        <p className="text-xs text-muted-foreground uppercase tracking-wide font-medium">
          AI Sector Heat
        </p>

        {/* Score + Level */}
        <div className="flex items-end gap-2">
          <span className={cn("text-4xl font-bold tabular-nums leading-none", scoreColor(data.level))}>
            {data.score}
          </span>
          <span className={cn("text-sm font-semibold mb-0.5", scoreColor(data.level))}>
            {scoreLabel(data.level)}
          </span>
        </div>

        {/* Sub-rows */}
        <div className="space-y-1 text-sm">
          <div className="flex justify-between">
            <span className="text-muted-foreground">SMH RSI(14)</span>
            <span className={cn("font-medium tabular-nums", data.smh_rsi >= 70 ? "text-orange-500" : "")}>
              {data.smh_rsi.toFixed(1)}
            </span>
          </div>
          <div className="flex justify-between">
            <span className="text-muted-foreground">SMH vs 200MA</span>
            <span className={cn("font-medium tabular-nums", data.smh_vs_200ma_pct >= 15 ? "text-orange-500" : "")}>
              {data.smh_vs_200ma_pct >= 0 ? "+" : ""}{data.smh_vs_200ma_pct.toFixed(1)}%
            </span>
          </div>
          <div className="flex justify-between">
            <span className="text-muted-foreground">Basket near highs</span>
            <span className={cn("font-medium tabular-nums", data.basket_breadth_pct >= 75 ? "text-orange-500" : "")}>
              {data.basket_breadth_pct.toFixed(0)}%
            </span>
          </div>
          {data.nvda_forward_pe != null && (
            <div className="flex justify-between">
              <span className="text-muted-foreground">NVDA fwd P/E</span>
              <span className={cn("font-medium tabular-nums", data.nvda_forward_pe >= 50 ? "text-orange-500" : "")}>
                {data.nvda_forward_pe.toFixed(0)}x
              </span>
            </div>
          )}
        </div>

        {/* Footer timestamp */}
        {asOf && (
          <p className="text-xs text-muted-foreground border-t pt-2 mt-1">
            Updated {asOf}
          </p>
        )}
      </CardContent>
    </Card>
  );
}
