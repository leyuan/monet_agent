import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";

// AI super-cycle data for the /ai-cycle page.
// `latest` = current cards (from agent_memory); `history` = trend time series.
export async function GET() {
  try {
    const supabase = await createClient();

    const [durability, bubble, capex, history] = await Promise.all([
      supabase.from("agent_memory").select("value").eq("key", "ai_cycle_durability").maybeSingle(),
      supabase.from("agent_memory").select("value").eq("key", "ai_bubble_risk").maybeSingle(),
      supabase.from("agent_memory").select("value").eq("key", "ai_capex_tracker").maybeSingle(),
      supabase
        .from("ai_cycle_snapshots")
        .select(
          "snapshot_date, cycle_score, phase, bubble_score, bubble_level, capex_direction, hyperscaler_capex_yoy, memory_capex_yoy, layers_participating",
        )
        .order("snapshot_date", { ascending: true })
        .limit(180),
    ]);

    return NextResponse.json({
      latest: {
        durability: durability.data?.value ?? null,
        bubble: bubble.data?.value ?? null,
        capex: capex.data?.value ?? null,
      },
      history: history.data ?? [],
    });
  } catch {
    return NextResponse.json({ error: "Failed to load AI cycle data" }, { status: 500 });
  }
}
