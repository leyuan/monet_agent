"use client";

import { useState, useCallback, useRef, useEffect, useMemo } from "react";
import { useStream } from "@langchain/langgraph-sdk/react";
import type {
  Message,
  Checkpoint,
  Interrupt,
  Command,
} from "@langchain/langgraph-sdk";
import {
  useExternalStoreRuntime,
  useExternalMessageConverter,
  useAui,
} from "@assistant-ui/react";
import type { ThreadMessage, AppendMessage } from "@assistant-ui/react";
import { convertLangChainMessages } from "@assistant-ui/react-langgraph";

const ASSISTANT_ID =
  process.env["NEXT_PUBLIC_LANGGRAPH_ASSISTANT_ID"] ?? "stock_agent";
const API_URL = process.env["NEXT_PUBLIC_LANGGRAPH_API_URL"]!;

type CheckpointRef = Omit<Checkpoint, "thread_id">;

export interface BridgeExtras {
  interrupt: Interrupt | undefined;
  submit: (
    values: Record<string, unknown> | null | undefined,
    options?: {
      command?: Command;
      config?: Record<string, unknown>;
      checkpoint?: CheckpointRef | null;
    },
  ) => Promise<void>;
}

let _autoCreatedThreadId: string | null = null;
let _pendingThreadResolve: ((id: string) => void) | null = null;

export async function waitForAutoCreatedThread(): Promise<string | null> {
  if (_autoCreatedThreadId) {
    const id = _autoCreatedThreadId;
    _autoCreatedThreadId = null;
    return id;
  }
  return new Promise<string | null>((resolve) => {
    _pendingThreadResolve = resolve;
    setTimeout(() => {
      if (_pendingThreadResolve === resolve) {
        _pendingThreadResolve = null;
        resolve(null);
      }
    }, 15000);
  });
}

function notifyThreadCreated(threadId: string) {
  if (_pendingThreadResolve) {
    _pendingThreadResolve(threadId);
    _pendingThreadResolve = null;
  } else {
    _autoCreatedThreadId = threadId;
  }
}

function getFirstAiIdInLastTurn(msgs: Message[]): string | null {
  let firstAiIdx = -1;
  for (let i = msgs.length - 1; i >= 0; i--) {
    if (msgs[i].type === "human") break;
    if (msgs[i].type === "ai") firstAiIdx = i;
  }
  return firstAiIdx >= 0 ? (msgs[firstAiIdx]?.id ?? null) : null;
}

function getMessageContent(
  msg: AppendMessage,
): string | Array<Record<string, unknown>> {
  const allContent = [
    ...msg.content,
    ...(msg.attachments?.flatMap((a) => a.content) ?? []),
  ];
  const content = allContent
    .map((part) => {
      if (part.type === "text") {
        return { type: "text" as const, text: part.text };
      }
      if (part.type === "image") {
        return { type: "image_url" as const, image_url: { url: part.image } };
      }
      return null;
    })
    .filter(Boolean) as Array<Record<string, unknown>>;

  if (content.length === 1 && content[0]?.type === "text") {
    return (content[0] as { type: string; text: string }).text ?? "";
  }
  return content;
}

