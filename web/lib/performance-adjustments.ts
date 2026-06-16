import type { SupabaseClient } from "@supabase/supabase-js";

/**
 * One-time corporate-action corrections (e.g. a broker mishandling a stock split)
 * stored in agent_memory.performance_adjustments. We add these back to displayed
 * performance so a simulator/broker artifact doesn't read as a strategy loss.
 * Single source of truth for every card/route that surfaces returns or alpha.
 */
export interface PerfAdjustment {
  amount: number;        // dollars to add back
  portfolio: string;     // "quant" | "conviction"
  date?: string;         // YYYY-MM-DD the artifact occurred
  symbol?: string;
  reason?: string;
}

const STARTING_EQUITY = 100_000;

/** Fetch the adjustments list (portfolio defaults to "quant" when untagged). */
export async function fetchPerfAdjustments(supabase: SupabaseClient): Promise<PerfAdjustment[]> {
  const { data } = await supabase
    .from("agent_memory")
    .select("value")
    .eq("key", "performance_adjustments")
    .maybeSingle();
  const list = (data?.value as { adjustments?: PerfAdjustment[] } | undefined)?.adjustments ?? [];
  return list.map((a) => ({ ...a, portfolio: a.portfolio ?? "quant" }));
}

const forBook = (adjs: PerfAdjustment[], portfolio: string) =>
  adjs.filter((a) => (a.portfolio ?? "quant") === portfolio);

/** Cumulative $ correction for a book (all dates). Apply to equity / Portfolio Value. */
export function cumulativeAdjustment(adjs: PerfAdjustment[], portfolio: string): number {
  return forBook(adjs, portfolio).reduce((s, a) => s + Number(a.amount ?? 0), 0);
}

/** $ correction dated `todayUtc` for a book. Apply to Daily P&L only. */
export function todayAdjustment(adjs: PerfAdjustment[], portfolio: string, todayUtc: string): number {
  return forBook(adjs, portfolio)
    .filter((a) => a.date === todayUtc)
    .reduce((s, a) => s + Number(a.amount ?? 0), 0);
}

/** Total absolute $ correction across all books — for disclosure copy. */
export function totalAdjustmentMagnitude(adjs: PerfAdjustment[]): number {
  return adjs.reduce((s, a) => s + Math.abs(Number(a.amount ?? 0)), 0);
}

/**
 * Cumulative-return percentage-point impact for a book ON OR AFTER `date`.
 * A fixed-$ artifact shifts cumulative return by amount/$100k pp for every point
 * from its date onward — used to correct equity-snapshot time series.
 */
export function adjustmentPpAt(adjs: PerfAdjustment[], portfolio: string, date: string): number {
  return (
    forBook(adjs, portfolio)
      .filter((a) => a.date && a.date <= date)
      .reduce((s, a) => s + Number(a.amount ?? 0), 0) / (STARTING_EQUITY / 100)
  );
}
