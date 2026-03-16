"use client";

import { useEffect, useState } from "react";
import { use } from "react";
import Link from "next/link";
import { createClient } from "@/lib/supabase/client";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Skeleton } from "@/components/ui/skeleton";
import { JournalEntryCard } from "@/components/trading/journal-entry";
import { cn } from "@/lib/utils";
import { ArrowLeft, ExternalLink, Building2 } from "lucide-react";

/* ---------- Types ---------- */

interface EarningsProfile {
  pattern: string;
  beat_streak: number;
  quarters_tracked: number;
  avg_surprise_pct: number;
  key_metric: string;
  agent_insight: string;
  quarterly_history?: QuarterData[];
}

interface QuarterData {
  quarter: string;
  estimated_eps: number | null;
  actual_eps: number | null;
  surprise_pct: number;
}

interface StockAnalysis {
  symbol: string;
  thesis: string;
  target_entry: number | null;
  target_exit: number | null;
  confidence: number | null;
  composite_score: number | null;
  momentum_score: number | null;
  quality_score: number | null;
  value_score: number | null;
  eps_revision_score: number | null;
  bull_case?: string;
  bear_case?: string;
  status: string;
  last_analyzed: string;
}

interface Decision {
  key: string;
  action: string;
  reasoning: string;
  confidence: number | null;
  price_at_decision: number | null;
  decided_at: string;
  symbol: string;
}

interface Trade {
  id: string;
  symbol: string;
  side: string;
  order_type: string;
  quantity: number;
  filled_avg_price: number | null;
  status: string;
  thesis: string | null;
  confidence: number | null;
  created_at: string;
}

interface JournalEntry {
  id: string;
  entry_type: string;
  title: string;
  content: string;
  symbols: string[];
  created_at: string;
}

interface EarningsReaction {
  quarter: string;
  actual_eps: number | null;
  estimated_eps: number | null;
  surprise_pct: number | null;
  guidance: string;
  thesis_impact: string;
  action_taken: string;
  date: string;
}

interface CompanyInfo {
  name: string;
  description: string | null;
  sector: string | null;
  industry: string | null;
  website: string | null;
  logo: string | null;
  fullTimeEmployees: number | null;
  city: string | null;
  state: string | null;
  country: string | null;
}

interface Officer {
  name: string;
  title: string;
  age: number | null;
  photo: string | null;
}

interface CompanyMetrics {
  marketCap: number | null;
  trailingPE: number | null;
  forwardPE: number | null;
  profitMargins: number | null;
  revenueGrowth: number | null;
  currentPrice: number | null;
  beta: number | null;
}

interface StockDetail {
  company: CompanyInfo;
  officers: Officer[];
  metrics: CompanyMetrics;
  earningsHistory: QuarterData[];
}

interface PageData {
  earnings: EarningsProfile | null;
  stock: StockAnalysis | null;
  decisions: Decision[];
  trades: Trade[];
  journal: JournalEntry[];
  reaction: EarningsReaction | null;
  stockUpdatedAt: string | null;
  detail: StockDetail | null;
}

/* ---------- Pattern badge ---------- */

const patternColors: Record<string, { bg: string; text: string }> = {
  reliable_beater: { bg: "bg-emerald-500/10", text: "text-emerald-600 dark:text-emerald-400" },
  systematic_underestimation: { bg: "bg-emerald-500/10", text: "text-emerald-600 dark:text-emerald-400" },
  volatile: { bg: "bg-amber-500/10", text: "text-amber-600 dark:text-amber-400" },
  declining: { bg: "bg-red-500/10", text: "text-red-600 dark:text-red-400" },
};

/* ---------- Action badge colors ---------- */

const actionColors: Record<string, string> = {
  BUY: "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200",
  DCA: "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200",
  SELL: "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200",
  TRIM: "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200",
  HOLD: "bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-200",
  WAIT: "bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-200",
  LIMIT_ORDER: "bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200",
  buy: "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200",
  sell: "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200",
};

/* ---------- Sub-components ---------- */

