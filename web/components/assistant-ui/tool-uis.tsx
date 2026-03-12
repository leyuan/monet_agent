"use client";

import { makeAssistantToolUI } from "@assistant-ui/react";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import {
  TrendingUpIcon,
  TrendingDownIcon,
  MinusIcon,
  ShieldIcon,
  ActivityIcon,
  BarChart3Icon,
  ArrowUpIcon,
  ArrowDownIcon,
} from "lucide-react";

// ============================================================
// Helpers
// ============================================================

function fmt(n: number | null | undefined): string {
  if (n == null) return "—";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
  }).format(n);
}

function fmtPct(n: number | null | undefined, decimals = 1): string {
  if (n == null) return "—";
  const sign = n > 0 ? "+" : "";
  return `${sign}${(n * 100).toFixed(decimals)}%`;
}

function fmtPctRaw(n: number | null | undefined, decimals = 1): string {
  if (n == null) return "—";
  const sign = n > 0 ? "+" : "";
  return `${sign}${n.toFixed(decimals)}%`;
}

function fmtCompact(n: number | null | undefined): string {
  if (n == null) return "—";
  if (Math.abs(n) >= 1e12) return `$${(n / 1e12).toFixed(1)}T`;
  if (Math.abs(n) >= 1e9) return `$${(n / 1e9).toFixed(1)}B`;
  if (Math.abs(n) >= 1e6) return `$${(n / 1e6).toFixed(1)}M`;
  return fmt(n);
}

function PnlText({ value, className }: { value: number | null | undefined; className?: string }) {
  if (value == null) return <span className={className}>—</span>;
  return (
    <span className={cn(value >= 0 ? "text-green-600" : "text-red-500", className)}>
      {value >= 0 ? "+" : ""}{value.toFixed(2)}%
    </span>
  );
}

