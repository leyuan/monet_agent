"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  AssistantRuntimeProvider,
  unstable_useRemoteThreadListRuntime as useRemoteThreadListRuntime,
  type unstable_RemoteThreadListAdapter as RemoteThreadListAdapter,
} from "@assistant-ui/react";
import { createAssistantStream } from "assistant-stream";
import {
  createThread,
  searchThreads,
  deleteThread as deleteThreadApi,
  updateThreadMetadata,
  generateThreadTitle,
} from "@/lib/chat-api";
import {
  useLangGraphBridge,
  waitForAutoCreatedThread,
} from "@/lib/langgraph-bridge";
import { createClient } from "@/lib/supabase/client";
import type { LangChainMessage } from "@assistant-ui/react-langgraph";

function useLangGraphStreamRuntime(userId: string, authToken: string | null) {
  return useLangGraphBridge(userId, authToken);
}

function useThreadListAdapter(): RemoteThreadListAdapter {
  return useMemo<RemoteThreadListAdapter>(
    () => ({
      async list() {
        const threads = await searchThreads();
        return {
          threads: threads
            .filter((t) => {
              const values = t.values as { messages?: unknown[] } | null;
              return values?.messages && values.messages.length > 0;
            })
            .map((t) => {
              const metadataTitle = (t.metadata as Record<string, unknown> | undefined)?.title;
              let title: string | undefined;
              if (typeof metadataTitle === "string" && metadataTitle.length > 0) {
                title = metadataTitle;
              } else {
                const values = t.values as { messages?: LangChainMessage[] } | null;
                const firstMsg = values?.messages?.[0];
                title = firstMsg && typeof firstMsg.content === "string"
                  ? firstMsg.content.slice(0, 60)
                  : undefined;
              }
              return {
                status: "regular" as const,
                remoteId: t.thread_id,
                externalId: t.thread_id,
                title,
              };
            }),
        };
      },
      async initialize(_localId: string) {
        const autoThreadId = await waitForAutoCreatedThread();
        if (autoThreadId) {
          return { remoteId: autoThreadId, externalId: autoThreadId };
        }
        const thread = await createThread();
        return { remoteId: thread.thread_id, externalId: thread.thread_id };
      },
      async rename(remoteId: string, newTitle: string) {
        await updateThreadMetadata(remoteId, { title: newTitle });
      },
      async archive() {},
      async unarchive() {},
      async delete(remoteId: string) {
        try { await deleteThreadApi(remoteId); } catch {}
      },
      async generateTitle(remoteId, unstable_messages) {
        return createAssistantStream(async (controller) => {
          try {
            const simplifiedMessages = unstable_messages
              .filter((m) => m.role === "user" || m.role === "assistant")
              .slice(0, 6)
              .map((m) => ({
                role: m.role as string,
                content: m.content
                  .filter((part: { type: string }): part is { type: "text"; text: string } => part.type === "text")
                  .map((part: { type: "text"; text: string }) => part.text)
                  .join(" "),
              }))
              .filter((m) => m.content.length > 0);
            if (simplifiedMessages.length === 0) return;
            const title = await generateThreadTitle(simplifiedMessages);
            await updateThreadMetadata(remoteId, { title });
            controller.appendText(title);
          } catch (error) {
            console.error("Failed to generate title:", error);
          }
        });
      },
      async fetch(threadId: string) {
        return { status: "regular" as const, remoteId: threadId, externalId: threadId };
      },
    }),
    [],
  );
}

interface ChatProviderProps {
  children: React.ReactNode;
  userId: string;
}

export function ChatProvider({ children, userId }: ChatProviderProps) {
  const [authToken, setAuthToken] = useState<string | null>(null);
  const [isReady, setIsReady] = useState(false);

  useEffect(() => {
    const supabase = createClient();
    supabase.auth.getSession().then(({ data: { session } }) => {
      setAuthToken(session?.access_token ?? null);
      setIsReady(true);
    });
    const { data: { subscription } } = supabase.auth.onAuthStateChange((_event, session) => {
      setAuthToken(session?.access_token ?? null);
    });
    return () => subscription.unsubscribe();
  }, []);

  const adapter = useThreadListAdapter();

  const tokenRef = useRef(authToken);
  tokenRef.current = authToken;

  const runtime = useRemoteThreadListRuntime({
    runtimeHook: function LangGraphRuntime() {
      return useLangGraphStreamRuntime(userId, tokenRef.current);
    },
    adapter,
  });

  if (!isReady) {
    return (
      <div className="flex h-dvh items-center justify-center">
        <div className="animate-pulse text-muted-foreground">Loading...</div>
      </div>
    );
  }

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      {children}
    </AssistantRuntimeProvider>
  );
}
