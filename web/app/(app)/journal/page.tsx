"use client";

import { useEffect, useState } from "react";
import { createClient } from "@/lib/supabase/client";
import { JournalEntryCard } from "@/components/trading/journal-entry";
import { AboutMeSection } from "@/components/trading/about-me";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

export default function JournalPage() {
  const [entries, setEntries] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      const supabase = createClient();
      const { data } = await supabase
        .from("agent_journal")
        .select("*")
        .order("created_at", { ascending: false })
        .limit(50);
      setEntries(data ?? []);
      setLoading(false);
    }
    load();
  }, []);

  const filterEntries = (type: string | null) =>
    type ? entries.filter((e) => e.entry_type === type) : entries;

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="animate-pulse text-muted-foreground">Loading journal...</div>
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto p-6 space-y-6">
      <h1 className="text-2xl font-semibold">Agent Journal</h1>

      <Tabs defaultValue="about">
        <TabsList>
          <TabsTrigger value="about">About Me</TabsTrigger>
          <TabsTrigger value="all">All</TabsTrigger>
          <TabsTrigger value="research">Research</TabsTrigger>
          <TabsTrigger value="analysis">Analysis</TabsTrigger>
          <TabsTrigger value="trade">Trades</TabsTrigger>
          <TabsTrigger value="reflection">Reflections</TabsTrigger>
        </TabsList>

        {["all", "research", "analysis", "trade", "reflection"].map((tab) => (
          <TabsContent key={tab} value={tab} className="space-y-4">
            {filterEntries(tab === "all" ? null : tab).length === 0 ? (
              <p className="text-center text-muted-foreground py-8">No entries yet</p>
            ) : (
              filterEntries(tab === "all" ? null : tab).map((entry) => (
                <JournalEntryCard key={entry.id} entry={entry} />
              ))
            )}
          </TabsContent>
        ))}

        <TabsContent value="about" className="space-y-4">
          <AboutMeSection />
        </TabsContent>
      </Tabs>
    </div>
  );
}
