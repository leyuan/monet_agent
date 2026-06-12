"use client";

import { useEffect, useState } from "react";
import { createClient } from "@/lib/supabase/client";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

interface Signal {
  headline: string;
  source: string | null;
  url: string | null;
  date: string | null;
  category: string;
  direction: string | null;
  why: string | null;
}

interface SignalsData {
  net_read: string | null;
  signals: Signal[];
  as_of: string | null;
}

// category → label + pill colors
const CATEGORY: Record<string, { label: string; cls: string }> = {
  supply_tight: { label: "Supply Tight", cls: "bg-green-500/10 text-green-600 border-green-500/20" },
  capacity_adds: { label: "Capacity Adds", cls: "bg-green-500/10 text-green-600 border-green-500/20" },
  guidance_shift: { label: "Guidance", cls: "bg-blue-500/10 text-blue-600 border-blue-500/20" },
  financing_strain: { label: "Financing Strain", cls: "bg-amber-500/10 text-amber-600 border-amber-500/20" },
  demand_stress: { label: "Demand Stress", cls: "bg-red-500/10 text-red-600 border-red-500/20" },
};

function cat(c: string) {
  return CATEGORY[c] ?? { label: c.replace(/_/g, " "), cls: "bg-muted text-muted-foreground border-border" };
}

export function CycleSignalsCard() {
  const [data, setData] = useState<SignalsData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      const supabase = createClient();
      const { data: row } = await supabase
        .from("agent_memory")
        .select("value")
        .eq("key", "ai_cycle_signals")
        .maybeSingle();
      if (row?.value) setData(row.value as SignalsData);
      setLoading(false);
    }
    load();
  }, []);

  if (loading) {
    return (
      <Card>
        <CardContent className="p-6">
          <Skeleton className="h-4 w-40 mb-4" />
          <Skeleton className="h-16 w-full" />
        </CardContent>
      </Card>
    );
  }

  const asOf = data?.as_of
    ? new Date(data.as_of).toLocaleDateString("en-US", { month: "short", day: "numeric" })
    : null;
  const signals = data?.signals ?? [];

  return (
    <Card>
      <CardContent className="p-6">
        <div className="flex items-start justify-between gap-4 mb-2">
          <p className="text-xs text-muted-foreground uppercase tracking-wide font-medium">Cycle Signals</p>
          {asOf && <p className="text-[11px] text-muted-foreground/70">Monet&apos;s read · {asOf}</p>}
        </div>

        {data?.net_read && (
          <p className="text-sm text-foreground/90 leading-relaxed mb-4">{data.net_read}</p>
        )}

        {signals.length === 0 ? (
          <p className="text-sm text-muted-foreground">No signals captured yet — the daily AI cycle refresh populates this.</p>
        ) : (
          <ul className="divide-y">
            {signals.map((s, i) => {
              const c = cat(s.category);
              return (
                <li key={i} className="py-3 first:pt-0 last:pb-0 flex flex-col gap-1">
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex items-start gap-2 min-w-0">
                      <span className={cn("shrink-0 mt-0.5 rounded-full border px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide", c.cls)}>
                        {c.label}
                      </span>
                      <span className="text-sm font-medium leading-snug">
                        {s.url ? (
                          <a href={s.url} target="_blank" rel="noopener noreferrer" className="hover:underline">
                            {s.headline} <span className="text-muted-foreground/50">↗</span>
                          </a>
                        ) : (
                          s.headline
                        )}
                      </span>
                    </div>
                    {s.date && <span className="shrink-0 text-[11px] text-muted-foreground/60 tabular-nums">{s.date}</span>}
                  </div>
                  {s.why && (
                    <p className="text-xs text-muted-foreground leading-relaxed pl-1">
                      {s.why}
                      {s.source && <span className="text-muted-foreground/50"> — {s.source}</span>}
                    </p>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
