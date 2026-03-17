"use client";

import { useState, useRef, useEffect } from "react";
import Link from "next/link";

type Message = {
  role: "assistant" | "user";
  content: string;
  type?: "loading" | "credentials";
};

const SECTORS = [
  "Technology",
  "Healthcare",
  "Energy",
  "Financials",
  "Consumer",
  "Industrial",
];

const RISK_OPTIONS = ["Conservative", "Moderate", "Aggressive"];
const EXPERIENCE_OPTIONS = ["New to it", "Some experience", "Very experienced"];

const LOADING_STEPS = [
  "Setting up your universe...",
  "Configuring factor weights...",
  "Deploying your agent...",
];

export function SetupChat() {
  const [step, setStep] = useState(0);
  const [sectors, setSectors] = useState<string[]>([]);
  const [risk, setRisk] = useState("");
  const [experience, setExperience] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [typing, setTyping] = useState(false);
  const [loadingLine, setLoadingLine] = useState(-1);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Scroll to bottom on new messages
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, typing, loadingLine]);

  // Initial greeting
  useEffect(() => {
    setTyping(true);
    const t = setTimeout(() => {
      setMessages([
        {
          role: "assistant",
          content:
            "Hi! I'm OpenClaw. I'll set up your own AI quant agent in about 2 minutes. What sectors are you most interested in?",
        },
      ]);
      setTyping(false);
      setStep(1);
    }, 1500);
    return () => clearTimeout(t);
  }, []);

  function addAssistantMessage(content: string, extra?: Partial<Message>) {
    return new Promise<void>((resolve) => {
      setTyping(true);
      setTimeout(() => {
        setMessages((prev) => [...prev, { role: "assistant", content, ...extra }]);
        setTyping(false);
        resolve();
      }, 1500);
    });
  }

  async function handleSectorSubmit() {
    if (sectors.length === 0) return;
    setMessages((prev) => [
      ...prev,
      { role: "user", content: sectors.join(", ") },
    ]);
    setStep(0); // disable chips while typing
    await addAssistantMessage(
      `Got it — ${sectors.join(", ")}. How would you describe your risk tolerance?`
    );
    setStep(2);
  }

  async function handleRiskSelect(value: string) {
    setRisk(value);
    setMessages((prev) => [...prev, { role: "user", content: value }]);
    setStep(0);
    await addAssistantMessage(
      "And how familiar are you with quantitative investing?"
    );
    setStep(3);
  }

  async function handleExperienceSelect(value: string) {
    setExperience(value);
    setMessages((prev) => [...prev, { role: "user", content: value }]);
    setStep(0);
    setTyping(true);

    // Fake loading sequence
    setTimeout(() => {
      setTyping(false);
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: "Creating your agent...", type: "loading" },
      ]);
      setLoadingLine(0);
    }, 1500);

    // Reveal loading steps
    setTimeout(() => setLoadingLine(1), 2100);
    setTimeout(() => setLoadingLine(2), 2700);

    // Show credentials
    setTimeout(() => {
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: "Your agent is ready! Here's how to access it:",
          type: "credentials",
        },
      ]);
      setStep(5);
    }, 3600);
  }

  return (
    <div className="w-full max-w-lg rounded-2xl border bg-card shadow-lg overflow-hidden">
      {/* Header */}
      <div className="px-4 py-3 border-b flex items-center gap-2">
        <div className="w-2 h-2 rounded-full bg-emerald-500" />
        <span className="text-sm font-medium">OpenClaw</span>
      </div>

      {/* Messages */}
      <div ref={scrollRef} className="p-4 space-y-3 h-[380px] overflow-y-auto">
        {messages.map((msg, i) => {
          if (msg.type === "loading") {
            return (
              <div key={i} className="flex justify-start">
                <div className="rounded-2xl rounded-tl-sm bg-muted px-4 py-3 max-w-[85%] space-y-1.5">
                  {LOADING_STEPS.map((line, j) => (
                    <div
                      key={j}
                      className={`text-sm transition-opacity duration-300 ${
                        j <= loadingLine ? "opacity-100" : "opacity-0"
                      }`}
                    >
                      {line}{" "}
                      {j <= loadingLine && (
                        <span className="text-emerald-500">✓</span>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            );
          }

          if (msg.type === "credentials") {
            return (
              <div key={i} className="flex flex-col gap-2 justify-start">
                <div className="rounded-2xl rounded-tl-sm bg-muted px-4 py-3 max-w-[85%]">
                  <p className="text-sm">{msg.content}</p>
                </div>
                <div className="rounded-xl border bg-card p-4 max-w-[85%] space-y-2 font-mono text-xs">
                  <div>
                    <span className="text-muted-foreground">URL: </span>
                    monet-abc123.openclaw.ai
                  </div>
                  <div>
                    <span className="text-muted-foreground">Username: </span>
                    investor@demo.com
                  </div>
                  <div>
                    <span className="text-muted-foreground">Password: </span>
                    ••••••••
                  </div>
                  <Link
                    href="/signup"
                    className="inline-block mt-2 rounded-full bg-foreground text-background px-4 py-1.5 text-xs font-medium hover:opacity-90 transition-opacity font-sans"
                  >
                    Open Dashboard →
                  </Link>
                </div>
              </div>
            );
          }

          return (
            <div
              key={i}
              className={`flex ${
                msg.role === "user" ? "justify-end" : "justify-start"
              }`}
            >
              <div
                className={`rounded-2xl px-4 py-2.5 max-w-[85%] text-sm leading-relaxed ${
                  msg.role === "user"
                    ? "rounded-tr-sm bg-foreground text-background"
                    : "rounded-tl-sm bg-muted"
                }`}
              >
                {msg.content}
              </div>
            </div>
          );
        })}

        {/* Typing indicator */}
        {typing && (
          <div className="flex justify-start">
            <div className="rounded-2xl rounded-tl-sm bg-muted px-4 py-2.5">
              <div className="flex gap-1">
                <span className="w-1.5 h-1.5 rounded-full bg-muted-foreground/50 animate-bounce [animation-delay:0ms]" />
                <span className="w-1.5 h-1.5 rounded-full bg-muted-foreground/50 animate-bounce [animation-delay:150ms]" />
                <span className="w-1.5 h-1.5 rounded-full bg-muted-foreground/50 animate-bounce [animation-delay:300ms]" />
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Input area — chip selectors */}
      <div className="px-4 py-3 border-t min-h-[60px]">
        {step === 1 && (
          <div className="space-y-2">
            <div className="flex flex-wrap gap-2">
              {SECTORS.map((s) => (
                <button
                  key={s}
                  onClick={() =>
                    setSectors((prev) =>
                      prev.includes(s)
                        ? prev.filter((x) => x !== s)
                        : prev.length < 3
                        ? [...prev, s]
                        : prev
                    )
                  }
                  className={`rounded-full border px-3 py-1 text-xs font-medium transition-colors ${
                    sectors.includes(s)
                      ? "bg-foreground text-background border-foreground"
                      : "hover:border-foreground/40"
                  }`}
                >
                  {s}
                </button>
              ))}
            </div>
            {sectors.length > 0 && (
              <button
                onClick={handleSectorSubmit}
                className="rounded-full bg-foreground text-background px-4 py-1 text-xs font-medium hover:opacity-90 transition-opacity"
              >
                Continue →
              </button>
            )}
          </div>
        )}

        {step === 2 && (
          <div className="flex flex-wrap gap-2">
            {RISK_OPTIONS.map((r) => (
              <button
                key={r}
                onClick={() => handleRiskSelect(r)}
                className="rounded-full border px-3 py-1 text-xs font-medium hover:border-foreground/40 transition-colors"
              >
                {r}
              </button>
            ))}
          </div>
        )}

        {step === 3 && (
          <div className="flex flex-wrap gap-2">
            {EXPERIENCE_OPTIONS.map((e) => (
              <button
                key={e}
                onClick={() => handleExperienceSelect(e)}
                className="rounded-full border px-3 py-1 text-xs font-medium hover:border-foreground/40 transition-colors"
              >
                {e}
              </button>
            ))}
          </div>
        )}

        {step === 5 && (
          <p className="text-xs text-muted-foreground text-center">
            Try it yourself — sign up and explore your dashboard.
          </p>
        )}

        {step === 0 && !typing && messages.length === 0 && (
          <p className="text-xs text-muted-foreground text-center">Loading...</p>
        )}
      </div>
    </div>
  );
}
