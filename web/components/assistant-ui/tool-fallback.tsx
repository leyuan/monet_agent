"use client";

import { makeAssistantToolUI } from "@assistant-ui/react";
import { LoaderIcon, CheckCircleIcon, AlertCircleIcon } from "lucide-react";

const TOOL_LABELS: Record<string, string> = {
  internet_search: "Searching the web",
  get_stock_quote: "Fetching quote",
  get_my_portfolio: "Loading portfolio",
  query_database: "Querying database",
  company_profile: "Analyzing company",
  sector_analysis: "Analyzing sectors",
  peer_comparison: "Comparing peers",
  market_breadth: "Checking market breadth",
  submit_user_insight: "Noting insight",
  get_portfolio_state: "Loading portfolio",
  screen_stocks: "Screening stocks",
  fundamental_analysis: "Running fundamentals",
  technical_analysis: "Running technicals",
  earnings_calendar: "Checking earnings",
  read_file: "Reading file",
};

function getToolLabel(name: string, isRunning: boolean): string {
  const label = TOOL_LABELS[name];
  if (label) return isRunning ? `${label}...` : label;
  // Fallback: humanize the tool name
  const humanized = name.replace(/_/g, " ");
  return isRunning ? `Running ${humanized}...` : humanized;
}

export const ToolFallback = makeAssistantToolUI({
  toolName: "*",
  render: (input) => {
    const name = input.toolName;
    const isRunning = input.status?.type === "running";
    const isError = input.status?.type === "incomplete";
    const label = getToolLabel(name, isRunning);

    return (
      <div className="my-1.5 flex items-center gap-2 text-xs text-muted-foreground">
        {isRunning ? (
          <LoaderIcon className="size-3.5 animate-spin" />
        ) : isError ? (
          <AlertCircleIcon className="size-3.5 text-destructive" />
        ) : (
          <CheckCircleIcon className="size-3.5 text-green-600 dark:text-green-500" />
        )}
        <span>{label}</span>
      </div>
    );
  },
});
