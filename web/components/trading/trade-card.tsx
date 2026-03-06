"use client";

import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";

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

export function TradeCard({ trade }: { trade: Trade }) {
  const isBuy = trade.side === "buy";
  const date = new Date(trade.created_at).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });

  return (
    <Card>
      <CardContent className="p-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className={cn(
              "rounded px-2 py-0.5 text-xs font-bold uppercase",
              isBuy ? "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200"
                    : "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200",
            )}>
              {trade.side}
            </span>
            <span className="font-mono font-semibold">{trade.symbol}</span>
            <span className="text-sm text-muted-foreground">
              {trade.quantity} shares
            </span>
          </div>
          <div className="text-right">
            <span className="text-xs text-muted-foreground">{date}</span>
            <div className="flex items-center gap-2">
              <span className={cn(
                "rounded px-1.5 py-0.5 text-xs",
                trade.status === "filled" ? "bg-green-100 text-green-800" : "bg-muted text-muted-foreground",
              )}>
                {trade.status}
              </span>
              {trade.filled_avg_price && (
                <span className="text-sm font-medium">
                  ${trade.filled_avg_price.toFixed(2)}
                </span>
              )}
            </div>
          </div>
        </div>
        {trade.thesis && (
          <p className="mt-2 text-sm text-muted-foreground">{trade.thesis}</p>
        )}
        {trade.confidence !== null && (
          <div className="mt-1 flex items-center gap-1">
            <span className="text-xs text-muted-foreground">Confidence:</span>
            <span className="text-xs font-medium">{(trade.confidence * 100).toFixed(0)}%</span>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
