"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
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

interface HistoryRow {
  snapshot_date: string;
  cycle_score: number | null;
  bubble_score: number | null;
  hyperscaler_capex_yoy: number | null;
}

type Granularity = "daily" | "weekly" | "monthly";

const GRANULARITIES: { key: Granularity; label: string }[] = [
  { key: "daily", label: "Daily" },
  { key: "weekly", label: "Weekly" },
  { key: "monthly", label: "Monthly" },
];

// Above this span, daily points get crowded and the underlying signal (3-month
// trailing momentum + quarterly capex) is oversampled — default to a weekly roll-up.
const AUTO_WEEKLY_DAYS = 56;

const DAY_MS = 86_400_000;

/** ISO date (UTC) of the Monday that starts the week containing `date`. */
function weekStart(date: string): string {
  const dt = new Date(`${date}T00:00:00Z`);
  const dow = dt.getUTCDay(); // 0=Sun..6=Sat
  dt.setUTCDate(dt.getUTCDate() + (dow === 0 ? -6 : 1 - dow));
  return dt.toISOString().slice(0, 10);
}

function bucketKey(date: string, g: Granularity): string {
  if (g === "weekly") return weekStart(date);
  if (g === "monthly") return date.slice(0, 7); // YYYY-MM
  return date;
}

interface Point {
  date: string;
  cycle: number | null;
  heat: number | null;
  capex: number | null;
}

/** Average non-null values; null when a bucket has none. */
function avg(nums: (number | null)[]): number | null {
  const vals = nums.filter((n): n is number => n != null);
  if (vals.length === 0) return null;
  return vals.reduce((a, b) => a + b, 0) / vals.length;
}

function aggregate(rows: HistoryRow[], g: Granularity): Point[] {
  if (g === "daily") {
    return rows.map((r) => ({
      date: r.snapshot_date,
      cycle: r.cycle_score,
      heat: r.bubble_score,
      capex: r.hyperscaler_capex_yoy,
    }));
  }
  // rows arrive ascending by date, so Map insertion order stays chronological.
  const groups = new Map<string, HistoryRow[]>();
  for (const r of rows) {
    const k = bucketKey(r.snapshot_date, g);
    const arr = groups.get(k);
    if (arr) arr.push(r);
    else groups.set(k, [r]);
  }
  return Array.from(groups.values()).map((bucket) => ({
    // Label each period by its most recent day so the right edge stays "now".
    date: bucket[bucket.length - 1].snapshot_date,
    cycle: avg(bucket.map((x) => x.cycle_score)),
    heat: avg(bucket.map((x) => x.bubble_score)),
    capex: avg(bucket.map((x) => x.hyperscaler_capex_yoy)),
  }));
}

export function CycleHistoryChart() {
  const [rows, setRows] = useState<HistoryRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [granularity, setGranularity] = useState<Granularity>("daily");
  const autoDefaulted = useRef(false);

  useEffect(() => {
    async function load() {
      try {
        const res = await fetch("/api/ai-cycle");
        if (res.ok) {
          const json = await res.json();
          const hist: HistoryRow[] = json.history ?? [];
          setRows(hist);
          // One-time: for a long span, weekly reads cleaner than daily. The user
          // can still switch back; we only auto-pick before any manual choice.
          if (!autoDefaulted.current && hist.length >= 2) {
            const spanDays =
              (new Date(hist[hist.length - 1].snapshot_date).getTime() -
                new Date(hist[0].snapshot_date).getTime()) /
              DAY_MS;
            if (spanDays > AUTO_WEEKLY_DAYS) setGranularity("weekly");
            autoDefaulted.current = true;
          }
        }
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  const chartData = useMemo(() => aggregate(rows, granularity), [rows, granularity]);

  if (loading) {
    return (
      <Card>
        <CardContent className="p-6">
          <Skeleton className="h-4 w-48 mb-4" />
          <Skeleton className="h-72 w-full" />
        </CardContent>
      </Card>
    );
  }

  const aggLabel =
    granularity === "daily" ? "" : ` · ${granularity} avg`;

  return (
    <Card>
      <CardContent className="p-6">
        <div className="flex items-start justify-between gap-4 mb-1">
          <p className="text-xs text-muted-foreground uppercase tracking-wide font-medium">
            Super-Cycle Over Time
          </p>
          <div className="flex rounded-md border border-border overflow-hidden shrink-0">
            {GRANULARITIES.map((g) => (
              <button
                key={g.key}
                type="button"
                onClick={() => {
                  autoDefaulted.current = true; // respect the manual choice
                  setGranularity(g.key);
                }}
                className={`px-2 py-0.5 text-xs transition-colors ${
                  granularity === g.key
                    ? "bg-foreground text-background"
                    : "text-muted-foreground hover:bg-muted"
                }`}
              >
                {g.label}
              </button>
            ))}
          </div>
        </div>
        <p className="text-xs text-muted-foreground mb-4">
          Cycle durability &amp; sector heat (0-100, left) vs hyperscaler capex YoY (%, right)
          {aggLabel}
        </p>
        {chartData.length === 0 ? (
          <div className="h-72 flex items-center justify-center text-sm text-muted-foreground">
            No history yet — the daily AI cycle refresh builds this over time.
          </div>
        ) : (
          <div className="h-72">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={chartData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                <XAxis
                  dataKey="date"
                  tickFormatter={(v) => String(v).slice(5)}
                  interval="preserveStartEnd"
                  minTickGap={40}
                  fontSize={10}
                />
                <YAxis yAxisId="score" domain={[0, 100]} fontSize={10} />
                <YAxis
                  yAxisId="capex"
                  orientation="right"
                  tickFormatter={(v) => `${v}%`}
                  fontSize={10}
                />
                <Tooltip
                  formatter={(v, name) =>
                    typeof v === "number"
                      ? name === "Capex YoY"
                        ? `${v.toFixed(0)}%`
                        : v.toFixed(0)
                      : String(v ?? "")
                  }
                />
                <Legend wrapperStyle={{ fontSize: "12px" }} />
                <Line
                  yAxisId="score"
                  type="monotone"
                  dataKey="cycle"
                  name="Cycle Durability"
                  stroke="#16a34a"
                  strokeWidth={2}
                  dot={false}
                  connectNulls
                />
                <Line
                  yAxisId="score"
                  type="monotone"
                  dataKey="heat"
                  name="Sector Heat"
                  stroke="#f59e0b"
                  strokeWidth={1.5}
                  dot={false}
                  connectNulls
                />
                <Line
                  yAxisId="capex"
                  type="monotone"
                  dataKey="capex"
                  name="Capex YoY"
                  stroke="#6366f1"
                  strokeWidth={1.5}
                  strokeDasharray="4 2"
                  dot={false}
                  connectNulls
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
