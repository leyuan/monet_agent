"use client";

import { makeAssistantToolUI } from "@assistant-ui/react";
import { LoaderIcon, CheckCircleIcon, AlertCircleIcon } from "lucide-react";

export const ToolFallback = makeAssistantToolUI({
  toolName: "*",
  render: (input) => {
    const name = input.toolName;
    const isRunning = input.status?.type === "running";
    const isError = input.status?.type === "incomplete";

    return (
      <div className="my-2 flex items-center gap-2 rounded-lg border bg-muted/50 px-3 py-2 text-sm text-muted-foreground">
        {isRunning ? (
          <LoaderIcon className="size-4 animate-spin" />
        ) : isError ? (
          <AlertCircleIcon className="size-4 text-destructive" />
        ) : (
          <CheckCircleIcon className="size-4 text-green-600" />
        )}
        <span className="font-mono text-xs">{name}</span>
      </div>
    );
  },
});