export function useLangGraphBridge(userId: string, authToken: string | null) {
  const aui = useAui();

  const useStreamCreatedRef = useRef(false);

  const [threadId, setThreadId] = useState<string | null>(() => {
    try {
      return aui.threadListItem().getState().externalId ?? null;
    } catch {
      return null;
    }
  });

  const defaultHeaders = useMemo(
    () => (authToken ? { Authorization: `Bearer ${authToken}` } : {}),
    [authToken],
  );

  const stream = useStream({
    apiUrl: API_URL,
    assistantId: ASSISTANT_ID,
    threadId,
    defaultHeaders,
    onThreadId: (newId: string) => {
      useStreamCreatedRef.current = true;
      setThreadId(newId);
      notifyThreadCreated(newId);
    },
    reconnectOnMount: true,
    onError: (error) => {
      console.error("[bridge] useStream error:", error);
    },
  });

  const streamRef = useRef(stream);
  const threadIdRef = useRef(threadId);
  useEffect(() => {
    streamRef.current = stream;
  }, [stream]);
  useEffect(() => {
    threadIdRef.current = threadId;
  }, [threadId]);

  useEffect(() => {
    const unsub = aui.subscribe(() => {
      try {
        const state = aui.threadListItem().getState();
        if (state.externalId && state.externalId !== threadIdRef.current) {
          if (useStreamCreatedRef.current) {
            useStreamCreatedRef.current = false;
            return;
          }
          setThreadId(state.externalId);
        }
      } catch {
        // threadListItem may not be available yet
      }
    });
    return unsub;
  }, [aui]);

  const [branchOverride, setBranchOverride] = useState<Message[] | null>(null);

  const historyByMsgId = useRef(
    new Map<string, { messages: Message[]; checkpoint: CheckpointRef }>(),
  );
  const streamMessagesByMsgId = useRef(new Map<string, Message[]>());

  const prevStreamMsgsRef = useRef(stream.messages);
  if (prevStreamMsgsRef.current !== stream.messages) {
    prevStreamMsgsRef.current = stream.messages;
    if (branchOverride !== null) {
      setBranchOverride(null);
    }
  }

  const displayMessages = branchOverride ?? stream.messages;

  const refreshBranchMap = useCallback(async () => {
    const tid = threadIdRef.current;
    const s = streamRef.current;
    if (!tid) return;

    try {
      const rawHistory = await s.client.threads.getHistory(tid, {
        limit: 200,
      });
      if (!rawHistory?.length) return;

      for (const state of rawHistory) {
        const vals = state as {
          values?: { messages?: Message[] };
          checkpoint?: Checkpoint;
        };
        const msgs = vals.values?.messages;
        const cp = vals.checkpoint;
        if (!msgs?.length || !cp) continue;

        const { thread_id: _, ...checkpoint } = cp;
        const entry = { messages: msgs, checkpoint };

        const lastMsg = msgs[msgs.length - 1];
        if (lastMsg?.id) {
          historyByMsgId.current.set(lastMsg.id, entry);
        }

        const firstAiId = getFirstAiIdInLastTurn(msgs);
        if (firstAiId && firstAiId !== lastMsg?.id) {
          historyByMsgId.current.set(firstAiId, entry);
        }
      }
    } catch (e) {
      console.error("[bridge] Failed to fetch raw history:", e);
    }
  }, []);

  useEffect(() => {
    if (!stream.isLoading && threadId) {
      refreshBranchMap();
    }
  }, [stream.isLoading, threadId, refreshBranchMap]);

  useEffect(() => {
    if (!stream.isLoading && stream.messages.length > 0) {
      const msgs = stream.messages;
      const copy = [...msgs];

      const lastMsg = msgs[msgs.length - 1];
      if (lastMsg?.id) {
        streamMessagesByMsgId.current.set(lastMsg.id, copy);
      }

      const firstAiId = getFirstAiIdInLastTurn(msgs);
      if (firstAiId && firstAiId !== lastMsg?.id) {
        streamMessagesByMsgId.current.set(firstAiId, copy);
      }
    }
  }, [stream.isLoading, stream.messages]);

  const threadMessages = useExternalMessageConverter({
    callback: convertLangChainMessages,
    messages: displayMessages as Array<
      Parameters<typeof convertLangChainMessages>[0]
    >,
    isRunning: stream.isLoading,
  });

  const config = useMemo(
    () => ({
      configurable: {
        user_id: userId,
      },
    }),
    [userId],
  );
  const configRef = useRef(config);
  useEffect(() => {
    configRef.current = config;
  }, [config]);

  const findCheckpoint = useCallback(
    async (
      parentId: string,
    ): Promise<{ checkpoint: CheckpointRef } | undefined> => {
      const s = streamRef.current;
      const tid = threadIdRef.current;
      if (!tid) return undefined;

      try {
        const states = await s.client.threads.getHistory(tid, { limit: 200 });
        for (const state of states) {
          const vals = state as {
            values?: { messages?: Message[] };
            checkpoint?: Checkpoint;
          };
          const msgs = vals.values?.messages;
          if (!msgs?.length || !vals.checkpoint) continue;

          const lastMsg = msgs[msgs.length - 1];

          if (lastMsg.type !== "human") {
            const firstAiId = getFirstAiIdInLastTurn(msgs);
            if (firstAiId === parentId) {
              const { thread_id: _, ...checkpoint } = vals.checkpoint;
              return { checkpoint };
            }
          }

          if (lastMsg.id === parentId) {
            const { thread_id: _, ...checkpoint } = vals.checkpoint;
            return { checkpoint };
          }
        }
      } catch (e) {
        console.error("[bridge] Failed to fetch history:", e);
      }

      return undefined;
    },
    [],
  );

  const branchOverrideRef = useRef(branchOverride);
  useEffect(() => {
    branchOverrideRef.current = branchOverride;
  }, [branchOverride]);

  const onNew = useCallback(async (msg: AppendMessage) => {
    const content = getMessageContent(msg);

    const override = branchOverrideRef.current;
    if (override) {
      const lastMsg = override[override.length - 1];
      const entry = lastMsg?.id
        ? historyByMsgId.current.get(lastMsg.id)
        : undefined;
      if (entry) {
        await streamRef.current.submit(
          { messages: [{ type: "human", content } as Message] },
          { config: configRef.current, checkpoint: entry.checkpoint },
        );
        return;
      }
    }

    await streamRef.current.submit(
      { messages: [{ type: "human", content } as Message] },
      { config: configRef.current },
    );
  }, []);

  const onEdit = useCallback(
    async (msg: AppendMessage) => {
      const content = getMessageContent(msg);

      if (msg.parentId) {
        const result = await findCheckpoint(msg.parentId);
        if (result) {
          await streamRef.current.submit(
            { messages: [{ type: "human", content } as Message] },
            { config: configRef.current, checkpoint: result.checkpoint },
          );
          return;
        }
      }

      await streamRef.current.submit(
        { messages: [{ type: "human", content } as Message] },
        { config: configRef.current },
      );
    },
    [findCheckpoint],
  );

  const onReload = useCallback(
    async (parentId: string | null) => {
      if (parentId) {
        const result = await findCheckpoint(parentId);
        if (result) {
          await streamRef.current.submit(null, {
            config: configRef.current,
            checkpoint: result.checkpoint,
          });
          return;
        }
      }

      await streamRef.current.submit(null, { config: configRef.current });
    },
    [findCheckpoint],
  );

  const setMessages = useCallback((messages: readonly ThreadMessage[]) => {
    const lastMsg = messages[messages.length - 1];
    if (!lastMsg?.id) return;

    const streamMsgs = streamMessagesByMsgId.current.get(lastMsg.id);
    if (streamMsgs) {
      setBranchOverride(streamMsgs);
      return;
    }

    const entry = historyByMsgId.current.get(lastMsg.id);
    if (entry) {
      setBranchOverride(entry.messages);
      return;
    }
  }, []);

  const onCancel = useCallback(async () => {
    await streamRef.current.stop();
  }, []);

  return useExternalStoreRuntime({
    isRunning: stream.isLoading,
    messages: threadMessages,
    setMessages,
    onNew,
    onEdit,
    onReload,
    onCancel,
    extras: {
      interrupt: stream.interrupt,
      submit: stream.submit,
    } as BridgeExtras,
  });
}
