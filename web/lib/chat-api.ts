import { Client } from "@langchain/langgraph-sdk";
import { createClient as createSupabaseClient } from "@/lib/supabase/client";

const createLangGraphClient = async () => {
  const supabase = createSupabaseClient();
  const {
    data: { session },
  } = await supabase.auth.getSession();
  const token = session?.access_token;

  return new Client({
    apiUrl: process.env["NEXT_PUBLIC_LANGGRAPH_API_URL"]!,
    defaultHeaders: token ? { Authorization: `Bearer ${token}` } : {},
  });
};

export const createThread = async (
  metadata?: Record<string, string>,
) => {
  const client = await createLangGraphClient();
  return client.threads.create({ metadata });
};

export const getThreadState = async (threadId: string) => {
  const client = await createLangGraphClient();
  return client.threads.getState(threadId);
};

export const searchThreads = async () => {
  const client = await createLangGraphClient();
  return client.threads.search({
    limit: 100,
    sortBy: "updated_at",
    sortOrder: "desc",
  });
};

export const deleteThread = async (threadId: string) => {
  const client = await createLangGraphClient();
  return client.threads.delete(threadId);
};

export const updateThreadMetadata = async (
  threadId: string,
  metadata: Record<string, string>,
) => {
  const client = await createLangGraphClient();
  return client.threads.update(threadId, { metadata });
};

export const generateThreadTitle = async (
  messages: Array<{ role: string; content: string }>,
): Promise<string> => {
  const baseUrl =
    typeof window !== "undefined"
      ? window.location.origin
      : "http://localhost:3000";
  const res = await fetch(`${baseUrl}/api/generate-title`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ messages }),
  });
  const data = (await res.json()) as { title: string };
  return data.title;
};
