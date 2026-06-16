CREATE TABLE equity_snapshots (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  snapshot_date date UNIQUE NOT NULL,
  portfolio_equity numeric(14,2) NOT NULL,
  portfolio_cash numeric(14,2) NOT NULL,
  spy_close numeric(14,4) NOT NULL,
  portfolio_cumulative_return numeric(8,4),
  spy_cumulative_return numeric(8,4),
  alpha numeric(8,4),
  deployed_pct numeric DEFAULT 0,
  created_at timestamptz DEFAULT now()
);

CREATE INDEX idx_equity_snapshots_date ON equity_snapshots(snapshot_date DESC);
