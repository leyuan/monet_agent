-- Fix exec_readonly_sql keyword guard: it used SUBSTRING matching, so legitimate
-- read-only queries containing 'created_at' / 'updated_at' were rejected because
-- 'CREATE' / 'UPDATE' appear as substrings. Since nearly every table has a
-- created_at/updated_at column (and the conformance review orders trades by
-- created_at), this blocked normal reads for both the chat agent and the reviewer.
--
-- Fix: match data-modifying keywords as WHOLE WORDS using Postgres word boundaries
-- (\y), so 'created_at'/'updated_at' are no longer false-positives while real
-- INSERT/UPDATE/DELETE/etc. statements are still blocked. SELECT-only is still enforced.
CREATE OR REPLACE FUNCTION exec_readonly_sql(query text)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
  result jsonb;
  normalized text;
BEGIN
  normalized := btrim(query);
  IF NOT (upper(normalized) LIKE 'SELECT%') THEN
    RAISE EXCEPTION 'Only SELECT queries are allowed';
  END IF;

  -- Whole-word match (\y = word boundary) so created_at/updated_at are not flagged.
  IF upper(normalized) ~ '\y(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|GRANT|REVOKE|COPY)\y' THEN
    RAISE EXCEPTION 'Query contains disallowed keywords';
  END IF;

  EXECUTE format('SELECT jsonb_agg(row_to_json(t)) FROM (%s) t', normalized) INTO result;
  RETURN COALESCE(result, '[]'::jsonb);
END;
$$;
