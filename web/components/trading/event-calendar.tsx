"use client";

import { useEffect, useState, useMemo } from "react";
import { createClient } from "@/lib/supabase/client";
import { ChevronLeft, ChevronRight } from "lucide-react";

type EventType = "earnings" | "activity" | "cron" | "catalyst";

interface CalendarEvent {
  symbol: string;
  date: string; // YYYY-MM-DD
  type: EventType;
  label?: string;
}

/** Convert a Date to YYYY-MM-DD in the browser's local timezone. */
function toLocalDateStr(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

/** Generate scheduled cron run dates for the next ~45 days. */
function generateCronEvents(): CalendarEvent[] {
  const events: CalendarEvent[] = [];
  const now = new Date();

  // Schedule: weekdays 10am, 1pm, 4pm ET; Sat 11am; Sun 11am
  const schedule = [
    { days: [1, 2, 3, 4, 5], hour: 10, label: "Morning Scout (10am)" },
    { days: [1, 2, 3, 4, 5], hour: 13, label: "Midday Dive (1pm)" },
    { days: [1, 2, 3, 4, 5], hour: 16, label: "EOD Execution (4pm)" },
    { days: [6], hour: 11, label: "Weekend Research (11am)" },
    { days: [0], hour: 11, label: "Weekly Review (11am)" },
  ];

  for (let d = 0; d < 45; d++) {
    const date = new Date(now);
    date.setDate(date.getDate() + d);
    const dow = date.getDay();

    for (const s of schedule) {
      if (!s.days.includes(dow)) continue;
      const run = new Date(date);
      run.setHours(s.hour, 0, 0, 0);
      // Skip past runs
      if (run <= now) continue;

      events.push({
        symbol: "",
        date: toLocalDateStr(run),
        type: "cron",
        label: s.label,
      });
    }
  }

  return events;
}

export function EventCalendar() {
  const [events, setEvents] = useState<CalendarEvent[]>([]);
  const [currentMonth, setCurrentMonth] = useState(() => {
    const now = new Date();
    return { year: now.getFullYear(), month: now.getMonth() };
  });
  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      const supabase = createClient();
      const allEvents: CalendarEvent[] = [];

      // 1a. Fetch upcoming earnings from agent_memory (persisted by earnings_calendar tool)
      const { data: earningsMem } = await supabase
        .from("agent_memory")
        .select("value")
        .eq("key", "upcoming_earnings")
        .maybeSingle();

      const earningsSymbolsSeen = new Set<string>();
      if (earningsMem?.value?.events) {
        for (const e of earningsMem.value.events) {
          if (e.date && e.symbol) {
            earningsSymbolsSeen.add(e.symbol);
            allEvents.push({
              symbol: e.symbol,
              date: e.date,
              type: "earnings",
              label: `${e.symbol} earnings${e.hour === "bmo" ? " (pre-market)" : e.hour === "amc" ? " (after close)" : ""}`,
            });
          }
        }
      }

      // 1b. Supplement with Yahoo Finance earnings dates for watchlist + portfolio
      //     symbols not already covered by the Finnhub memory key.
      const [{ data: watchlistRows }, { data: stockKeys }] = await Promise.all([
        supabase.from("watchlist").select("symbol"),
        supabase
          .from("agent_memory")
          .select("key")
          .like("key", "stock:%"),
      ]);

      const trackedSymbols = new Set<string>();
      for (const w of watchlistRows ?? []) trackedSymbols.add(w.symbol);
      for (const m of stockKeys ?? []) {
        const sym = m.key.replace("stock:", "");
        if (sym && !sym.includes(":")) trackedSymbols.add(sym);
      }

      const missing = [...trackedSymbols].filter(
        (s) => !earningsSymbolsSeen.has(s),
      );

      if (missing.length > 0) {
        try {
          const res = await fetch(
            `/api/earnings-dates?symbols=${missing.join(",")}`,
          );
          if (res.ok) {
            const { events: yahooEvents } = await res.json();
            for (const e of yahooEvents ?? []) {
              if (e.date && e.symbol && !earningsSymbolsSeen.has(e.symbol)) {
                earningsSymbolsSeen.add(e.symbol);
                allEvents.push({
                  symbol: e.symbol,
                  date: e.date,
                  type: "earnings",
                  label: `${e.symbol} earnings`,
                });
              }
            }
          }
        } catch {
          // Yahoo supplement is best-effort
        }
      }

      // 2. Fetch upcoming catalysts from agent_memory
      const { data: catalystMem } = await supabase
        .from("agent_memory")
        .select("value")
        .eq("key", "upcoming_catalysts")
        .maybeSingle();

      if (catalystMem?.value?.events) {
        for (const e of catalystMem.value.events) {
          if (e.date && e.symbol) {
            allEvents.push({
              symbol: e.symbol,
              date: e.date,
              type: "catalyst",
              label: `${e.symbol}: ${e.title ?? "Catalyst"}${e.significance ? ` (${e.significance})` : ""}`,
            });
          }
        }
      }

      // 3. Fetch recent journal entries as activity markers
      const { data: journals } = await supabase
        .from("agent_journal")
        .select("entry_type, title, symbols, created_at")
        .order("created_at", { ascending: false })
        .limit(30);

      for (const j of journals ?? []) {
        const dateStr = toLocalDateStr(new Date(j.created_at));
        allEvents.push({
          symbol: j.symbols?.[0] ?? "",
          date: dateStr,
          type: "activity",
          label: j.title,
        });
      }

      // 3. Generate upcoming cron schedule events
      allEvents.push(...generateCronEvents());

      setEvents(allEvents);
      setLoading(false);
    }
    load();
  }, []);

  // Group events by date string
  const eventsByDate = useMemo(() => {
    const map: Record<string, CalendarEvent[]> = {};
    for (const e of events) {
      (map[e.date] ??= []).push(e);
    }
    return map;
  }, [events]);

  // Calendar grid computation
  const { year, month } = currentMonth;
  const firstDay = new Date(year, month, 1);
  const lastDay = new Date(year, month + 1, 0);
  const startDow = firstDay.getDay(); // 0=Sun
  const daysInMonth = lastDay.getDate();
  const today = new Date();
  const todayStr = toLocalDateStr(today);

  const monthLabel = firstDay.toLocaleDateString("en-US", { month: "long", year: "numeric" });

  const prevMonth = () =>
    setCurrentMonth((m) => (m.month === 0 ? { year: m.year - 1, month: 11 } : { year: m.year, month: m.month - 1 }));
  const nextMonth = () =>
    setCurrentMonth((m) => (m.month === 11 ? { year: m.year + 1, month: 0 } : { year: m.year, month: m.month + 1 }));

  // Build grid cells
  const cells: { day: number | null; dateStr: string }[] = [];
  for (let i = 0; i < startDow; i++) cells.push({ day: null, dateStr: "" });
  for (let d = 1; d <= daysInMonth; d++) {
    const dateStr = `${year}-${String(month + 1).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
    cells.push({ day: d, dateStr });
  }

  // Events for selected date
  const selectedEvents = selectedDate ? eventsByDate[selectedDate] ?? [] : [];
  const earningsForSelected = selectedEvents.filter((e) => e.type === "earnings");
  const catalystForSelected = selectedEvents.filter((e) => e.type === "catalyst");
  const cronForSelected = selectedEvents.filter((e) => e.type === "cron");
  const activityForSelected = selectedEvents.filter((e) => e.type === "activity");

  if (loading) {
    return (
      <div className="p-3 space-y-2">
        <div className="h-4 w-20 animate-pulse rounded bg-accent" />
        <div className="grid grid-cols-7 gap-1">
          {Array.from({ length: 35 }).map((_, i) => (
            <div key={i} className="h-6 w-6 animate-pulse rounded bg-accent" />
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="p-3 text-xs select-none">
      {/* Month header */}
      <div className="flex items-center justify-between mb-2">
        <button onClick={prevMonth} className="p-0.5 rounded hover:bg-muted">
          <ChevronLeft className="size-3.5" />
        </button>
        <span className="font-semibold text-[11px]">{monthLabel}</span>
        <button onClick={nextMonth} className="p-0.5 rounded hover:bg-muted">
          <ChevronRight className="size-3.5" />
        </button>
      </div>

      {/* Day-of-week headers */}
      <div className="grid grid-cols-7 gap-0.5 mb-1">
        {["Su", "Mo", "Tu", "We", "Th", "Fr", "Sa"].map((d) => (
          <div key={d} className="text-center text-[9px] text-muted-foreground font-medium">
            {d}
          </div>
        ))}
      </div>

      {/* Calendar grid */}
      <div className="grid grid-cols-7 gap-0.5">
        {cells.map((cell, i) => {
          if (cell.day === null) return <div key={i} />;

          const dateEvents = eventsByDate[cell.dateStr];
          const hasEarnings = dateEvents?.some((e) => e.type === "earnings");
          const hasCatalyst = dateEvents?.some((e) => e.type === "catalyst");
          const hasActivity = dateEvents?.some((e) => e.type === "activity");
          const hasCron = dateEvents?.some((e) => e.type === "cron");
          const isToday = cell.dateStr === todayStr;
          const isSelected = cell.dateStr === selectedDate;

          return (
            <button
              key={i}
              onClick={() => setSelectedDate(isSelected ? null : cell.dateStr)}
              className={`
                relative flex flex-col items-center justify-center rounded h-7 w-full text-[10px] transition-colors
                ${isToday ? "font-bold" : ""}
                ${isSelected ? "bg-primary text-primary-foreground" : isToday ? "bg-muted font-bold" : "hover:bg-muted/60"}
              `}
            >
              {cell.day}
              {/* Event dots */}
              {(hasEarnings || hasCatalyst || hasActivity || hasCron) && (
                <div className="absolute bottom-0.5 flex gap-0.5">
                  {hasEarnings && (
                    <span className="size-1 rounded-full bg-orange-500" />
                  )}
                  {hasCatalyst && (
                    <span className="size-1 rounded-full bg-purple-500" />
                  )}
                  {hasCron && !hasActivity && (
                    <span className="size-1 rounded-full bg-emerald-500" />
                  )}
                  {hasActivity && (
                    <span className="size-1 rounded-full bg-blue-500" />
                  )}
                </div>
              )}
            </button>
          );
        })}
      </div>

      {/* Legend */}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 mt-2 text-[9px] text-muted-foreground">
        <span className="flex items-center gap-1">
          <span className="size-1.5 rounded-full bg-orange-500" /> Earnings
        </span>
        <span className="flex items-center gap-1">
          <span className="size-1.5 rounded-full bg-purple-500" /> Catalyst
        </span>
        <span className="flex items-center gap-1">
          <span className="size-1.5 rounded-full bg-emerald-500" /> Scheduled
        </span>
        <span className="flex items-center gap-1">
          <span className="size-1.5 rounded-full bg-blue-500" /> Activity
        </span>
      </div>

      {/* Selected date detail */}
      {selectedDate && selectedEvents.length > 0 && (
        <div className="mt-3 space-y-1.5 border-t pt-2">
          <p className="font-semibold text-[10px] text-muted-foreground">
            {new Date(selectedDate + "T12:00:00").toLocaleDateString("en-US", {
              weekday: "short",
              month: "short",
              day: "numeric",
            })}
          </p>
          {earningsForSelected.map((e, i) => (
            <div
              key={`e-${i}`}
              className="flex items-center gap-1.5 rounded px-1.5 py-1 bg-orange-500/10 text-orange-700 dark:text-orange-300"
            >
              <span className="size-1.5 rounded-full bg-orange-500 shrink-0" />
              <span className="font-mono font-semibold">{e.symbol}</span>
              <span className="truncate">{e.label?.replace(`${e.symbol} `, "")}</span>
            </div>
          ))}
          {catalystForSelected.map((e, i) => (
            <div
              key={`cat-${i}`}
              className="flex items-center gap-1.5 rounded px-1.5 py-1 bg-purple-500/10 text-purple-700 dark:text-purple-300"
            >
              <span className="size-1.5 rounded-full bg-purple-500 shrink-0" />
              <span className="font-mono font-semibold">{e.symbol}</span>
              <span className="truncate">{e.label?.replace(`${e.symbol}: `, "")}</span>
            </div>
          ))}
          {cronForSelected.map((e, i) => (
            <div
              key={`c-${i}`}
              className="flex items-center gap-1.5 rounded px-1.5 py-1 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300"
            >
              <span className="size-1.5 rounded-full bg-emerald-500 shrink-0" />
              <span className="truncate">{e.label}</span>
            </div>
          ))}
          {activityForSelected.slice(0, 4).map((e, i) => (
            <div
              key={`a-${i}`}
              className="flex items-center gap-1.5 rounded px-1.5 py-1 bg-blue-500/10 text-blue-700 dark:text-blue-300"
            >
              <span className="size-1.5 rounded-full bg-blue-500 shrink-0" />
              <span className="truncate">{e.label}</span>
            </div>
          ))}
          {activityForSelected.length > 4 && (
            <p className="text-[9px] text-muted-foreground px-1.5">
              +{activityForSelected.length - 4} more
            </p>
          )}
        </div>
      )}
    </div>
  );
}
