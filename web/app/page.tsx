import Link from "next/link";
import { createClient } from "@/lib/supabase/server";
import { redirect } from "next/navigation";
import { SetupChat } from "@/components/landing/setup-chat";

export default async function LandingPage() {
  const supabase = await createClient();
  const { data: { user } } = await supabase.auth.getUser();

  if (user) {
    redirect("/dashboard");
  }

  return (
    <div className="min-h-screen bg-background text-foreground">
      {/* Nav */}
      <nav className="flex items-center justify-between px-6 py-4 max-w-5xl mx-auto">
        <span className="text-lg font-bold tracking-tight">Monet</span>
        <div className="flex items-center gap-3">
          <Link
            href="/login"
            className="text-sm text-muted-foreground hover:text-foreground transition-colors"
          >
            Sign in
          </Link>
          <Link
            href="/signup"
            className="rounded-full bg-foreground text-background px-4 py-1.5 text-sm font-medium hover:opacity-90 transition-opacity"
          >
            Build Your Agent
          </Link>
        </div>
      </nav>

      {/* Hero — two-column */}
      <section className="max-w-5xl mx-auto px-6 pt-16 pb-20">
        <div className="grid md:grid-cols-2 gap-12 items-center">
          <div>
            <p className="text-sm font-medium text-muted-foreground mb-4 tracking-wider uppercase">
              AI-Native Quantitative Investing
            </p>
            <h1 className="text-4xl sm:text-5xl font-bold tracking-tight leading-[1.15]">
              Your Own AI
              <br />
              Quant Agent
            </h1>
            <p className="mt-6 text-lg text-muted-foreground leading-relaxed">
              Tell OpenClaw what you care about. In 2 minutes, you&apos;ll have a
              personalized quant agent scoring 900 stocks and trading with
              systematic discipline.
            </p>
            <div className="mt-8 flex items-center gap-4">
              <Link
                href="/signup"
                className="rounded-full bg-foreground text-background px-6 py-2.5 text-sm font-medium hover:opacity-90 transition-opacity"
              >
                Get Started — Free
              </Link>
              <Link
                href="/about"
                className="rounded-full border px-6 py-2.5 text-sm font-medium text-muted-foreground hover:text-foreground hover:border-foreground/30 transition-colors"
              >
                Learn More
              </Link>
            </div>
          </div>
          <div className="flex justify-center">
            <SetupChat />
          </div>
        </div>
      </section>

      {/* How it works */}
      <section className="max-w-4xl mx-auto px-6 pb-20">
        <div className="grid gap-6 sm:grid-cols-3">
          <div className="rounded-2xl border p-6 space-y-3">
            <div className="text-2xl">01</div>
            <h3 className="font-semibold">Talk to OpenClaw</h3>
            <p className="text-sm text-muted-foreground leading-relaxed">
              Tell OpenClaw your sectors, risk tolerance, and experience level.
              It configures everything — no forms, no dashboards, just a
              conversation.
            </p>
          </div>
          <div className="rounded-2xl border p-6 space-y-3">
            <div className="text-2xl">02</div>
            <h3 className="font-semibold">Get Your Own Agent</h3>
            <p className="text-sm text-muted-foreground leading-relaxed">
              In under 2 minutes, you get a dedicated quant agent that scores
              900 stocks on four factors, executes trades, and manages risk —
              all personalized to you.
            </p>
          </div>
          <div className="rounded-2xl border p-6 space-y-3">
            <div className="text-2xl">03</div>
            <h3 className="font-semibold">Customize Anytime</h3>
            <p className="text-sm text-muted-foreground leading-relaxed">
              Chat with your agent to adjust strategy, shift sector focus, or
              tune risk. It learns your preferences and improves its factor
              weights weekly.
            </p>
          </div>
        </div>
      </section>

      {/* Edge */}
      <section className="max-w-4xl mx-auto px-6 pb-20">
        <h2 className="text-2xl font-bold text-center mb-10">
          Why Your Own AI Agent Beats DIY Investing
        </h2>
        <div className="grid gap-4 sm:grid-cols-2">
          {[
            {
              label: "Breadth",
              desc: "Your agent scores 900 stocks in one pass — not 5 stocks you heard about on social media.",
            },
            {
              label: "Speed",
              desc: "It reacts to earnings overnight, hours before analyst revisions update.",
            },
            {
              label: "Discipline",
              desc: "No FOMO, no panic selling, no emotional attachment to positions.",
            },
            {
              label: "Consistency",
              desc: "Same rules every day. No strategy drift based on mood or market noise.",
            },
          ].map((item) => (
            <div
              key={item.label}
              className="flex gap-4 rounded-xl border p-5"
            >
              <div>
                <p className="font-semibold text-sm">{item.label}</p>
                <p className="text-sm text-muted-foreground mt-1 leading-relaxed">
                  {item.desc}
                </p>
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* Factors */}
      <section className="max-w-3xl mx-auto px-6 pb-20">
        <h2 className="text-2xl font-bold text-center mb-2">
          Four-Factor Composite Model
        </h2>
        <p className="text-sm text-muted-foreground text-center mb-10">
          Default starting weights — your agent adjusts these based on your
          preferences and weekly performance reviews.
        </p>
        <div className="space-y-3">
          {[
            { name: "Momentum", weight: 35, color: "bg-blue-500", desc: "Price trend strength" },
            { name: "Quality", weight: 30, color: "bg-emerald-500", desc: "Business durability" },
            { name: "Value", weight: 20, color: "bg-amber-500", desc: "Relative cheapness" },
            { name: "EPS Revision", weight: 15, color: "bg-purple-500", desc: "Where consensus is shifting" },
          ].map((f) => (
            <div key={f.name} className="flex items-center gap-4">
              <div className="w-24 text-sm font-medium shrink-0">{f.name}</div>
              <div className="flex-1 h-3 rounded-full bg-muted overflow-hidden">
                <div
                  className={`h-full rounded-full ${f.color}`}
                  style={{ width: `${f.weight * 2.5}%` }}
                />
              </div>
              <div className="w-10 text-right text-sm font-semibold tabular-nums">
                {f.weight}%
              </div>
              <div className="w-40 text-xs text-muted-foreground hidden sm:block">
                {f.desc}
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* CTA */}
      <section className="max-w-3xl mx-auto px-6 pb-24 text-center">
        <div className="rounded-2xl border p-10 space-y-4">
          <h2 className="text-2xl font-bold">Build your agent in 2 minutes.</h2>
          <p className="text-muted-foreground text-sm max-w-md mx-auto">
            No code. No configuration. Just a conversation.
          </p>
          <Link
            href="/signup"
            className="inline-block rounded-full bg-foreground text-background px-6 py-2.5 text-sm font-medium hover:opacity-90 transition-opacity mt-2"
          >
            Get Started — Free
          </Link>
        </div>
      </section>

      {/* Footer */}
      <footer className="border-t py-6 px-6">
        <div className="max-w-5xl mx-auto flex items-center justify-between text-xs text-muted-foreground">
          <span>Monet Agent</span>
          <span>Paper trading only. Not financial advice.</span>
        </div>
      </footer>
    </div>
  );
}
