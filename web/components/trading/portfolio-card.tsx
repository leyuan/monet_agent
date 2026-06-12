"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

interface Position {
  symbol: string;
  qty: number;
  market_value: number;
  unrealized_pl: number;
  unrealized_plpc: number;
  current_price: number;
  avg_entry_price: number;
}

interface PortfolioAccount {
  equity: number;       // total account value (positions + cash)
  cash: number;
  buying_power: number;
  portfolio_value: number; // positions market value only
  daily_pnl: number;
}

interface PortfolioData {
  account: PortfolioAccount;
  positions: Position[];
}

const STARTING_EQUITY = 100_000;

/**
 * adjustment: cumulative one-time corporate-action correction for THIS portfolio
 *   (e.g. a broker split artifact) — applied to Portfolio Value & Realized P&L.
 * todayAdjustment: the portion dated today — applied to Daily P&L only (the
 *   artifact only distorts the day it occurred).
 */
export function PortfolioSummary({
  data,
  adjustment = 0,
  todayAdjustment = 0,
}: {
  data: PortfolioData;
  adjustment?: number;
  todayAdjustment?: number;
}) {
  const { account, positions } = data;
  const unrealizedPl = positions.reduce((sum, p) => sum + p.unrealized_pl, 0);
  const portfolioValue = account.equity + adjustment;
  const totalPl = portfolioValue - STARTING_EQUITY;
  const realizedPl = totalPl - unrealizedPl; // artifact lives in realized, not unrealized
  const dailyPnl = account.daily_pnl + todayAdjustment;

  return (
    <div className="space-y-1.5">
      <div className="grid gap-4 md:grid-cols-5">
        <StatCard label="Portfolio Value" value={fmt(portfolioValue)} />
        <StatCard label="Cash" value={fmt(account.cash)} />
        <StatCard
          label="Unrealized P&L"
          value={fmt(unrealizedPl)}
          className={unrealizedPl >= 0 ? "text-green-600" : "text-red-500"}
        />
        <StatCard
          label="Realized P&L"
          value={fmt(realizedPl)}
          className={realizedPl >= 0 ? "text-green-600" : "text-red-500"}
        />
        <StatCard
          label="Daily P&L"
          value={fmt(dailyPnl)}
          className={dailyPnl >= 0 ? "text-green-600" : "text-red-500"}
        />
      </div>
      {adjustment !== 0 && (
        <p className="text-[11px] text-muted-foreground/70">
          Portfolio Value, Realized{todayAdjustment !== 0 ? " & Daily" : ""} P&L include a{" "}
          {adjustment > 0 ? "+" : "−"}${(Math.abs(adjustment) / 1000).toFixed(1)}k one-time KLAC split-artifact correction.
        </p>
      )}
    </div>
  );
}

export function PositionsTable({ positions }: { positions: Position[] }) {
  if (positions.length === 0) {
    return (
      <Card>
        <CardContent className="p-6 text-center text-muted-foreground">
          No open positions
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Positions</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-left text-muted-foreground">
                <th className="pb-2 font-medium">Symbol</th>
                <th className="pb-2 font-medium">Qty</th>
                <th className="pb-2 font-medium">Price</th>
                <th className="pb-2 font-medium">Avg Entry</th>
                <th className="pb-2 font-medium">Value</th>
                <th className="pb-2 font-medium text-right">P&L</th>
              </tr>
            </thead>
            <tbody>
              {positions.map((pos) => (
                <tr key={pos.symbol} className="border-b last:border-0">
                  <td className="py-2 font-medium">{pos.symbol}</td>
                  <td className="py-2">{pos.qty}</td>
                  <td className="py-2">{fmt(pos.current_price)}</td>
                  <td className="py-2">{fmt(pos.avg_entry_price)}</td>
                  <td className="py-2">{fmt(pos.market_value)}</td>
                  <td className={cn("py-2 text-right", pos.unrealized_pl >= 0 ? "text-green-600" : "text-red-500")}>
                    {fmt(pos.unrealized_pl)} ({(pos.unrealized_plpc * 100).toFixed(1)}%)
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
}

function StatCard({ label, value, className }: { label: string; value: string; className?: string }) {
  return (
    <Card>
      <CardContent className="p-4">
        <p className="text-xs text-muted-foreground">{label}</p>
        <p className={cn("text-xl font-semibold", className)}>{value}</p>
      </CardContent>
    </Card>
  );
}

function fmt(n: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
  }).format(n);
}
