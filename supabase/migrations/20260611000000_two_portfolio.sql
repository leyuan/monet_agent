-- Two-portfolio support: Quant Core (slug 'quant') + Conviction (slug 'conviction').
-- Existing rows belong to the original systematic strategy => backfill to 'quant'.

-- ── trades: tag every trade with its portfolio ──
ALTER TABLE trades ADD COLUMN IF NOT EXISTS portfolio text NOT NULL DEFAULT 'quant';
CREATE INDEX IF NOT EXISTS idx_trades_portfolio ON trades(portfolio);

-- ── equity_snapshots: one equity curve per portfolio ──
-- The table currently has a UNIQUE constraint on snapshot_date alone (auto-named
-- equity_snapshots_snapshot_date_key) and upserts on_conflict=snapshot_date.
-- Replace it with a composite UNIQUE (portfolio, snapshot_date) so each portfolio
-- keeps its own daily row. The primary key remains the surrogate `id`.
ALTER TABLE equity_snapshots ADD COLUMN IF NOT EXISTS portfolio text NOT NULL DEFAULT 'quant';
ALTER TABLE equity_snapshots DROP CONSTRAINT IF EXISTS equity_snapshots_snapshot_date_key;
ALTER TABLE equity_snapshots
  ADD CONSTRAINT equity_snapshots_portfolio_date_key UNIQUE (portfolio, snapshot_date);

DROP INDEX IF EXISTS idx_equity_snapshots_date;
CREATE INDEX IF NOT EXISTS idx_equity_snapshots_portfolio_date
  ON equity_snapshots(portfolio, snapshot_date DESC);
