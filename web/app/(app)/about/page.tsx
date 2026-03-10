"use client";

import { AboutMeSection } from "@/components/trading/about-me";
import { PerformanceCard, LifecycleCard } from "@/components/trading/performance-card";

export default function AboutPage() {
  return (
    <div className="h-full overflow-y-auto p-6 space-y-6">
      <h1 className="text-2xl font-semibold">About Me</h1>
      <div className="grid gap-6 lg:grid-cols-[1fr_280px]">
        <AboutMeSection />
        <div className="lg:sticky lg:top-6 lg:self-start space-y-4">
          <PerformanceCard />
          <LifecycleCard />
        </div>
      </div>
    </div>
  );
}