function Badge({ children, variant = "default" }: { children: React.ReactNode; variant?: "default" | "green" | "red" | "yellow" }) {
  const colors = {
    default: "bg-muted text-muted-foreground",
    green: "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400",
    red: "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400",
    yellow: "bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400",
  };
  return (
    <span className={cn("inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium", colors[variant])}>
      {children}
    </span>
  );
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function ToolCard({ children, isRunning }: { children: React.ReactNode; isRunning: boolean }) {
  if (isRunning) return null;
  return (
    <Card className="my-2 overflow-hidden">
      <CardContent className="p-4">{children}</CardContent>
    </Card>
  );
}

// ============================================================
// Stock Quote
// ============================================================

export const StockQuoteUI = makeAssistantToolUI({
  toolName: "get_stock_quote",
  render: ({ result, status }) => {
    if (status?.type === "running" || !result) return null;
    const data = typeof result === "string" ? JSON.parse(result) : result;
    const isIndex = "price" in data;

    if (isIndex) {
      return (
        <ToolCard isRunning={false}>
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-semibold">{data.symbol}</p>
              <p className="text-2xl font-bold">{fmt(data.price)}</p>
            </div>
            <div className="text-right">
              <PnlText value={data.change_pct} className="text-lg font-semibold" />
              <p className="text-xs text-muted-foreground">vs prev close</p>
            </div>
          </div>
        </ToolCard>
      );
    }

    const mid = data.bid_price && data.ask_price
      ? ((data.bid_price + data.ask_price) / 2)
      : data.bid_price || data.ask_price;

    return (
      <ToolCard isRunning={false}>
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm font-semibold">{data.symbol}</p>
            <p className="text-2xl font-bold">{fmt(mid)}</p>
          </div>
          <div className="text-right text-xs text-muted-foreground space-y-0.5">
            <p>Bid: {fmt(data.bid_price)} <span className="text-muted-foreground/60">x{data.bid_size}</span></p>
            <p>Ask: {fmt(data.ask_price)} <span className="text-muted-foreground/60">x{data.ask_size}</span></p>
          </div>
        </div>
      </ToolCard>
    );
  },
});

// ============================================================
// Portfolio
// ============================================================

export const PortfolioUI = makeAssistantToolUI({
  toolName: "get_my_portfolio",
  render: ({ result, status }) => {
    if (status?.type === "running" || !result) return null;
    const data = typeof result === "string" ? JSON.parse(result) : result;
    const positions = data.positions || [];

    return (
      <ToolCard isRunning={false}>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 mb-3">
          <div>
            <p className="text-xs text-muted-foreground">Equity</p>
            <p className="text-sm font-semibold">{fmt(data.equity)}</p>
          </div>
          <div>
            <p className="text-xs text-muted-foreground">Cash</p>
            <p className="text-sm font-semibold">{fmt(data.cash)}</p>
          </div>
          <div>
            <p className="text-xs text-muted-foreground">Buying Power</p>
            <p className="text-sm font-semibold">{fmt(data.buying_power)}</p>
          </div>
          <div>
            <p className="text-xs text-muted-foreground">Daily P&L</p>
            <p className={cn("text-sm font-semibold", data.daily_pnl >= 0 ? "text-green-600" : "text-red-500")}>
              {fmt(data.daily_pnl)}
            </p>
          </div>
        </div>
        {positions.length > 0 && (
          <div className="overflow-x-auto -mx-4 px-4">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b text-muted-foreground">
                  <th className="pb-1.5 text-left font-medium">Symbol</th>
                  <th className="pb-1.5 text-right font-medium">Qty</th>
                  <th className="pb-1.5 text-right font-medium">Price</th>
                  <th className="pb-1.5 text-right font-medium">P&L</th>
                </tr>
              </thead>
              <tbody>
                {positions.map((p: Record<string, number | string>) => (
                  <tr key={String(p.symbol)} className="border-b last:border-0">
                    <td className="py-1.5 font-medium">{String(p.symbol)}</td>
                    <td className="py-1.5 text-right">{Number(p.qty)}</td>
                    <td className="py-1.5 text-right">{fmt(Number(p.current_price))}</td>
                    <td className={cn("py-1.5 text-right", Number(p.unrealized_pl) >= 0 ? "text-green-600" : "text-red-500")}>
                      {fmt(Number(p.unrealized_pl))} ({fmtPct(Number(p.unrealized_plpc))})
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </ToolCard>
    );
  },
});

// ============================================================
// Market Breadth
// ============================================================

export const MarketBreadthUI = makeAssistantToolUI({
  toolName: "market_breadth",
  render: ({ result, status }) => {
    if (status?.type === "running" || !result) return null;
    const data = typeof result === "string" ? JSON.parse(result) : result;

    const regimeColor = data.regime?.includes("bull") || data.regime?.includes("uptrend")
      ? "green"
      : data.regime?.includes("weakness") || data.regime?.includes("risk-off")
        ? "red"
        : "yellow";

    return (
      <ToolCard isRunning={false}>
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <ActivityIcon className="size-4 text-muted-foreground" />
            <p className="text-sm font-semibold">Market Breadth</p>
          </div>
          <Badge variant={regimeColor}>{data.regime}</Badge>
        </div>
        <div className="space-y-2">
          <BreadthBar label="Above 50-day SMA" value={data.pct_above_sma50} />
          <BreadthBar label="Above 200-day SMA" value={data.pct_above_sma200} />
        </div>
        <div className="mt-2 flex gap-4 text-xs text-muted-foreground">
          <span>A/D Ratio: {data.advance_decline_ratio?.toFixed(2)}</span>
          <span>Advancing: {data.advancing_20d}</span>
          <span>Declining: {data.declining_20d}</span>
        </div>
      </ToolCard>
    );
  },
});

function BreadthBar({ label, value }: { label: string; value: number }) {
  const color = value >= 60 ? "bg-green-500" : value >= 40 ? "bg-yellow-500" : "bg-red-500";
  return (
    <div>
      <div className="flex justify-between text-xs mb-0.5">
        <span className="text-muted-foreground">{label}</span>
        <span className="font-medium">{value?.toFixed(0)}%</span>
      </div>
      <div className="h-1.5 w-full rounded-full bg-muted">
        <div className={cn("h-1.5 rounded-full transition-all", color)} style={{ width: `${Math.min(value, 100)}%` }} />
      </div>
    </div>
  );
}

// ============================================================
// Sector Analysis
// ============================================================

export const SectorAnalysisUI = makeAssistantToolUI({
  toolName: "sector_analysis",
  render: ({ result, status }) => {
    if (status?.type === "running" || !result) return null;
    const data = typeof result === "string" ? JSON.parse(result) : result;
    const sectors = (data.sectors || [])
      .slice()
      .sort((a: { total_return: number }, b: { total_return: number }) => b.total_return - a.total_return);

    const rotationColor = data.rotation_signal === "risk-on" ? "green" : data.rotation_signal === "risk-off" ? "red" : "yellow";

    return (
      <ToolCard isRunning={false}>
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <BarChart3Icon className="size-4 text-muted-foreground" />
            <p className="text-sm font-semibold">Sector Performance ({data.period})</p>
          </div>
          <Badge variant={rotationColor}>{data.rotation_signal}</Badge>
        </div>
        <div className="space-y-1">
          {sectors.map((s: { etf: string; sector: string; total_return: number; rsi: number }) => {
            const pct = s.total_return * 100;
            const maxAbs = Math.max(...sectors.map((x: { total_return: number }) => Math.abs(x.total_return * 100)), 1);
            const width = Math.abs(pct) / maxAbs * 50;
            const isPositive = pct >= 0;
            return (
              <div key={s.etf} className="flex items-center gap-2 text-xs">
                <span className="w-28 truncate text-muted-foreground">{s.sector}</span>
                <div className="flex-1 flex items-center h-4">
                  <div className="relative w-full h-3">
                    {/* Center line */}
                    <div className="absolute left-1/2 top-0 h-full w-px bg-border" />
                    {/* Bar */}
                    <div
                      className={cn(
                        "absolute top-0.5 h-2 rounded-sm",
                        isPositive ? "bg-green-500" : "bg-red-500"
                      )}
                      style={{
                        left: isPositive ? "50%" : `${50 - width}%`,
                        width: `${width}%`,
                      }}
                    />
                  </div>
                </div>
                <span className={cn("w-14 text-right font-medium", isPositive ? "text-green-600" : "text-red-500")}>
                  {fmtPctRaw(pct)}
                </span>
              </div>
            );
          })}
        </div>
      </ToolCard>
    );
  },
});

// ============================================================
// EPS Estimates
// ============================================================

export const EpsEstimatesUI = makeAssistantToolUI({
  toolName: "eps_estimates",
  render: ({ args, result, status }) => {
    if (status?.type === "running" || !result) return null;
    const data = typeof result === "string" ? JSON.parse(result) : result;
    if (data.error || !data.estimates?.length) return null;

    const signal = data.revision_signal;
    const SignalIcon = signal === "rising" ? TrendingUpIcon : signal === "falling" ? TrendingDownIcon : MinusIcon;
    const signalColor = signal === "rising" ? "green" : signal === "falling" ? "red" : "yellow";

    return (
      <ToolCard isRunning={false}>
        <div className="flex items-center justify-between mb-3">
          <p className="text-sm font-semibold">{data.symbol} EPS Estimates</p>
          {signal && (
            <Badge variant={signalColor}>
              <SignalIcon className="size-3 mr-1" />
              {signal}
            </Badge>
          )}
        </div>
        <div className="overflow-x-auto -mx-4 px-4">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b text-muted-foreground">
                <th className="pb-1.5 text-left font-medium">Period</th>
                <th className="pb-1.5 text-right font-medium">EPS Est.</th>
                <th className="pb-1.5 text-right font-medium">High</th>
                <th className="pb-1.5 text-right font-medium">Low</th>
                <th className="pb-1.5 text-right font-medium">Analysts</th>
              </tr>
            </thead>
            <tbody>
              {data.estimates.slice(0, 6).map((e: Record<string, number | string | null>, i: number) => (
                <tr key={i} className="border-b last:border-0">
                  <td className="py-1.5 font-medium">{e.period ? String(e.period) : `Q${e.quarter} ${e.year}`}</td>
                  <td className="py-1.5 text-right">{e.eps_avg != null ? Number(e.eps_avg).toFixed(2) : "—"}</td>
                  <td className="py-1.5 text-right text-muted-foreground">{e.eps_high != null ? Number(e.eps_high).toFixed(2) : "—"}</td>
                  <td className="py-1.5 text-right text-muted-foreground">{e.eps_low != null ? Number(e.eps_low).toFixed(2) : "—"}</td>
                  <td className="py-1.5 text-right text-muted-foreground">{e.num_analysts ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </ToolCard>
    );
  },
});

// ============================================================
// Technical Analysis
// ============================================================

export const TechnicalAnalysisUI = makeAssistantToolUI({
  toolName: "technical_analysis",
  render: ({ result, status }) => {
    if (status?.type === "running" || !result) return null;
    const data = typeof result === "string" ? JSON.parse(result) : result;
    if (data.error) return null;

    const rsiColor = data.rsi > 70 ? "text-red-500" : data.rsi < 30 ? "text-green-600" : "text-foreground";
    const signals = data.signals || [];

    return (
      <ToolCard isRunning={false}>
        <div className="flex items-center justify-between mb-3">
          <p className="text-sm font-semibold">{data.symbol} Technicals</p>
          <span className="text-xs text-muted-foreground">{fmt(data.price)}</span>
        </div>
        <div className="grid grid-cols-2 gap-x-6 gap-y-2 text-xs mb-3">
          <div className="flex justify-between">
            <span className="text-muted-foreground">RSI</span>
            <span className={cn("font-medium", rsiColor)}>{data.rsi?.toFixed(1)}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-muted-foreground">ATR</span>
            <span className="font-medium">{data.atr?.toFixed(2)}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-muted-foreground">MACD</span>
            <span className={cn("font-medium", data.macd?.histogram >= 0 ? "text-green-600" : "text-red-500")}>
              {data.macd?.histogram?.toFixed(2)}
            </span>
          </div>
          <div className="flex justify-between">
            <span className="text-muted-foreground">Volume</span>
            <span className="font-medium">{data.volume?.ratio?.toFixed(1)}x avg</span>
          </div>
          <div className="flex justify-between">
            <span className="text-muted-foreground">SMA 50</span>
            <span className="font-medium">{data.moving_averages?.sma_50 ? fmt(data.moving_averages.sma_50) : "—"}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-muted-foreground">SMA 200</span>
            <span className="font-medium">{data.moving_averages?.sma_200 ? fmt(data.moving_averages.sma_200) : "—"}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-muted-foreground">BB Upper</span>
            <span className="font-medium">{fmt(data.bollinger_bands?.upper)}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-muted-foreground">BB Lower</span>
            <span className="font-medium">{fmt(data.bollinger_bands?.lower)}</span>
          </div>
        </div>
        {signals.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {signals.map((s: string, i: number) => {
              const isBullish = s.includes("oversold") || s.includes("bullish") || s.includes("above");
              const isBearish = s.includes("overbought") || s.includes("bearish") || s.includes("below");
              return (
                <Badge key={i} variant={isBullish ? "green" : isBearish ? "red" : "default"}>
                  {s}
                </Badge>
              );
            })}
          </div>
        )}
      </ToolCard>
    );
  },
});

// ============================================================
// Fundamental Analysis
// ============================================================

export const FundamentalAnalysisUI = makeAssistantToolUI({
  toolName: "fundamental_analysis",
  render: ({ result, status }) => {
    if (status?.type === "running" || !result) return null;
    const data = typeof result === "string" ? JSON.parse(result) : result;

    const recColor = data.recommendation === "strong_buy" || data.recommendation === "buy"
      ? "green"
      : data.recommendation === "sell" || data.recommendation === "strong_sell"
        ? "red"
        : "yellow";

    return (
      <ToolCard isRunning={false}>
        <div className="flex items-center justify-between mb-3">
          <div>
            <p className="text-sm font-semibold">{data.symbol}</p>
            <p className="text-xs text-muted-foreground">{data.name} · {data.sector}</p>
          </div>
          {data.recommendation && (
            <Badge variant={recColor}>{data.recommendation.replace("_", " ")}</Badge>
          )}
        </div>
        <div className="grid grid-cols-2 gap-x-6 gap-y-2 text-xs">
          <Metric label="Market Cap" value={fmtCompact(data.market_cap)} />
          <Metric label="P/E" value={data.pe_ratio?.toFixed(1)} />
          <Metric label="Forward P/E" value={data.forward_pe?.toFixed(1)} />
          <Metric label="PEG" value={data.peg_ratio?.toFixed(2)} />
          <Metric label="Revenue Growth" value={fmtPct(data.revenue_growth)} highlight={data.revenue_growth} />
          <Metric label="Earnings Growth" value={fmtPct(data.earnings_growth)} highlight={data.earnings_growth} />
          <Metric label="Profit Margin" value={fmtPct(data.profit_margin)} />
          <Metric label="D/E Ratio" value={data.debt_to_equity?.toFixed(2)} />
          <Metric label="Beta" value={data.beta?.toFixed(2)} />
          <Metric label="Analyst Target" value={fmt(data.analyst_target)} />
          <Metric label="52W High" value={fmt(data.fifty_two_week_high)} />
          <Metric label="52W Low" value={fmt(data.fifty_two_week_low)} />
        </div>
      </ToolCard>
    );
  },
});

function Metric({ label, value, highlight }: { label: string; value: string | undefined; highlight?: number | null }) {
  return (
    <div className="flex justify-between">
      <span className="text-muted-foreground">{label}</span>
      <span className={cn(
        "font-medium",
        highlight != null && highlight > 0 ? "text-green-600" : highlight != null && highlight < 0 ? "text-red-500" : ""
      )}>
        {value ?? "—"}
      </span>
    </div>
  );
}

// ============================================================
// Peer Comparison
// ============================================================

export const PeerComparisonUI = makeAssistantToolUI({
  toolName: "peer_comparison",
  render: ({ result, status }) => {
    if (status?.type === "running" || !result) return null;
    const data = typeof result === "string" ? JSON.parse(result) : result;
    if (data.error || !data.comparisons?.length) return null;

    return (
      <ToolCard isRunning={false}>
        <p className="text-sm font-semibold mb-3">{data.symbol} vs Peers</p>
        <div className="overflow-x-auto -mx-4 px-4">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b text-muted-foreground">
                <th className="pb-1.5 text-left font-medium">Ticker</th>
                <th className="pb-1.5 text-right font-medium">Mkt Cap</th>
                <th className="pb-1.5 text-right font-medium">P/E</th>
                <th className="pb-1.5 text-right font-medium">Margin</th>
                <th className="pb-1.5 text-right font-medium">3M Return</th>
              </tr>
            </thead>
            <tbody>
              {data.comparisons.map((c: Record<string, number | string | null>) => {
                const isTarget = String(c.symbol) === data.symbol;
                return (
                  <tr key={String(c.symbol)} className={cn("border-b last:border-0", isTarget && "bg-muted/50")}>
                    <td className={cn("py-1.5", isTarget ? "font-semibold" : "font-medium")}>{String(c.symbol)}</td>
                    <td className="py-1.5 text-right">{fmtCompact(c.market_cap as number)}</td>
                    <td className="py-1.5 text-right">{c.pe_ratio != null ? Number(c.pe_ratio).toFixed(1) : "—"}</td>
                    <td className="py-1.5 text-right">{c.profit_margin != null ? fmtPct(Number(c.profit_margin)) : "—"}</td>
                    <td className={cn("py-1.5 text-right", c.return_3m != null && Number(c.return_3m) >= 0 ? "text-green-600" : "text-red-500")}>
                      {c.return_3m != null ? fmtPct(Number(c.return_3m)) : "—"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </ToolCard>
    );
  },
});

// ============================================================
// Performance Comparison
// ============================================================

export const PerformanceComparisonUI = makeAssistantToolUI({
  toolName: "get_performance_comparison",
  render: ({ result, status }) => {
    if (status?.type === "running" || !result) return null;
    const data = typeof result === "string" ? JSON.parse(result) : result;
    if (data.error) return null;

    return (
      <ToolCard isRunning={false}>
        <div className="flex items-center justify-between mb-3">
          <p className="text-sm font-semibold">Performance vs SPY ({data.period_days}d)</p>
          <Badge variant={data.alpha_pct >= 0 ? "green" : "red"}>
            Alpha: {fmtPctRaw(data.alpha_pct)}
          </Badge>
        </div>
        <div className="grid grid-cols-3 gap-3 text-xs">
          <div>
            <p className="text-muted-foreground">Portfolio</p>
            <p className={cn("font-semibold", data.portfolio_return_pct >= 0 ? "text-green-600" : "text-red-500")}>
              {fmtPctRaw(data.portfolio_return_pct)}
            </p>
          </div>
          <div>
            <p className="text-muted-foreground">SPY</p>
            <p className={cn("font-semibold", data.spy_return_pct >= 0 ? "text-green-600" : "text-red-500")}>
              {fmtPctRaw(data.spy_return_pct)}
            </p>
          </div>
          <div>
            <p className="text-muted-foreground">Max Drawdown</p>
            <p className="font-semibold text-red-500">-{data.max_drawdown_pct?.toFixed(1)}%</p>
          </div>
        </div>
      </ToolCard>
    );
  },
});
