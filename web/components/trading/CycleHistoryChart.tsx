"use client";

import { useEffect, useState } from "react";
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

export function CycleHistoryChart() {
  const [rows, setRows] = useState<HistoryRow[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      try {
        const res = await fetch("/api/ai-cycle");
        if (res.ok) {
          const json = await res.json();
          setRows(json.history ?? []);
        }
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

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

  const chartData = rows.map((r) => ({
    date: r.snapshot_date,
    cycle: r.cycle_score,
    heat: r.bubble_score,
    capex: r.hyperscaler_capex_yoy,
  }));

  return (
    <Card>
      <CardContent className="p-6">
        <p className="text-xs text-muted-foreground uppercase tracking-wide font-medium mb-1">
          Super-Cycle Over Time
        </p>
        <p className="text-xs text-muted-foreground mb-4">
          Cycle durability &amp; sector heat (0-100, left) vs hyperscaler capex YoY (%, right)
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