function CompanyProfileCard({ company, officers, metrics }: { company: CompanyInfo; officers: Officer[]; metrics: CompanyMetrics }) {
  const [descExpanded, setDescExpanded] = useState(false);
  const desc = company.description ?? "";
  const truncatedDesc = desc.length > 300 ? desc.slice(0, 300) + "..." : desc;

  function formatMarketCap(val: number) {
    if (val >= 1e12) return `$${(val / 1e12).toFixed(2)}T`;
    if (val >= 1e9) return `$${(val / 1e9).toFixed(2)}B`;
    if (val >= 1e6) return `$${(val / 1e6).toFixed(0)}M`;
    return `$${val.toLocaleString()}`;
  }

  function getInitials(name: string) {
    return name.split(" ").map((n) => n[0]).join("").slice(0, 2).toUpperCase();
  }

  const initialsColors = [
    "bg-blue-500", "bg-emerald-500", "bg-purple-500", "bg-amber-500", "bg-rose-500",
  ];

  return (
    <Card>
      <CardContent className="p-5 space-y-5">
        {/* Company header */}
        <div className="flex items-start gap-4">
          {company.logo ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={company.logo}
              alt={`${company.name} logo`}
              className="size-12 rounded-lg object-contain bg-white p-1 border"
              onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }}
            />
          ) : (
            <div className="size-12 rounded-lg bg-muted flex items-center justify-center">
              <Building2 className="size-6 text-muted-foreground" />
            </div>
          )}
          <div className="flex-1 min-w-0">
            <h2 className="text-lg font-semibold leading-tight">{company.name}</h2>
            <div className="flex items-center gap-2 flex-wrap mt-1">
              {company.sector && (
                <span className="text-xs text-muted-foreground bg-muted rounded-full px-2 py-0.5">
                  {company.sector}
                </span>
              )}
              {company.industry && (
                <span className="text-xs text-muted-foreground">
                  {company.industry}
                </span>
              )}
            </div>
            <div className="flex items-center gap-3 mt-1 text-xs text-muted-foreground flex-wrap">
              {company.city && company.state && (
                <span>{company.city}, {company.state}{company.country && company.country !== "United States" ? `, ${company.country}` : ""}</span>
              )}
              {company.fullTimeEmployees && (
                <span>{company.fullTimeEmployees.toLocaleString()} employees</span>
              )}
              {company.website && (
                <a
                  href={company.website}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-0.5 text-primary hover:underline"
                >
                  Website <ExternalLink className="size-3" />
                </a>
              )}
            </div>
          </div>
        </div>

        {/* Description */}
        {desc && (
          <div>
            <p className="text-sm text-muted-foreground leading-relaxed">
              {descExpanded ? desc : truncatedDesc}
            </p>
            {desc.length > 300 && (
              <button onClick={() => setDescExpanded(!descExpanded)} className="text-xs text-primary hover:underline mt-1">
                {descExpanded ? "Show less" : "Read more"}
              </button>
            )}
          </div>
        )}

        {/* Key metrics row */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          {metrics.marketCap != null && (
            <MetricBox label="Market Cap" value={formatMarketCap(metrics.marketCap)} />
          )}
          {metrics.currentPrice != null && (
            <MetricBox label="Price" value={`$${metrics.currentPrice.toFixed(2)}`} />
          )}
          {metrics.trailingPE != null && (
            <MetricBox label="P/E (TTM)" value={metrics.trailingPE.toFixed(1)} />
          )}
          {metrics.forwardPE != null && (
            <MetricBox label="P/E (Fwd)" value={metrics.forwardPE.toFixed(1)} />
          )}
          {metrics.profitMargins != null && (
            <MetricBox label="Profit Margin" value={`${(metrics.profitMargins * 100).toFixed(1)}%`} />
          )}
          {metrics.revenueGrowth != null && (
            <MetricBox
              label="Revenue Growth"
              value={`${metrics.revenueGrowth > 0 ? "+" : ""}${(metrics.revenueGrowth * 100).toFixed(1)}%`}
              positive={metrics.revenueGrowth > 0}
            />
          )}
          {metrics.beta != null && (
            <MetricBox label="Beta" value={metrics.beta.toFixed(2)} />
          )}
        </div>

        {/* Leadership team */}
        {officers.length > 0 && (
          <div className="space-y-3">
            <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Leadership</p>
            <div className="grid gap-2 sm:grid-cols-2">
              {officers.map((o, i) => (
                <div key={o.name} className="flex items-center gap-2.5">
                  {o.photo ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img
                      src={o.photo}
                      alt={o.name}
                      className="size-8 rounded-full object-cover shrink-0"
                      onError={(e) => {
                        const el = e.target as HTMLImageElement;
                        el.style.display = "none";
                        el.nextElementSibling?.classList.remove("hidden");
                      }}
                    />
                  ) : null}
                  <div className={cn(
                    "size-8 rounded-full flex items-center justify-center text-white text-xs font-bold shrink-0",
                    initialsColors[i % initialsColors.length],
                    o.photo ? "hidden" : "",
                  )}>
                    {getInitials(o.name)}
                  </div>
                  <div className="min-w-0">
                    <p className="text-sm font-medium leading-tight truncate">{o.name}</p>
                    <p className="text-xs text-muted-foreground truncate">{o.title}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function MetricBox({ label, value, positive }: { label: string; value: string; positive?: boolean }) {
  return (
    <div className="rounded-lg border p-2.5">
      <p className="text-[10px] text-muted-foreground uppercase tracking-wider">{label}</p>
      <p className={cn("text-sm font-semibold tabular-nums mt-0.5", positive === true ? "text-green-600" : positive === false ? "text-red-500" : "")}>
        {value}
      </p>
    </div>
  );
}

function StockHeader({
  symbol,
  earnings,
  stock,
  reaction,
  stockUpdatedAt,
}: {
  symbol: string;
  earnings: EarningsProfile | null;
  stock: StockAnalysis | null;
  reaction: EarningsReaction | null;
  stockUpdatedAt: string | null;
}) {
  const pattern = earnings?.pattern;
  const colors = pattern ? patternColors[pattern] ?? { bg: "bg-muted", text: "text-muted-foreground" } : null;

  return (
    <div className="space-y-4">
      {/* Symbol row */}
      <div className="flex items-center gap-3 flex-wrap">
        <h1 className="text-2xl font-bold font-mono">{symbol}</h1>
        {colors && (
          <span className={cn("inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium", colors.bg, colors.text)}>
            {pattern!.replace(/_/g, " ")}
          </span>
        )}
        {earnings && (
          <span className="text-sm text-muted-foreground">
            {earnings.beat_streak}/{earnings.quarters_tracked} beats
            {earnings.avg_surprise_pct !== 0 && (
              <span className={cn("ml-2 font-medium", earnings.avg_surprise_pct > 0 ? "text-emerald-600 dark:text-emerald-400" : "text-red-600 dark:text-red-400")}>
                avg {earnings.avg_surprise_pct > 0 ? "+" : ""}{earnings.avg_surprise_pct.toFixed(1)}%
              </span>
            )}
          </span>
        )}
        {stockUpdatedAt && (
          <span className="text-xs text-muted-foreground">
            Last analyzed: {new Date(stockUpdatedAt).toLocaleDateString("en-US", { month: "short", day: "numeric" })}
          </span>
        )}
      </div>

      {/* Thesis + targets */}
      {stock && (
        <Card>
          <CardContent className="p-4 space-y-3">
            {stock.thesis && (
              <p className="text-sm">
                <span className="font-medium">Thesis:</span> {stock.thesis}
              </p>
            )}
            {(stock.bull_case || stock.bear_case) && (
              <div className="grid gap-3 sm:grid-cols-2">
                {stock.bull_case && (
                  <p className="text-xs text-muted-foreground">
                    <span className="font-medium text-emerald-600 dark:text-emerald-400">Bull:</span> {stock.bull_case}
                  </p>
                )}
                {stock.bear_case && (
                  <p className="text-xs text-muted-foreground">
                    <span className="font-medium text-red-600 dark:text-red-400">Bear:</span> {stock.bear_case}
                  </p>
                )}
              </div>
            )}
            <div className="flex items-center gap-4 text-xs text-muted-foreground flex-wrap">
              {stock.target_entry != null && <span>Entry: <span className="font-medium text-foreground">${stock.target_entry}</span></span>}
              {stock.target_exit != null && <span>Exit: <span className="font-medium text-foreground">${stock.target_exit}</span></span>}
              {stock.confidence != null && <span>Confidence: <span className="font-medium text-foreground">{(stock.confidence * 100).toFixed(0)}%</span></span>}
              {stock.status && <span>Status: <span className="font-medium text-foreground">{stock.status}</span></span>}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Agent insight */}
      {(earnings?.agent_insight || reaction) && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Agent Insight</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {earnings?.agent_insight && (
              <p className="text-sm text-muted-foreground">{earnings.agent_insight}</p>
            )}
            {reaction && (
              <div className="text-xs text-muted-foreground space-y-1 border-t pt-2">
                <p className="font-medium text-foreground">Latest Earnings Reaction ({reaction.quarter})</p>
                {reaction.guidance && <p>Guidance: {reaction.guidance}</p>}
                {reaction.thesis_impact && <p>Thesis impact: {reaction.thesis_impact}</p>}
                {reaction.action_taken && <p>Action: {reaction.action_taken}</p>}
              </div>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function FactorScores({ stock }: { stock: StockAnalysis }) {
  const factors = [
    { label: "Momentum", score: stock.momentum_score, color: "bg-blue-500" },
    { label: "Quality", score: stock.quality_score, color: "bg-emerald-500" },
    { label: "Value", score: stock.value_score, color: "bg-amber-500" },
    { label: "EPS Revision", score: stock.eps_revision_score, color: "bg-purple-500" },
  ];

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">Factor Scores</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {stock.composite_score != null && (
          <div className="flex items-center gap-2">
            <span className="text-xs text-muted-foreground">Composite:</span>
            <span className={cn(
              "text-2xl font-bold tabular-nums",
              stock.composite_score >= 80 ? "text-green-600" : stock.composite_score >= 70 ? "text-yellow-600" : "text-muted-foreground",
            )}>
              {stock.composite_score.toFixed(1)}
            </span>
          </div>
        )}
        {factors.map((f) => (
          <div key={f.label} className="space-y-1">
            <div className="flex items-center justify-between text-xs">
              <span className="text-muted-foreground">{f.label}</span>
              <span className="font-medium tabular-nums">{f.score != null ? f.score.toFixed(1) : "—"}</span>
            </div>
            <div className="h-2 rounded-full bg-muted overflow-hidden">
              <div
                className={cn("h-full rounded-full transition-all", f.color)}
                style={{ width: `${Math.min(f.score ?? 0, 100)}%` }}
              />
            </div>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

function EarningsHistory({ quarters }: { quarters: QuarterData[] }) {
  if (quarters.length === 0) {
    return (
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">Earnings History</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">No quarterly earnings history available.</p>
        </CardContent>
      </Card>
    );
  }

  const maxSurprise = Math.max(...quarters.map((q) => Math.abs(q.surprise_pct)), 1);

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">Earnings History</CardTitle>
      </CardHeader>
      <CardContent>
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b text-muted-foreground">
              <th className="py-1.5 text-left font-medium">Quarter</th>
              <th className="py-1.5 text-right font-medium">Est EPS</th>
              <th className="py-1.5 text-right font-medium">Actual</th>
              <th className="py-1.5 text-right font-medium">Surprise</th>
              <th className="py-1.5 pl-3 font-medium w-24"></th>
            </tr>
          </thead>
          <tbody>
            {quarters.map((q) => {
              const positive = q.surprise_pct >= 0;
              const barWidth = (Math.abs(q.surprise_pct) / maxSurprise) * 100;
              return (
                <tr key={q.quarter} className="border-b last:border-0">
                  <td className="py-1.5 font-medium">{q.quarter}</td>
                  <td className="py-1.5 text-right tabular-nums text-muted-foreground">
                    {q.estimated_eps != null ? `$${q.estimated_eps.toFixed(2)}` : "—"}
                  </td>
                  <td className="py-1.5 text-right tabular-nums">
                    {q.actual_eps != null ? `$${q.actual_eps.toFixed(2)}` : "—"}
                  </td>
                  <td className={cn("py-1.5 text-right tabular-nums font-medium", positive ? "text-emerald-600 dark:text-emerald-400" : "text-red-600 dark:text-red-400")}>
                    {positive ? "+" : ""}{q.surprise_pct.toFixed(1)}%
                  </td>
                  <td className="py-1.5 pl-3">
                    <div className="h-2 rounded-full bg-muted overflow-hidden">
                      <div
                        className={cn("h-full rounded-full", positive ? "bg-emerald-500" : "bg-red-500")}
                        style={{ width: `${barWidth}%` }}
                      />
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </CardContent>
    </Card>
  );
}

function DecisionTimeline({ decisions, trades }: { decisions: Decision[]; trades: Trade[] }) {
  type TimelineItem =
    | { type: "decision"; date: string; data: Decision }
    | { type: "trade"; date: string; data: Trade };

  const items: TimelineItem[] = [
    ...decisions.map((d) => ({ type: "decision" as const, date: d.decided_at, data: d })),
    ...trades.map((t) => ({ type: "trade" as const, date: t.created_at, data: t })),
  ].sort((a, b) => new Date(b.date).getTime() - new Date(a.date).getTime());

  if (items.length === 0) {
    return <p className="text-sm text-muted-foreground">No decisions recorded yet.</p>;
  }

  return (
    <div className="space-y-3">
      {items.map((item, i) => {
        if (item.type === "decision") {
          const d = item.data;
          return <DecisionCard key={`d-${d.key}-${i}`} decision={d} />;
        }
        const t = item.data;
        return <TradeTimelineCard key={`t-${t.id}`} trade={t} />;
      })}
    </div>
  );
}

function DecisionCard({ decision }: { decision: Decision }) {
  const [expanded, setExpanded] = useState(false);
  const action = decision.action?.toUpperCase() ?? "HOLD";
  const colorClass = actionColors[action] ?? actionColors.HOLD;
  const date = new Date(decision.decided_at).toLocaleDateString("en-US", {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  });

  return (
    <Card>
      <CardContent className="p-4 space-y-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className={cn("rounded px-2 py-0.5 text-xs font-bold uppercase", colorClass)}>
              {action}
            </span>
            <span className="text-xs text-muted-foreground">Decision</span>
          </div>
          <div className="flex items-center gap-3 text-xs text-muted-foreground">
            {decision.price_at_decision != null && (
              <span>@ ${decision.price_at_decision.toFixed(2)}</span>
            )}
            {decision.confidence != null && (
              <span>Conf: {(decision.confidence * 100).toFixed(0)}%</span>
            )}
            <span>{date}</span>
          </div>
        </div>
        {decision.reasoning && (
          <>
            <p className="text-xs text-muted-foreground">
              {expanded ? decision.reasoning : decision.reasoning.slice(0, 150) + (decision.reasoning.length > 150 ? "..." : "")}
            </p>
            {decision.reasoning.length > 150 && (
              <button onClick={() => setExpanded(!expanded)} className="text-xs text-primary hover:underline">
                {expanded ? "less" : "more"}
              </button>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}

function TradeTimelineCard({ trade }: { trade: Trade }) {
  const isBuy = trade.side === "buy";
  const colorClass = isBuy ? actionColors.buy : actionColors.sell;
  const date = new Date(trade.created_at).toLocaleDateString("en-US", {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  });

  return (
    <Card>
      <CardContent className="p-4 space-y-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className={cn("rounded px-2 py-0.5 text-xs font-bold uppercase", colorClass)}>
              {trade.side}
            </span>
            <span className="text-xs text-muted-foreground">
              {trade.quantity} shares · {trade.order_type}
            </span>
            <span className={cn(
              "rounded px-1.5 py-0.5 text-xs",
              trade.status === "filled" ? "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200" : "bg-muted text-muted-foreground",
            )}>
              {trade.status}
            </span>
          </div>
          <div className="flex items-center gap-3 text-xs text-muted-foreground">
            {trade.filled_avg_price != null && (
              <span className="font-medium text-foreground">${trade.filled_avg_price.toFixed(2)}</span>
            )}
            {trade.confidence != null && (
              <span>Conf: {(trade.confidence * 100).toFixed(0)}%</span>
            )}
            <span>{date}</span>
          </div>
        </div>
        {trade.thesis && (
          <p className="text-xs text-muted-foreground">{trade.thesis}</p>
        )}
      </CardContent>
    </Card>
  );
}

/* ---------- Main page ---------- */

export default function EarningsDetailPage({
  params,
}: {
  params: Promise<{ symbol: string }>;
}) {
  const { symbol } = use(params);
  const upperSymbol = symbol.toUpperCase();

  const [data, setData] = useState<PageData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      const supabase = createClient();

      // Fetch Supabase data + Yahoo Finance data in parallel
      const [earningsRes, stockRes, decisionsRes, tradesRes, journalRes, reactionRes, detailRes] =
        await Promise.all([
          supabase
            .from("agent_memory")
            .select("value, updated_at")
            .eq("key", `earnings_profile:${upperSymbol}`)
            .maybeSingle(),
          supabase
            .from("agent_memory")
            .select("value, updated_at")
            .eq("key", `stock:${upperSymbol}`)
            .maybeSingle(),
          supabase
            .from("agent_memory")
            .select("key, value, updated_at")
            .like("key", `decision:${upperSymbol}:%`)
            .order("updated_at", { ascending: false })
            .limit(20),
          supabase
            .from("trades")
            .select("*")
            .eq("symbol", upperSymbol)
            .order("created_at", { ascending: false })
            .limit(20),
          supabase
            .from("agent_journal")
            .select("*")
            .contains("symbols", [upperSymbol])
            .order("created_at", { ascending: false })
            .limit(10),
          supabase
            .from("agent_memory")
            .select("value, updated_at")
            .eq("key", `earnings_reaction:${upperSymbol}`)
            .maybeSingle(),
          fetch(`/api/stock-detail/${upperSymbol}`)
            .then((r) => r.ok ? r.json() : null)
            .catch(() => null),
        ]);

      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const earningsVal = earningsRes.data?.value as any;
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const stockVal = stockRes.data?.value as any;
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const reactionVal = reactionRes.data?.value as any;

      const earnings: EarningsProfile | null = earningsVal
        ? {
            pattern: earningsVal.pattern ?? "unknown",
            beat_streak: earningsVal.beat_streak ?? 0,
            quarters_tracked: earningsVal.quarters_tracked ?? 0,
            avg_surprise_pct: earningsVal.avg_surprise_pct ?? 0,
            key_metric: earningsVal.key_metric ?? "",
            agent_insight: earningsVal.agent_insight ?? "",
            quarterly_history: earningsVal.quarterly_history ?? [],
          }
        : null;

      const stock: StockAnalysis | null = stockVal
        ? {
            symbol: upperSymbol,
            thesis: stockVal.thesis ?? "",
            target_entry: stockVal.target_entry ?? null,
            target_exit: stockVal.target_exit ?? null,
            confidence: stockVal.confidence ?? null,
            composite_score: stockVal.composite_score ?? null,
            momentum_score: stockVal.momentum_score ?? null,
            quality_score: stockVal.quality_score ?? null,
            value_score: stockVal.value_score ?? null,
            eps_revision_score: stockVal.eps_revision_score ?? null,
            bull_case: stockVal.bull_case ?? undefined,
            bear_case: stockVal.bear_case ?? undefined,
            status: stockVal.status ?? "",
            last_analyzed: stockVal.last_analyzed ?? "",
          }
        : null;

      const decisions: Decision[] = (decisionsRes.data ?? []).map((row) => {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const v = row.value as any;
        return {
          key: row.key,
          action: v?.action ?? "HOLD",
          reasoning: v?.reasoning ?? "",
          confidence: v?.confidence ?? null,
          price_at_decision: v?.price_at_decision ?? null,
          decided_at: v?.decided_at ?? row.updated_at,
          symbol: upperSymbol,
        };
      });

      const reaction: EarningsReaction | null = reactionVal
        ? {
            quarter: reactionVal.quarter ?? "",
            actual_eps: reactionVal.actual_eps ?? null,
            estimated_eps: reactionVal.estimated_eps ?? null,
            surprise_pct: reactionVal.surprise_pct ?? null,
            guidance: reactionVal.guidance ?? "",
            thesis_impact: reactionVal.thesis_impact ?? "",
            action_taken: reactionVal.action_taken ?? "",
            date: reactionVal.date ?? "",
          }
        : null;

      setData({
        earnings,
        stock,
        decisions,
        trades: (tradesRes.data ?? []) as Trade[],
        journal: (journalRes.data ?? []) as JournalEntry[],
        reaction,
        stockUpdatedAt: stockRes.data?.updated_at ?? null,
        detail: detailRes as StockDetail | null,
      });
      setLoading(false);
    }
    load();
  }, [upperSymbol]);

  if (loading) {
    return (
      <div className="h-full overflow-y-auto p-6 space-y-6">
        <Link href="/dashboard" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
          <ArrowLeft className="size-4" /> Back to Dashboard
        </Link>
        <div className="flex items-center gap-4">
          <Skeleton className="size-12 rounded-lg" />
          <div className="space-y-2">
            <Skeleton className="h-6 w-48" />
            <Skeleton className="h-4 w-32" />
          </div>
        </div>
        <Skeleton className="h-24 w-full" />
        <div className="grid gap-4 md:grid-cols-2">
          <Skeleton className="h-48" />
          <Skeleton className="h-48" />
        </div>
      </div>
    );
  }

  // Use Yahoo Finance earnings history as fallback when Supabase has none
  const earningsQuarters =
    (data?.earnings?.quarterly_history ?? []).length > 0
      ? data!.earnings!.quarterly_history!
      : data?.detail?.earningsHistory ?? [];

  const hasAnyData = data?.earnings || data?.stock || data?.detail;

  return (
    <div className="h-full overflow-y-auto p-6 space-y-6">
      {/* Back link */}
      <Link href="/dashboard" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
        <ArrowLeft className="size-4" /> Back to Dashboard
      </Link>

      {!hasAnyData ? (
        <Card>
          <CardContent className="p-8 text-center space-y-2">
            <p className="text-lg font-semibold">{upperSymbol}</p>
            <p className="text-sm text-muted-foreground">
              Monet hasn&apos;t analyzed {upperSymbol} yet. It will appear here after the next factor loop run.
            </p>
          </CardContent>
        </Card>
      ) : (
        <Tabs defaultValue="overview">
          <TabsList>
            <TabsTrigger value="overview">Overview</TabsTrigger>
            <TabsTrigger value="decisions">
              Decisions & Trades
              {((data?.decisions.length ?? 0) + (data?.trades.length ?? 0)) > 0 && (
                <span className="ml-1.5 text-xs text-muted-foreground">
                  ({(data?.decisions.length ?? 0) + (data?.trades.length ?? 0)})
                </span>
              )}
            </TabsTrigger>
            <TabsTrigger value="journal">
              Journal
              {(data?.journal.length ?? 0) > 0 && (
                <span className="ml-1.5 text-xs text-muted-foreground">({data?.journal.length})</span>
              )}
            </TabsTrigger>
          </TabsList>

          {/* Tab 1: Overview */}
          <TabsContent value="overview" className="space-y-6">
            {/* Company profile (from Yahoo Finance) */}
            {data?.detail && (
              <CompanyProfileCard
                company={data.detail.company}
                officers={data.detail.officers}
                metrics={data.detail.metrics}
              />
            )}

            <StockHeader
              symbol={upperSymbol}
              earnings={data?.earnings ?? null}
              stock={data?.stock ?? null}
              reaction={data?.reaction ?? null}
              stockUpdatedAt={data?.stockUpdatedAt ?? null}
            />

            <div className="grid gap-4 md:grid-cols-2">
              {data?.stock && (data.stock.composite_score != null || data.stock.momentum_score != null) && (
                <FactorScores stock={data.stock} />
              )}
              <EarningsHistory quarters={earningsQuarters} />
            </div>
          </TabsContent>

          {/* Tab 2: Decisions & Trades */}
          <TabsContent value="decisions">
            <DecisionTimeline
              decisions={data?.decisions ?? []}
              trades={data?.trades ?? []}
            />
          </TabsContent>

          {/* Tab 3: Journal */}
          <TabsContent value="journal" className="space-y-4">
            {(data?.journal.length ?? 0) === 0 ? (
              <p className="text-sm text-muted-foreground">No journal entries for {upperSymbol} yet.</p>
            ) : (
              data?.journal.map((entry) => (
                <JournalEntryCard key={entry.id} entry={entry} />
              ))
            )}
          </TabsContent>
        </Tabs>
      )}
    </div>
  );
}
