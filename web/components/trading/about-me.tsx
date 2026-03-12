"use client";

import { useEffect, useState } from "react";
import { createClient } from "@/lib/supabase/client";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

interface WatchlistRow {
  id: string;
  symbol: string;
  thesis: string;
  target_entry: number | null;
  target_exit: number | null;
}

const MEMORY_KEYS = [
  "strategy",
  "risk_appetite",
  "market_outlook",
  "factor_weights",
  "factor_rankings",
];

const SKILLS = [
  "Factor-Based Scoring",
  "Universe Screening (900 stocks)",
  "Momentum Factor",
  "Quality Factor",
  "Value Factor",
  "EPS Revision Tracking",
  "Earnings Interpretation",
  "Market Breadth",
  "Sector Rotation",
  "Risk Management",
  "Position Sizing",
  "Bracket Orders",
  "Anti-Churn Controls",
  "Portfolio Rebalancing",
];

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function buildBio(memories: Record<string, any>, watchlist: WatchlistRow[]): string {
  const strategy = memories.strategy;
  const risk = memories.risk_appetite;
  const outlook = memories.market_outlook;
  const factorWeights = memories.factor_weights;
  const factorRankings = memories.factor_rankings;

  const paragraphs: string[] = [];

  // Paragraph 1: Identity & approach
  const approach = strategy?.summary
    ? strategy.summary
    : "I score the S&P 500 and S&P 400 universe on four quantitative factors — momentum, quality, value, and EPS revisions — to systematically identify the best risk-adjusted opportunities.";
  paragraphs.push(
    `My name is **Monet**. I'm a systematic, factor-based AI investor. ${approach} My edge is **breadth** (scoring ~900 stocks every run), **speed** (reacting to earnings within hours), and **discipline** (never overriding the system with gut feel).`
  );

  // Paragraph 2: Factor weights & risk
  const riskLevel = risk?.level ?? "moderate";
  const riskSummary = risk?.summary ?? "";
  const maxPos = strategy?.max_positions ?? "8";
  if (factorWeights) {
    const mom = factorWeights.momentum ?? 0.35;
    const qual = factorWeights.quality ?? 0.30;
    const val = factorWeights.value ?? 0.20;
    const eps = factorWeights.eps_revision ?? 0.15;
    paragraphs.push(
      `My factor weights: **Momentum ${Math.round(mom * 100)}%**, **Quality ${Math.round(qual * 100)}%**, **Value ${Math.round(val * 100)}%**, **EPS Revision ${Math.round(eps * 100)}%**. ` +
      `Risk appetite is **${riskLevel}**. ${riskSummary ? riskSummary + " " : ""}` +
      `I run up to ${maxPos} positions with a 20% cash buffer.`
    );
  } else {
    paragraphs.push(
      `My risk appetite is **${riskLevel}**. ${riskSummary ? riskSummary + " " : ""}` +
      `I run up to ${maxPos} positions with a 20% cash buffer.`
    );
  }

  // Paragraph 3: Current market read
  if (outlook) {
    const regime = outlook.regime ?? "uncertain";
    const vix = outlook.vix ? `VIX at ${outlook.vix}` : "";
    const interp = outlook.interpretation ?? "";
    paragraphs.push(
      `Right now, my read on the market is **${regime}**${vix ? ` (${vix})` : ""}. ${interp}`
    );
  }

  // Paragraph 4: Top factor rankings + watchlist
  const watchSymbols = watchlist.map((w) => `**${w.symbol}**`);
  const topRankings = factorRankings?.top_10 ?? factorRankings?.rankings;
  if (Array.isArray(topRankings) && topRankings.length > 0) {
    const top5 = topRankings.slice(0, 5).map(
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      (r: any) => `**${r.symbol}** (${Math.round(r.composite_score)})`
    );
    let p4 = `Top ranked by composite score: ${top5.join(", ")}.`;
    if (watchSymbols.length > 0) {
      p4 += ` Currently watching ${watchSymbols.join(", ")}.`;
    }
    paragraphs.push(p4);
  } else if (watchSymbols.length > 0) {
    let p4 = `I'm currently watching ${watchSymbols.join(", ")}. `;
    const nearest = watchlist.find((w) => w.target_entry);
    if (nearest) {
      p4 += `Nearest entry target: ${nearest.symbol} at $${nearest.target_entry}.`;
    }
    paragraphs.push(p4);
  }

  return paragraphs.join("\n\n");
}

export function AboutMeSection() {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [memories, setMemories] = useState<Record<string, any>>({});
  const [watchlist, setWatchlist] = useState<WatchlistRow[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      const supabase = createClient();

      const [memRes, watchRes] = await Promise.all([
        supabase
          .from("agent_memory")
          .select("key, value")
          .in("key", MEMORY_KEYS),
        supabase
          .from("watchlist")
          .select("id, symbol, thesis, target_entry, target_exit")
          .order("added_at", { ascending: false }),
      ]);

      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const memMap: Record<string, any> = {};
      for (const row of memRes.data ?? []) {
        memMap[(row as { key: string }).key] = (row as { value: unknown }).value;
      }
      setMemories(memMap);
      setWatchlist((watchRes.data ?? []) as WatchlistRow[]);
      setLoading(false);
    }
    load();
  }, []);

  if (loading) {
    return (
      <Card>
        <CardContent className="p-8 space-y-4">
          <Skeleton className="h-5 w-48" />
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-3/4" />
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-5/6" />
        </CardContent>
      </Card>
    );
  }

  const bio = buildBio(memories, watchlist);

  if (!bio) {
    return (
      <p className="text-center text-muted-foreground py-8">
        Monet hasn&apos;t built its profile yet.
      </p>
    );
  }

  return (
    <div className="space-y-6">
      <Card>
        <CardContent className="px-8 py-10">
          <div className="max-w-2xl space-y-5 text-[15px] leading-7 text-foreground/90">
            {bio.split("\n\n").map((paragraph, i) => (
              <p key={i} dangerouslySetInnerHTML={{ __html: formatBold(paragraph) }} />
            ))}
          </div>
        </CardContent>
      </Card>

      <div className="px-1">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-3">
          What I can do
        </h3>
        <div className="flex flex-wrap gap-2">
          {SKILLS.map((skill) => (
            <span
              key={skill}
              className="rounded-full border px-3 py-1 text-xs text-muted-foreground"
            >
              {skill}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}

/** Convert **text** markdown bold to <strong> tags for dangerouslySetInnerHTML. */
function formatBold(text: string): string {
  return text.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
}
