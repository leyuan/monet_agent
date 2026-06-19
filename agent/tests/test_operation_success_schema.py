"""Guard: every column the operation-success code probes must exist in the migration DDL
(supabase/migrations/*.sql) — the source of truth the live DB is built from."""
import pathlib
import re

MIGRATIONS = pathlib.Path(__file__).resolve().parents[2] / "supabase" / "migrations"

# (table, columns) the code depends on: build_probe_sql match cols + the fields classify reads.
REQUIRED = {
    "trades": {"id", "status", "filled_avg_price"},
    "agent_memory": {"key", "updated_at"},
    "agent_journal": {"id"},
    "watchlist": {"symbol"},
    "equity_snapshots": {"snapshot_date", "spy_close", "portfolio_equity"},
}

_KEYWORDS = {"primary", "unique", "constraint", "check", "foreign"}


def _schema() -> dict[str, set]:
    text = "\n".join(p.read_text() for p in sorted(MIGRATIONS.glob("*.sql")))
    cols: dict[str, set] = {}
    for m in re.finditer(r"create table(?:\s+if not exists)?\s+(?:public\.)?(\w+)\s*\((.*?)\);",
                         text, re.IGNORECASE | re.DOTALL):
        table, body = m.group(1).lower(), m.group(2)
        for line in body.splitlines():
            mm = re.match(r"(\w+)\s+\w", line.strip().rstrip(","))
            if mm and mm.group(1).lower() not in _KEYWORDS:
                cols.setdefault(table, set()).add(mm.group(1).lower())
    for m in re.finditer(
            r"alter table\s+(?:if exists\s+)?(?:public\.)?(\w+)\s+add column(?:\s+if not exists)?\s+(\w+)",
            text, re.IGNORECASE):
        cols.setdefault(m.group(1).lower(), set()).add(m.group(2).lower())
    return cols


def test_probed_columns_exist_in_migrations():
    schema = _schema()
    for table, needed in REQUIRED.items():
        present = schema.get(table, set())
        assert needed <= present, f"{table}: probed columns missing from migrations: {needed - present}"
