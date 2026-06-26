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
  date?: string;         // YYYY-MM-DD the artifact occurred (correction start)
  end_date?: string;     // YYYY-MM-DD the artifact RESOLVED; correction inactive after this
  symbol?: string;
  reason?: string;
}

const STARTING_EQUITY = 100_000;

/** Today as YYYY-MM-DD (UTC) — the as-of date for live/current figures. */
function todayUtc(): string {
  return new Date().toISOString().slice(0, 10);
}

/**
 * Is a correction still ACTIVE as of `asOf`? Inactive once its `end_date` has
 * passed — e.g. a missing position was restored in the account, so live equity
 * already reflects the recovery and adding the correction would double-count.
 */
function activeAt(a: PerfAdjustment, asOf: string): boolean {
  if (a.date && a.date > asOf) return false;          // hasn't occurred yet
  if (a.end_date && asOf > a.end_date) return false;  // already resolved
  return true;
}

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

/**
 * Cumulative $ correction for a book that is still ACTIVE as of `asOf` (default
 * today). A correction whose `end_date` has passed is dropped, so current equity
 * isn't double-counted once the underlying artifact resolves. Apply to equity /
 * Portfolio Value.
 */
export function cumulativeAdjustment(
  adjs: PerfAdjustment[],
  portfolio: string,
  asOf: string = todayUtc(),
): number {
  return forBook(adjs, portfolio)
    .filter((a) => activeAt(a, asOf))
    .reduce((s, a) => s + Number(a.amount ?? 0), 0);
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
 * Cumulative-return percentage-point impact for a book at time-series point `date`.
 * A fixed-$ artifact shifts cumulative return by amount/$100k pp for every point
 * from its `date` until its `end_date` (if it has resolved) — used to correct the
 * equity-snapshot series for the depressed window while keeping post-resolution
 * points honest.
 */
export function adjustmentPpAt(adjs: PerfAdjustment[], portfolio: string, date: string): number {
  return (
    forBook(adjs, portfolio)
      .filter((a) => a.date && a.date <= date && (!a.end_date || date <= a.end_date))
      .reduce((s, a) => s + Number(a.amount ?? 0), 0) / (STARTING_EQUITY / 100)
  );
}
