"use client";

import { ChatProvider } from "@/components/assistant";
import { Thread } from "@/components/assistant-ui/thread";
import { ThreadList } from "@/components/assistant-ui/thread-list";

export function ChatView({ userId }: { userId: string }) {
  return (
    <ChatProvider userId={userId}>
      <div className="flex h-full">
        <aside className="hidden w-64 flex-col border-r bg-background lg:flex">
          <div className="flex h-14 items-center border-b px-4">
            <h2 className="font-semibold text-sm">Conversations</h2>
          </div>
          <div className="flex-1 overflow-y-auto">
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
