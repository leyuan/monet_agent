"use client";

import { useEffect, useState } from "react";
import { createClient } from "@/lib/supabase/client";
import { PortfolioSummary, PositionsTable } from "@/components/trading/portfolio-card";
import { TradeCard } from "@/components/trading/trade-card";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export default function DashboardPage() {
  const [portfolio, setPortfolio] = useState<any>(null);
  const [trades, setTrades] = useState<any[]>([]);
  const [watchlist, setWatchlist] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      const supabase = createClient();

      const [tradesRes, watchlistRes] = await Promise.all([
        supabase.from("trades").select("*").order("created_at", { ascending: false }).limit(10),
        supabase.from("watchlist").select("*").order("added_at", { ascending: false }),
      ]);

      setTrades(tradesRes.data ?? []);
      setWatchlist(watchlistRes.data ?? []);
      setLoading(false);
    }
    load();
  }, []);

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="animate-pulse text-muted-foreground">Loading dashboard...</div>
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto p-6 space-y-6">
      <h1 className="text-2xl font-semibold">Dashboard</h1>

      {portfolio && (
        <>
          <PortfolioSummary data={portfolio} />
          <PositionsTable positions={portfolio.positions} />
        </>
      )}

      <div className="grid gap-6 lg:grid-cols-2">
        <div className="space-y-4">
          <h2 className="text-lg font-semibold">Recent Trades</h2>
          {trades.length === 0 ? (
            <Card><CardContent className="p-4 text-center text-muted-foreground">No trades yet</CardContent></Card>
          ) : (
            trades.map((t) => <TradeCard key={t.id} trade={t} />)
          )}
        </div>

        <div className="space-y-4">
          <h2 className="text-lg font-semibold">Watchlist</h2>
          {watchlist.length === 0 ? (
            <Card><CardContent className="p-4 text-center text-muted-foreground">Watchlist empty</CardContent></Card>
          ) : (
            <Card>
              <CardContent className="p-0">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b text-left text-muted-foreground">
                      <th className="p-3 font-medium">Symbol</th>
                      <th className="p-3 font-medium">Thesis</th>
                      <th className="p-3 font-medium">Target Entry</th>
                    </tr>
                  </thead>
                  <tbody>
                    {watchlist.map((w) => (
                      <tr key={w.id} className="border-b last:border-0">
                        <td className="p-3 font-mono font-semibold">{w.symbol}</td>
                        <td className="p-3 text-muted-foreground">{w.thesis || "-"}</td>
                        <td className="p-3">{w.target_entry ? `$${w.target_entry}` : "-"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </CardContent>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
