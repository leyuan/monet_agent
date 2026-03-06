import { NextResponse } from "next/server";
import Anthropic from "@anthropic-ai/sdk";

const anthropic = new Anthropic();

export async function POST(request: Request) {
  try {
    const { messages } = (await request.json()) as {
      messages: Array<{ role: string; content: string }>;
    };

    const formatted = messages.slice(0, 6).map((m) => ({
      role: m.role as "user" | "assistant",
      content: m.content.slice(0, 500),
    }));

    const response = await anthropic.messages.create({
      model: "claude-haiku-4-5-20251001",
      max_tokens: 30,
      system:
        "Generate a concise 5-8 word title summarizing this conversation. Return only the title, no quotes or punctuation.",
      messages: formatted,
    });

    const block = response.content[0];
    const title =
      block.type === "text" ? block.text.trim() : "New Chat";
    return NextResponse.json({ title });
  } catch (error) {
    console.error("Title generation failed:", error);
    return NextResponse.json({ title: "New Chat" });
  }
}
