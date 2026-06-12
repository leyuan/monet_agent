"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { createClient } from "@/lib/supabase/client";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

interface Summary {
  cycleScore: number | null;
  phaseLabel: string | null;
  phase: string | null;
  capexDir: string | null;
  hyperYoy: number | null;
  heatScore: number | null;
  heatLevel: string | null;
  asOf: string | null;
}

function phaseColor(phase: string | null) {
  switch (phase) {
    case "full_build": return "text-green-500";
    case "expanding": return "text-emerald-500";
    case "maturing": return "text-yellow-500";
    case "cooling": return "text-red-500";
    default: return "text-muted-foreground";
  }
}

function capexColor(dir: string | null) {
  switch (dir) {
    case "accelerating": return "text-green-500";
    case "stable": return "text-yellow-500";
    case "decelerating": return "text-red-500";
    default: return "text-muted-foreground";
  }
}

function heatColor(level: string | null) {
  switch (level) {
    case "low": return "text-green-500";
    case "moderate": return "text-yellow-500";
    case "elevated": return "text-orange-500";
    case "high": return "text-red-500";
    default: return "text-muted-foreground";
  }
}

const titleCase = (s: string | null) => (s ? s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()) : "—");

function Stat({ label, value, sub, color }: { label: string; value: string; sub: string; color: string }) {
  return (
    <div className="flex flex-col">
      <span className="text-[11px] uppercase tracking-wide text-muted-foreground/70 font-medium">{label}</span>
      <span className={cn("text-2xl font-bold tabular-nums leading-tight mt-0.5", color)}>{value}</span>
      <span className={cn("text-xs font-medium", color)}>{sub}</span>
    </div>
  );
}

export function AiSuperCycleCard() {
  const [data, setData] = useState<Summary | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      const supabase = createClient();
      const [dur, bub, cap] = await Promise.all([
        supabase.from("agent_memory").select("value").eq("key", "ai_cycle_durability").maybeSingle(),
        supabase.from("agent_memory").select("value").eq("key", "ai_bubble_risk").maybeSingle(),
        supabase.from("agent_memory").select("value").eq("key", "ai_capex_tracker").maybeSingle(),
      ]);
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const d = (dur.data?.value ?? {}) as any;
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const b = (bub.data?.value ?? {}) as any;
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const c = (cap.data?.value ?? {}) as any;
      setData({
        cycleScore: d.score ?? null,
        phaseLabel: d.phase_label ?? null,
        phase: d.phase ?? null,
        capexDir: c.guidance_direction ?? null,
        hyperYoy: c.hyperscaler_total_yoy ?? null,
        heatScore: b.score ?? null,
        heatLevel: b.level ?? null,
        asOf: d.as_of ?? c.as_of ?? b.as_of ?? null,
      });
      setLoading(false);
    }
    load();
  }, []);

  if (loading) {
    return (
      <Card>
        <CardContent className="p-6 flex flex-col gap-3">
          <Skeleton className="h-4 w-40" />
          <div className="grid grid-cols-3 gap-4">
            <Skeleton className="h-14" /><Skeleton className="h-14" /><Skeleton className="h-14" />
          </div>
        </CardContent>
      </Card>
    );
  }

  const yoy = data?.hyperYoy;
  const yoyStr = yoy === null || yoy === undefined ? "—" : `${yoy >= 0 ? "+" : ""}${yoy.toFixed(0)}%`;

  return (
    <Card>
      <CardContent className="p-6 flex flex-col gap-4">
        <div className="flex items-center justify-between">
          <p className="text-xs text-muted-foreground uppercase tracking-wide font-medium">AI Super-Cycle</p>
          <Link href="/ai-cycle" className="text-xs text-muted-foreground hover:text-foreground transition-colors">
            Details →
          </Link>
        </div>
        <div className="grid grid-cols-3 gap-4">
          <Stat
            label="Cycle"
            value={data?.cycleScore != null ? String(data.cycleScore) : "—"}
            sub={titleCase(data?.phaseLabel ?? data?.phase ?? null)}
            color={phaseColor(data?.phase ?? null)}
          />
          <Stat
            label="Capex YoY"
            value={yoyStr}
            sub={titleCase(data?.capexDir ?? null)}
            color={capexColor(data?.capexDir ?? null)}
          />
          <Stat
            label="Sector Heat"
            value={data?.heatScore != null ? String(data.heatScore) : "—"}
            sub={titleCase(data?.heatLevel ?? null)}
            color={heatColor(data?.heatLevel ?? null)}
          />
        </div>
      </CardContent>
    </Card>
  );
}
