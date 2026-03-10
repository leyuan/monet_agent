"use client";

import { useState } from "react";
import { ChatProvider } from "@/components/assistant";
import { Thread } from "@/components/assistant-ui/thread";
import { ThreadList } from "@/components/assistant-ui/thread-list";
import { Button } from "@/components/ui/button";
import { MessageSquareIcon, XIcon } from "lucide-react";

export function ChatView({ userId }: { userId: string }) {
  const [sidebarOpen, setSidebarOpen] = useState(false);

  return (
    <ChatProvider userId={userId}>
      <div className="relative flex h-full">
        {/* Mobile sidebar toggle */}
        <Button
          variant="ghost"
          size="icon"
          className="absolute left-2 top-2 z-40 lg:hidden"
          onClick={() => setSidebarOpen(!sidebarOpen)}
        >
          {sidebarOpen ? <XIcon className="size-5" /> : <MessageSquareIcon className="size-5" />}
        </Button>

        {/* Mobile overlay */}
        {sidebarOpen && (
          <div
            className="fixed inset-0 z-30 bg-black/40 lg:hidden"
            onClick={() => setSidebarOpen(false)}
          />
        )}

        {/* Sidebar — always visible on lg, overlay on mobile when toggled */}
        <aside
          className={`absolute inset-y-0 left-0 z-30 w-64 flex-col border-r bg-background transition-transform lg:relative lg:flex lg:translate-x-0 ${
            sidebarOpen ? "flex translate-x-0" : "hidden -translate-x-full lg:flex"
          }`}
        >
          <div className="flex h-14 items-center border-b px-4 pl-12 lg:pl-4">
            <h2 className="font-semibold text-sm">Conversations</h2>
          </div>
          <div className="flex-1 overflow-y-auto" onClick={() => setSidebarOpen(false)}>
            <ThreadList />
          </div>
        </aside>

        <main className="flex-1">
          <Thread />
        </main>
      </div>
    </ChatProvider>
  );
}
