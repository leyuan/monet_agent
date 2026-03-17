import { NextRequest, NextResponse } from "next/server";
import YahooFinance from "yahoo-finance2";

const yf = new YahooFinance({ suppressNotices: ["yahooSurvey"] });

/**
 * GET /api/earnings-dates?symbols=MU,NVDA,WDC
 *
 * Returns upcoming earnings dates from Yahoo Finance for the given symbols.
 * Used by the event calendar as a supplement to the Finnhub-based
 * upcoming_earnings memory key (which can miss dates).
 */
export async function GET(req: NextRequest) {
  const raw = req.nextUrl.searchParams.get("symbols") ?? "";
  const symbols = raw
    .split(",")
    .map((s) => s.trim().toUpperCase())
    .filter(Boolean)
    .slice(0, 30); // cap to avoid abuse

  if (symbols.length === 0) {
    return NextResponse.json({ events: [] });
  }

  const events: {
    symbol: string;
    date: string;
    hour: string;
  }[] = [];

  await Promise.all(
    symbols.map(async (symbol) => {
      try {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const result: any = await yf.quoteSummary(symbol, {
          modules: ["calendarEvents"],
        });
        const earnings = result.calendarEvents?.earnings;
        const dateObj: Date | undefined =
          earnings?.earningsDate?.[0] ?? undefined;
        if (!dateObj) return;

        const d = dateObj instanceof Date ? dateObj : new Date(dateObj);
        if (isNaN(d.getTime())) return;

        // Only include future dates (within next 60 days)
        const now = new Date();
        const diffDays =
          (d.getTime() - now.getTime()) / (1000 * 60 * 60 * 24);
        if (diffDays < -1 || diffDays > 60) return;

        const dateStr = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

        // Yahoo doesn't reliably provide bmo/amc, so mark as unknown
        events.push({ symbol, date: dateStr, hour: "unknown" });
      } catch {
        // skip symbol on error
      }
    }),
  );

  return NextResponse.json({ events });
}
