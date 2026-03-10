"use client";

import { useEffect, useState } from "react";
import { createClient } from "@/lib/supabase/client";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

interface PerformanceData {
  overallReturn: number;
  filledTrades: number;
  stage: string;
}

export function PerformanceCard() {
  const [data, setData] = useState<PerformanceData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      const supabase = createClient();

      const [stageRes, tradesRes] = await Promise.all([
        supabase
          .from("agent_memory")
          .select("value")
          .eq("key", "agent_stage")
          .single(),
        supabase
          .from("trades")
          .select("id", { count: "exact", head: true })
          .eq("status", "filled"),
      ]);

      const rawStage = stageRes.data?.value;
      const stage =
        typeof rawStage === "string"
          ? rawStage
          : rawStage?.stage ?? "explore";

      setData({
        overallReturn: 0,
        filledTrades: tradesRes.count ?? 0,
        stage,
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

  const { overallReturn, filledTrades, stage } = data;
  const sign = overallReturn > 0 ? "+" : "";
  const formatted = `${sign}${overallReturn.toFixed(2)}%`;

  return (
    <Card>
      <CardContent className="p-8 flex flex-col items-center gap-1">
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
        <p className="text-sm text-muted-foreground">Overall Return</p>
        <p className="text-xs text-muted-foreground/70 mt-3">
          {filledTrades} trade{filledTrades !== 1 ? "s" : ""} · {capitalize(stage)} stage
        </p>
      </CardContent>
    </Card>
  );
}

const STAGES = ["explore", "balanced", "exploit"] as const;

const STAGE_DESCRIPTIONS: Record<string, string> = {
  explore: "Screening stocks and building a watchlist before committing capital.",
  balanced: "Actively researching and trading when setups align.",
  exploit: "Managing positions and harvesting returns.",
};

interface StageData {
  stage: string;
  watchlist_profiles: number;
  cycles_completed: number;
  total_trades: number;
}

export function LifecycleCard() {
  const [data, setData] = useState<StageData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      const supabase = createClient();
      const res = await supabase
        .from("agent_memory")
        .select("value")
        .eq("key", "agent_stage")
        .single();

      const raw = res.data?.value;
      setData({
        stage: raw?.stage ?? "explore",
        watchlist_profiles: raw?.watchlist_profiles ?? 0,
        cycles_completed: raw?.cycles_completed ?? 0,
        total_trades: raw?.total_trades ?? 0,
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

  const currentIndex = STAGES.indexOf(data.stage as typeof STAGES[number]);
  const safeIndex = currentIndex === -1 ? 0 : currentIndex;

  // Progress stat for current stage
  let progressLabel: string;
  let progressValue: string;
  if (data.stage === "explore") {
    const profilePct = Math.min(data.watchlist_profiles / 15, 1);
    const cyclePct = Math.min(data.cycles_completed / 30, 1);
    const avg = ((profilePct + cyclePct) / 2) * 100;
    progressLabel = "Progress to Balanced";
    progressValue = `${Math.round(avg)}%`;
  } else if (data.stage === "balanced") {
    const tradePct = Math.min(data.total_trades / 10, 1);
    const profilePct = Math.min(data.watchlist_profiles / 25, 1);
    const avg = ((tradePct + profilePct) / 2) * 100;
    progressLabel = "Progress to Exploit";
    progressValue = `${Math.round(avg)}%`;
  } else {
    progressLabel = "Lifecycle";
    progressValue = "Complete";
  }

  return (
    <Card>
      <CardContent className="p-6 space-y-4">
        <div className="flex items-center justify-between">
          <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            Lifecycle
          </p>
          <p className="text-xs text-muted-foreground">
            <span className="font-medium text-foreground">{progressValue}</span>{" "}
            {data.stage !== "exploit" && (
              <span className="text-muted-foreground/70">{progressLabel.replace("Progress to ", "→ ")}</span>
            )}
          </p>
        </div>

        {/* 3-segment progress bar */}
        <div className="flex gap-1">
          {STAGES.map((s, i) => (
            <div
              key={s}
              className={cn(
                "h-2 flex-1 rounded-full",
                i <= safeIndex ? "bg-primary" : "bg-muted"
              )}
            />
          ))}
        </div>

        {/* Stage labels */}
        <div className="flex justify-between text-[10px] text-muted-foreground/70">
          {STAGES.map((s, i) => (
            <span
              key={s}
              className={cn(
                i === safeIndex && "text-foreground font-medium"
              )}
            >
              {capitalize(s)}
            </span>
          ))}
        </div>

        {/* Description */}
        <p className="text-xs text-muted-foreground leading-relaxed">
          {STAGE_DESCRIPTIONS[data.stage] ?? STAGE_DESCRIPTIONS.explore}
        </p>

        {/* Current stage stats */}
        {data.stage === "explore" && (
          <div className="flex gap-4 text-xs text-muted-foreground pt-1">
            <span>{data.watchlist_profiles}/15 profiles</span>
            <span>{data.cycles_completed}/30 cycles</span>
          </div>
        )}
        {data.stage === "balanced" && (
          <div className="flex gap-4 text-xs text-muted-foreground pt-1">
            <span>{data.total_trades}/10 trades</span>
            <span>{data.watchlist_profiles}/25 profiles</span>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function capitalize(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1);
}
