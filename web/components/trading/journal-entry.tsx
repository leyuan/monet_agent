"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

interface JournalEntry {
  id: string;
  entry_type: string;
  title: string;
  content: string;
  symbols: string[];
  created_at: string;
}

const typeColors: Record<string, string> = {
  research: "bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200",
  analysis: "bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-200",
  trade: "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200",
  reflection: "bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-200",
  market_scan: "bg-gray-100 text-gray-800 dark:bg-gray-800 dark:text-gray-200",
};

export function JournalEntryCard({ entry }: { entry: JournalEntry }) {
  const colorClass = typeColors[entry.entry_type] ?? typeColors.market_scan;
  const date = new Date(entry.created_at).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${colorClass}`}>
              {entry.entry_type}
            </span>
            <CardTitle className="text-base">{entry.title}</CardTitle>
          </div>
          <span className="text-xs text-muted-foreground">{date}</span>
        </div>
        {entry.symbols.length > 0 && (
          <div className="flex gap-1 pt-1">
            {entry.symbols.map((s) => (
              <span key={s} className="rounded bg-muted px-1.5 py-0.5 text-xs font-mono">
                {s}
              </span>
            ))}
          </div>
        )}
      </CardHeader>
      <CardContent>
        <div className="prose prose-sm dark:prose-invert max-w-none whitespace-pre-wrap">
          {entry.content}
        </div>
      </CardContent>
    </Card>
  );
}
