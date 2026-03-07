"use client";

import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { createClient } from "@/lib/supabase/client";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

interface MemoryRow {
  key: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  value: any;
}

interface WatchlistRow {
  id: string;
  symbol: string;
  thesis: string;
  target_entry: number | null;
  target_exit: number | null;
  created_at: string;
}

interface JournalEntry {
  id: string;
  title: string;
  content: string;
  created_at: string;
}

const MEMORY_KEYS = [
  "strategy",
  "risk_appetite",
  "market_outlook",
  "agent_stage",
  "weekly_priorities",
];

function SectionSkeleton() {
  return (
    <Card>
      <CardHeader>
        <Skeleton className="h-5 w-40" />
      </CardHeader>
      <CardContent className="space-y-2">
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-3/4" />
        <Skeleton className="h-4 w-5/6" />
      </CardContent>
    </Card>
  );
}

/** Convert a JSONB memory value into a readable markdown string. */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
function formatMemoryValue(value: any): string {
  if (typeof value === "string") return value;
  if (value == null) return "";

  // If it has a "summary" field, lead with that
  const parts: string[] = [];
  if (value.summary) parts.push(value.summary);

  for (const [k, v] of Object.entries(value)) {
    if (k === "summary" || k === "last_updated" || k === "validated") continue;
    if (Array.isArray(v)) {
      parts.push(`**${k.replace(/_/g, " ")}**: ${v.join(", ")}`);
    } else if (typeof v === "object" && v !== null) {
      // Nested object — format as sub-items
      const sub = Object.entries(v)
        .map(([sk, sv]) => `${sk.replace(/_/g, " ")}: ${sv}`)
        .join("; ");
      parts.push(`**${k.replace(/_/g, " ")}**: ${sub}`);
    } else if (typeof v === "string" || typeof v === "number") {
      parts.push(`**${k.replace(/_/g, " ")}**: ${v}`);
    }
  }
  return parts.join("\n\n");
}

function MemorySection({ title, content }: { title: string; content: unknown }) {
  if (!content) return null;
  const text = formatMemoryValue(content);
  if (!text) return null;
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-lg">{title}</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="journal-prose max-w-none text-sm">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
        </div>
      </CardContent>
    </Card>
  );
}

const stageLabels: Record<string, { label: string; color: string }> = {
  explore: {
    label: "Explore",
    color: "bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200",
  },
  balanced: {
    label: "Balanced",
    color: "bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-200",
  },
  exploit: {
    label: "Exploit",
    color: "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200",
  },
};

export function AboutMeSection() {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [memories, setMemories] = useState<Record<string, any>>({});
  const [watchlist, setWatchlist] = useState<WatchlistRow[]>([]);
  const [latestReflection, setLatestReflection] = useState<JournalEntry | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      const supabase = createClient();

      const [memRes, watchRes, reflRes] = await Promise.all([
        supabase
          .from("agent_memory")
          .select("key, value")
          .in("key", MEMORY_KEYS),
        supabase
          .from("watchlist")
          .select("*")
          .order("created_at", { ascending: false }),
        supabase
          .from("agent_journal")
          .select("id, title, content, created_at")
          .eq("entry_type", "reflection")
          .order("created_at", { ascending: false })
          .limit(1),
      ]);

      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const memMap: Record<string, any> = {};
      for (const row of (memRes.data ?? []) as MemoryRow[]) {
        memMap[row.key] = row.value;
      }
      setMemories(memMap);
      setWatchlist((watchRes.data ?? []) as WatchlistRow[]);
      setLatestReflection(
        (reflRes.data?.[0] as JournalEntry | undefined) ?? null,
      );
      setLoading(false);
    }
    load();
  }, []);

  if (loading) {
    return (
      <div className="space-y-4">
        {Array.from({ length: 5 }).map((_, i) => (
          <SectionSkeleton key={i} />
        ))}
      </div>
    );
  }

  const rawStage = memories.agent_stage;
  const stage = typeof rawStage === "string" ? rawStage : rawStage?.stage ?? rawStage?.value ?? null;
  const stageInfo = stage ? stageLabels[stage] ?? { label: stage, color: "bg-muted text-muted-foreground" } : null;

  return (
    <div className="space-y-4">
      <MemorySection title="Identity & Strategy" content={memories.strategy} />

      <MemorySection title="Investment Philosophy & Risk Appetite" content={memories.risk_appetite} />

      {stageInfo && (
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">Current Stage</CardTitle>
          </CardHeader>
          <CardContent>
            <span className={`inline-block rounded-full px-3 py-1 text-sm font-medium ${stageInfo.color}`}>
              {stageInfo.label}
            </span>
            <p className="mt-2 text-sm text-muted-foreground">
              {stage === "explore" && "Screening aggressively, building watchlist, rarely trading."}
              {stage === "balanced" && "Maintaining research cadence, actively checking price targets, trading at 0.6+ confidence."}
              {stage === "exploit" && "Focusing on position management, researching only for new catalysts."}
            </p>
          </CardContent>
        </Card>
      )}

      <MemorySection title="Market Outlook" content={memories.market_outlook} />

      <MemorySection title="Weekly Priorities" content={memories.weekly_priorities} />

      {watchlist.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">Watchlist</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-3">
              {watchlist.map((item) => (
                <div key={item.id} className="flex items-start gap-3 rounded-lg border p-3">
                  <span className="rounded bg-muted px-2 py-0.5 text-sm font-mono font-semibold">
                    {item.symbol}
                  </span>
                  <div className="flex-1 text-sm">
                    <p>{item.thesis}</p>
                    {(item.target_entry || item.target_exit) && (
                      <p className="mt-1 text-xs text-muted-foreground">
                        {item.target_entry && `Entry: $${item.target_entry}`}
                        {item.target_entry && item.target_exit && " | "}
                        {item.target_exit && `Exit: $${item.target_exit}`}
                      </p>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {latestReflection && (
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <CardTitle className="text-lg">Latest Reflection</CardTitle>
              <span className="text-xs text-muted-foreground">
                {new Date(latestReflection.created_at).toLocaleDateString("en-US", {
                  month: "short",
                  day: "numeric",
                  hour: "2-digit",
                  minute: "2-digit",
                })}
              </span>
            </div>
          </CardHeader>
          <CardContent>
            <p className="mb-2 font-medium text-sm">{latestReflection.title}</p>
            <div className="journal-prose max-w-none text-sm">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {latestReflection.content}
              </ReactMarkdown>
            </div>
          </CardContent>
        </Card>
      )}

      {!memories.strategy && !memories.risk_appetite && !memories.market_outlook && watchlist.length === 0 && !latestReflection && (
        <p className="text-center text-muted-foreground py-8">
          No data yet. Monet hasn&apos;t built its profile.
        </p>
      )}
    </div>
  );
}
