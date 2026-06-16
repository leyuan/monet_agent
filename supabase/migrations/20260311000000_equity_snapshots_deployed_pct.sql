-- Add deployed_pct column to equity_snapshots for meaningful alpha tracking.
-- Alpha is only meaningful when >50% of portfolio is deployed in positions.
--
-- NOTE: this migration is timestamped BEFORE the one that CREATEs equity_snapshots
-- (20260311183524_add_equity_snapshots.sql). On cloud the table already existed when
-- this ran, so the column was added. On a fresh local apply the table doesn't exist yet,
-- so we guard the ALTER to no-op; the column is then provided by the CREATE TABLE itself.
-- Order-tolerant + idempotent in both directions.
DO $$
BEGIN
  IF EXISTS (
    SELECT FROM information_schema.tables WHERE table_name = 'equity_snapshots'
  ) THEN
    ALTER TABLE equity_snapshots ADD COLUMN IF NOT EXISTS deployed_pct numeric DEFAULT 0;
  END IF;
END $$;
