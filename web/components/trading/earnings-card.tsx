"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { createClient } from "@/lib/supabase/client";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";

interface EarningsProfile {
  symbol: string;
  pattern: string;
  beat_streak: number;
  quarters_tracked: number;
  avg_surprise_pct: number;
  key_metric: string;
  agent_insight: string;
  updated_at: string;
}

function parseProfile(key: string, value: unknown, updated_at: string): EarningsProfile | null {
  const symbol = key.replace("earnings_profile:", "");
  if (!symbol) return null;

  const v = value as Record<string, unknown> | undefined;
  if (!v) return null;

  return {
    symbol,
    pattern: (v.pattern as string) ?? "unknown",
    beat_streak: (v.beat_streak as number) ?? 0,
    quarters_tracked: (v.quarters_tracked as number) ?? 0,
    avg_surprise_pct: (v.avg_surprise_pct as number) ?? 0,
    key_metric: (v.key_metric as string) ?? "",
    agent_insight: (v.agent_insight as string) ?? "",
    updated_at,
  };
}

const patternColors: Record<string, { bg: string; text: string }> = {
  reliable_beater: { bg: "bg-emerald-500/10", text: "text-emerald-600 dark:text-emerald-400" },
  systematic_underestimation: { bg: "bg-emerald-500/10", text: "text-emerald-600 dark:text-emerald-400" },
  volatile: { bg: "bg-amber-500/10", text: "text-amber-600 dark:text-amber-400" },
  declining: { bg: "bg-red-500/10", text: "text-red-600 dark:text-red-400" },
};

function PatternBadge({ pattern }: { pattern: string }) {
  const colors = patternColors[pattern] ?? { bg: "bg-muted", text: "text-muted-foreground" };
  const label = pattern.replace(/_/g, " ");
  return (
    <span className={cn("inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium", colors.bg, colors.text)}>
      {label}
    </span>
  );
}

function EarningsRow({ profile }: { profile: EarningsProfile }) {
  const [expanded, setExpanded] = useState(false);
  const insight = profile.agent_insight;
  const truncated = insight.length > 120 ? insight.slice(0, 120) + "..." : insight;

  return (
    <div className="border-b last:border-0 px-4 py-3 space-y-1.5">
      <div className="flex items-center gap-2 flex-wrap">
        <Link href={`/earnings/${profile.symbol}`} className="font-mono font-semibold text-sm text-primary hover:underline">
          {profile.symbol}
        </Link>
        <PatternBadge pattern={profile.pattern} />
        <span className="text-xs text-muted-foreground">
          {profile.beat_streak}/{profile.quarters_tracked} beats
        </span>
        {profile.avg_surprise_pct !== 0 && (
          <span className={cn("text-xs font-medium", profile.avg_surprise_pct > 0 ? "text-emerald-600 dark:text-emerald-400" : "text-red-600 dark:text-red-400")}>
            avg {profile.avg_surprise_pct > 0 ? "+" : ""}{profile.avg_surprise_pct.toFixed(1)}%
          </span>
        )}
      </div>
      {profile.key_metric && (
        <p className="text-xs text-muted-foreground">
          <span className="font-medium text-foreground">Key:</span> {profile.key_metric}
        </p>
      )}
      {insight && (
        <p className="text-xs text-muted-foreground">
          <span className="font-medium text-foreground">Insight:</span>{" "}
          {expanded ? insight : truncated}
          {insight.length > 120 && (
            <button
              onClick={() => setExpanded(!expanded)}
              className="ml-1 text-xs text-primary hover:underline"
            >
              {expanded ? "less" : "more"}
            </button>
          )}
        </p>
      )}
    </div>
  );
}

export function EarningsIntelligenceCard() {
  const [profiles, setProfiles] = useState<EarningsProfile[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      const supabase = createClient();
      const { data } = await supabase
        .from("agent_memory")
        .select("key, value, updated_at")
        .like("key", "earnings_profile:%")
        .order("updated_at", { ascending: false })
        .limit(10);

      if (data) {
        const parsed = data
          .map((row) => parseProfile(row.key, row.value, row.updated_at))
          .filter(Boolean) as EarningsProfile[];
        setProfiles(parsed);
      }
      setLoading(false);
    }
    load();
  }, []);

  if (loading) {
    return (
      <div className="space-y-4">
        <h2 className="text-lg font-semibold">Earnings Intelligence</h2>
        <Card>
          <CardContent className="p-4">
            <div className="animate-pulse h-16 bg-muted rounded" />
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <h2 className="text-lg font-semibold">Earnings Intelligence</h2>
      <Card>
        {profiles.length === 0 ? (
          <CardContent className="p-4 text-center text-muted-foreground text-sm">
            No earnings profiles yet. Profiles build automatically as Monet tracks earnings for portfolio stocks.
          </CardContent>
        ) : (
          <CardContent className="p-0">
            {profiles.map((p) => (
              <EarningsRow key={p.symbol} profile={p} />
            ))}
          </CardContent>
        )}
      </Card>
    </div>
  );
}
