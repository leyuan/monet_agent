"use client";

import { useEffect, useState } from "react";
import { createClient } from "@/lib/supabase/client";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";

interface ActivityItem {
  id: string;
  type: "trade" | "journal" | "memory";
  title: string;
  description: string;
  timestamp: string;
  symbols?: string[];
}

export default function ActivityPage() {
  const [activities, setActivities] = useState<ActivityItem[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      const supabase = createClient();

      const [journalRes, tradesRes] = await Promise.all([
        supabase
          .from("agent_journal")
          .select("id, entry_type, title, content, symbols, created_at")
          .order("created_at", { ascending: false })
          .limit(30),
        supabase
          .from("trades")
          .select("id, symbol, side, quantity, status, thesis, created_at")
          .order("created_at", { ascending: false })
          .limit(30),
      ]);

      const items: ActivityItem[] = [];

      for (const j of journalRes.data ?? []) {
        items.push({
          id: `j-${j.id}`,
          type: "journal",
          title: `[${j.entry_type}] ${j.title}`,
          description: j.content.slice(0, 200),
          timestamp: j.created_at,
          symbols: j.symbols,
        });
      }

      for (const t of tradesRes.data ?? []) {
        items.push({
          id: `t-${t.id}`,
          type: "trade",
          title: `${t.side.toUpperCase()} ${t.quantity} ${t.symbol}`,
          description: t.thesis || `Status: ${t.status}`,
          timestamp: t.created_at,
          symbols: [t.symbol],
        });
      }

      items.sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime());
      setActivities(items);
      setLoading(false);
    }
    load();
  }, []);

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="animate-pulse text-muted-foreground">Loading activity...</div>
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto p-6 space-y-6">
      <h1 className="text-2xl font-semibold">Activity Feed</h1>

      {activities.length === 0 ? (
        <p className="text-center text-muted-foreground py-8">
          No activity yet. The agent will start logging activity after its first autonomous loop.
        </p>
      ) : (
        <div className="space-y-3">
          {activities.map((item) => {
            const date = new Date(item.timestamp).toLocaleDateString("en-US", {
              month: "short",
              day: "numeric",
              hour: "2-digit",
              minute: "2-digit",
            });

            return (
              <Card key={item.id}>
                <CardContent className="p-4">
                  <div className="flex items-start justify-between gap-4">
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span className={cn(
                          "rounded-full px-2 py-0.5 text-xs font-medium",
                          item.type === "trade"
                            ? "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200"
                            : "bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200",
                        )}>
                          {item.type}
                        </span>
                        <span className="font-medium text-sm">{item.title}</span>
                      </div>
                      <p className="mt-1 text-sm text-muted-foreground line-clamp-2">
                        {item.description}
                      </p>
                      {item.symbols && item.symbols.length > 0 && (
                        <div className="mt-1 flex gap-1">
                          {item.symbols.map((s) => (
                            <span key={s} className="rounded bg-muted px-1.5 py-0.5 text-xs font-mono">{s}</span>
                          ))}
                        </div>
                      )}
                    </div>
                    <span className="shrink-0 text-xs text-muted-foreground">{date}</span>
                  </div>
                </CardContent>
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}
