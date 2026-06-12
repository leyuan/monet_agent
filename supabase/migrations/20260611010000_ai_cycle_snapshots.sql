-- AI super-cycle daily history. One row/day; powers trend charts on the AI Cycle page.
-- agent_memory keys (ai_cycle_durability, ai_bubble_risk, ai_capex_tracker) stay as
-- the "latest" snapshot for cards; this table is the time series.
CREATE TABLE IF NOT EXISTS ai_cycle_snapshots (
  snapshot_date date PRIMARY KEY,
  cycle_score int,
  phase text,
  bubble_score int,
  bubble_level text,
  capex_direction text,
  hyperscaler_capex_yoy numeric(8,2),
  memory_capex_yoy numeric(8,2),
  layers_participating int,
  signals jsonb,
  created_at timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ai_cycle_snapshots_date
  ON ai_cycle_snapshots(snapshot_date DESC);

-- Mirror agent_memory: authenticated users can read; the agent writes via the
-- service role (which bypasses RLS). Keeps the table off the anon role.
ALTER TABLE ai_cycle_snapshots ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Authenticated users can read ai_cycle_snapshots"
  ON ai_cycle_snapshots FOR SELECT TO authenticated USING (true);
