"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { createClient } from "@/lib/supabase/client";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";

interface StockRow {
  symbol: string;
  status: string;
  composite_score: number | null;
  momentum_score: number | null;
  quality_score: number | null;
  value_score: number | null;
  eps_revision_score: number | null;
  earningsPattern: string | null;
  beatStreak: string | null;
  avgSurprise: number | null;
  nextEarnings: string | null;
  catalyst: string | null;
  lastAnalyzed: string | null;
}

const patternColors: Record<string, { bg: string; text: string }> = {
  reliable_beater: { bg: "bg-emerald-500/10", text: "text-emerald-600 dark:text-emerald-400" },
  systematic_underestimation: { bg: "bg-emerald-500/10", text: "text-emerald-600 dark:text-emerald-400" },
  volatile: { bg: "bg-amber-500/10", text: "text-amber-600 dark:text-amber-400" },
  declining: { bg: "bg-red-500/10", text: "text-red-600 dark:text-red-400" },
  turnaround: { bg: "bg-blue-500/10", text: "text-blue-600 dark:text-blue-400" },
};

const statusColors: Record<string, string> = {
  holding: "text-emerald-600 dark:text-emerald-400",
  watching: "text-amber-600 dark:text-amber-400",
};

function ScoreCell({ score, label }: { score: number | null; label?: string }) {
  if (score == null) return <span className="text-muted-foreground">—</span>;
  return (
    <span
      className={cn(
        "tabular-nums text-xs font-medium",
        score >= 80 ? "text-emerald-600 dark:text-emerald-400" :
        score >= 60 ? "text-foreground" :
        "text-muted-foreground",
      )}
      title={label}
    >
      {score.toFixed(0)}
    </span>
  );
}

