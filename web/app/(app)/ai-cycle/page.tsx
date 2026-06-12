"use client";

import { AiCycleDurabilityCard } from "@/components/trading/AiCycleDurabilityCard";
import { AiBubbleRiskCard } from "@/components/trading/AiBubbleRiskCard";
import { AiCapexTrendCard } from "@/components/trading/AiCapexTrendCard";
import { CycleHistoryChart } from "@/components/trading/CycleHistoryChart";
import { CycleSignalsCard } from "@/components/trading/CycleSignalsCard";

export default function AiCyclePage() {
  return (
    <div className="h-full overflow-y-auto p-6 space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">AI Super-Cycle</h1>
        <p className="text-sm text-muted-foreground mt-1 max-w-2xl">
          Tracking whether the AI-infrastructure buildout keeps expanding — hyperscaler
          capex, memory/storage demand, and how durable vs overheated the cycle is.
          This is the research engine behind the Conviction portfolio.
        </p>
      </div>

      {/* Top row — the three live readings */}
      <div className="grid gap-4 md:grid-cols-3">
        <AiCycleDurabilityCard />
        <AiCapexTrendCard />
        <AiBubbleRiskCard />
      </div>

      {/* Qualitative cycle signals — the narrative the quant misses */}
      <CycleSignalsCard />

      {/* Trend over time */}
      <CycleHistoryChart />
    </div>
  );
}
