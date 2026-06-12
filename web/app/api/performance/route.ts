import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";

// ?portfolio=conviction filters to the Conviction equity curve + account.
// Default = Quant Core (backward-compatible).
export async function GET(req: Request) {
  try {
    const { searchParams } = new URL(req.url);
    const portfolio = searchParams.get("portfolio") === "conviction" ? "conviction" : "quant";

    const supabase = await createClient();

    const { data: snapshots } = await supabase
      .from("equity_snapshots")
      .select("snapshot_date, portfolio_cumulative_return, spy_cumulative_return")
      .eq("portfolio", portfolio)
      .order("snapshot_date", { ascending: true })
      .limit(90);

    // Also pull live equity from the matching Alpaca account (best-effort)
    let currentEquity: number | null = null;
    try {
      const apiKey =
        portfolio === "conviction" ? process.env.ALPACA_API_KEY_CONVICTION : process.env.ALPACA_API_KEY;
      const secretKey =
        portfolio === "conviction" ? process.env.ALPACA_SECRET_KEY_CONVICTION : process.env.ALPACA_SECRET_KEY;
      const baseUrl = process.env.ALPACA_BASE_URL || "https://paper-api.alpaca.markets";
      if (apiKey && secretKey) {
        const res = await fetch(`${baseUrl}/v2/account`, {
          headers: {
            "APCA-API-KEY-ID": apiKey,
            "APCA-API-SECRET-KEY": secretKey,
          },
          next: { revalidate: 60 },
        });
        if (res.ok) {
          const acct = await res.json();
          currentEquity = parseFloat(acct.equity);
        }
      }
    } catch {
      // Fall back to latest snapshot
    }

    return NextResponse.json({
      portfolio,
      snapshots: snapshots ?? [],
      currentEquity,
      startingEquity: 100_000,
    });
  } catch {
    return NextResponse.json({ error: "Failed to load performance data" }, { status: 500 });
  }
}