export default function StockProfilesPage() {
  const [rows, setRows] = useState<StockRow[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      const supabase = createClient();

      // Fetch all data in parallel
      const [stocksRes, earningsRes, upcomingRes, catalystRes] = await Promise.all([
        supabase
          .from("agent_memory")
          .select("key, value, updated_at")
          .like("key", "stock:%")
          .order("updated_at", { ascending: false }),
        supabase
          .from("agent_memory")
          .select("key, value")
          .like("key", "earnings_profile:%"),
        supabase
          .from("agent_memory")
          .select("value")
          .eq("key", "upcoming_earnings")
          .maybeSingle(),
        supabase
          .from("agent_memory")
          .select("value")
          .eq("key", "upcoming_catalysts")
          .maybeSingle(),
      ]);

      // Build lookup maps
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const earningsMap: Record<string, any> = {};
      for (const row of earningsRes.data ?? []) {
        const sym = row.key.replace("earnings_profile:", "");
        earningsMap[sym] = row.value;
      }

      const earningsDateMap: Record<string, string> = {};
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      for (const e of (upcomingRes.data?.value as any)?.events ?? []) {
        if (e.symbol && e.date) earningsDateMap[e.symbol] = e.date;
      }

      const catalystMap: Record<string, string> = {};
      const today = new Date().toISOString().slice(0, 10);
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      for (const e of (catalystRes.data?.value as any)?.events ?? []) {
        if (e.symbol && e.date && e.date >= today) {
          // Keep the soonest catalyst per symbol
          if (!catalystMap[e.symbol] || e.date < catalystMap[e.symbol]) {
            catalystMap[e.symbol] = `${e.date.slice(5)} ${e.title ?? ""}`.trim();
          }
        }
      }

      // Build rows
      const result: StockRow[] = [];
      for (const row of stocksRes.data ?? []) {
        const sym = row.key.replace("stock:", "");
        if (!sym || sym.includes(":")) continue;
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const v = row.value as any;
        const ep = earningsMap[sym];

        result.push({
          symbol: sym,
          status: v?.status ?? "unknown",
          composite_score: v?.composite_score ?? null,
          momentum_score: v?.momentum_score ?? null,
          quality_score: v?.quality_score ?? null,
          value_score: v?.value_score ?? null,
          eps_revision_score: v?.eps_revision_score ?? null,
          earningsPattern: ep?.pattern ?? null,
          beatStreak: ep ? `${ep.beat_streak ?? 0}/${ep.quarters_tracked ?? 0}` : null,
          avgSurprise: ep?.avg_surprise_pct ?? null,
          nextEarnings: earningsDateMap[sym] ?? null,
          catalyst: catalystMap[sym] ?? null,
          lastAnalyzed: v?.last_analyzed ?? row.updated_at,
        });
      }

      // Sort: holding first, then by composite score desc
      result.sort((a, b) => {
        if (a.status === "holding" && b.status !== "holding") return -1;
        if (a.status !== "holding" && b.status === "holding") return 1;
        return (b.composite_score ?? 0) - (a.composite_score ?? 0);
      });

      setRows(result);
      setLoading(false);
    }
    load();
  }, []);

  if (loading) {
    return (
      <div className="h-full overflow-y-auto p-6 space-y-4">
        <h1 className="text-lg font-semibold">Stock Profiles</h1>
        <div className="space-y-2">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="h-12 animate-pulse rounded-lg bg-muted" />
          ))}
        </div>
      </div>
    );
  }

  const holdCount = rows.filter((r) => r.status === "holding").length;
  const watchCount = rows.filter((r) => r.status === "watching").length;
  const profiledCount = rows.filter((r) => r.earningsPattern).length;

  return (
    <div className="h-full overflow-y-auto p-6 space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold">Stock Profiles</h1>
        <div className="flex items-center gap-3 text-xs text-muted-foreground">
          <span>{holdCount} holding</span>
          <span>{watchCount} watching</span>
          <span>{profiledCount}/{rows.length} earnings profiled</span>
        </div>
      </div>

      <Card>
        <CardContent className="p-0">
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b text-muted-foreground">
                  <th className="py-2.5 px-3 text-left font-medium">Symbol</th>
                  <th className="py-2.5 px-2 text-left font-medium">Status</th>
                  <th className="py-2.5 px-2 text-right font-medium" title="Composite">Comp</th>
                  <th className="py-2.5 px-2 text-right font-medium hidden sm:table-cell" title="Momentum">M</th>
                  <th className="py-2.5 px-2 text-right font-medium hidden sm:table-cell" title="Quality">Q</th>
                  <th className="py-2.5 px-2 text-right font-medium hidden sm:table-cell" title="Value">V</th>
                  <th className="py-2.5 px-2 text-right font-medium hidden sm:table-cell" title="EPS Revision">E</th>
                  <th className="py-2.5 px-2 text-left font-medium hidden md:table-cell">Earnings</th>
                  <th className="py-2.5 px-2 text-left font-medium hidden lg:table-cell">Catalyst</th>
                  <th className="py-2.5 px-2 text-right font-medium hidden md:table-cell">Analyzed</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => {
                  const patternStyle = row.earningsPattern
                    ? patternColors[row.earningsPattern] ?? { bg: "bg-muted", text: "text-muted-foreground" }
                    : null;

                  return (
                    <tr key={row.symbol} className="border-b last:border-0 hover:bg-muted/50 transition-colors">
                      <td className="py-2.5 px-3">
                        <Link
                          href={`/earnings/${row.symbol}`}
                          className="font-mono font-semibold text-sm text-primary hover:underline"
                        >
                          {row.symbol}
                        </Link>
                      </td>
                      <td className="py-2.5 px-2">
                        <span className={cn("text-xs font-medium capitalize", statusColors[row.status] ?? "text-muted-foreground")}>
                          {row.status}
                        </span>
                      </td>
                      <td className="py-2.5 px-2 text-right">
                        {row.composite_score != null ? (
                          <span className={cn(
                            "tabular-nums text-sm font-bold",
                            row.composite_score >= 80 ? "text-emerald-600 dark:text-emerald-400" :
                            row.composite_score >= 70 ? "text-foreground" :
                            "text-muted-foreground",
                          )}>
                            {row.composite_score.toFixed(1)}
                          </span>
                        ) : (
                          <span className="text-muted-foreground">—</span>
                        )}
                      </td>
                      <td className="py-2.5 px-2 text-right hidden sm:table-cell">
                        <ScoreCell score={row.momentum_score} label="Momentum" />
                      </td>
                      <td className="py-2.5 px-2 text-right hidden sm:table-cell">
                        <ScoreCell score={row.quality_score} label="Quality" />
                      </td>
                      <td className="py-2.5 px-2 text-right hidden sm:table-cell">
                        <ScoreCell score={row.value_score} label="Value" />
                      </td>
                      <td className="py-2.5 px-2 text-right hidden sm:table-cell">
                        <ScoreCell score={row.eps_revision_score} label="EPS Revision" />
                      </td>
                      <td className="py-2.5 px-2 hidden md:table-cell">
                        <div className="flex items-center gap-1.5 flex-wrap">
                          {patternStyle ? (
                            <span className={cn("rounded-full px-1.5 py-0.5 text-[10px] font-medium", patternStyle.bg, patternStyle.text)}>
                              {row.earningsPattern!.replace(/_/g, " ")}
                            </span>
                          ) : (
                            <span className="text-[10px] text-muted-foreground">no profile</span>
                          )}
                          {row.beatStreak && (
                            <span className="text-[10px] text-muted-foreground">{row.beatStreak}</span>
                          )}
                          {row.nextEarnings && (
                            <span className="text-[10px] text-orange-600 dark:text-orange-400 font-medium">
                              {row.nextEarnings.slice(5)}
                            </span>
                          )}
                        </div>
                      </td>
                      <td className="py-2.5 px-2 hidden lg:table-cell">
                        {row.catalyst ? (
                          <span className="text-[10px] text-purple-600 dark:text-purple-400 truncate block max-w-[180px]">
                            {row.catalyst}
                          </span>
                        ) : (
                          <span className="text-[10px] text-muted-foreground">—</span>
                        )}
                      </td>
                      <td className="py-2.5 px-2 text-right hidden md:table-cell">
                        {row.lastAnalyzed ? (
                          <span className="text-[10px] text-muted-foreground">
                            {new Date(row.lastAnalyzed).toLocaleDateString("en-US", { month: "short", day: "numeric" })}
                          </span>
                        ) : (
                          <span className="text-[10px] text-muted-foreground">—</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>

      <p className="text-[10px] text-muted-foreground text-center">
        Click any symbol for full company profile, factor scores, earnings history, and decision timeline.
      </p>
    </div>
  );
}
