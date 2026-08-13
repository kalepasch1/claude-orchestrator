"""Wave-C spine persistence migration: the narrowest checks that prove it holds.

The migration is the SQL mirror of ``packages/spine/shared`` — the TypeScript
states its invariants in the type system, the migration states the same ones as
constraints. Two languages describing one schema drift silently, so these tests
assert the two agree rather than trusting a reader to notice.

They are deliberately static: no database is required, which is what lets them
run in preflight on a host with no Postgres.
"""
from __future__ import annotations

import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MIGRATION = os.path.join(
    ROOT, "supabase", "migrations", "20260813000000_wave_c_spine_persistence.sql"
)
CONTRACTS = os.path.join(ROOT, "packages", "spine", "shared", "contracts")

TABLES = (
    "spine_compounds",
    "spine_waves",
    "spine_events",
    "spine_idempotency_keys",
)


def _sql() -> str:
    with open(MIGRATION, encoding="utf-8") as fh:
        return fh.read()


def _ts_union(filename: str, type_name: str) -> set[str]:
    """String-literal members of an exported TS union, or an empty set."""
    path = os.path.join(CONTRACTS, filename)
    if not os.path.exists(path):
        return set()
    with open(path, encoding="utf-8") as fh:
        source = fh.read()
    match = re.search(
        r"export type %s\s*=\s*(.*?);" % re.escape(type_name), source, re.DOTALL
    )
    if not match:
        return set()
    return set(re.findall(r'"([^"]+)"', match.group(1)))


def _check_literals(table: str, column: str) -> set[str]:
    """String literals of a column-level ``check (col in (...))`` constraint."""
    sql = _sql()
    start = sql.index("create table if not exists public.%s" % table)
    body = sql[start : sql.index("\n);", start)]
    match = re.search(
        r"%s[^,]*?check\s*\(\s*%s in \((.*?)\)\)" % (re.escape(column), re.escape(column)),
        body,
        re.DOTALL,
    )
    if not match:
        return set()
    return set(re.findall(r"'([^']+)'", match.group(1)))


class TestMigrationShape(unittest.TestCase):
    def test_migration_file_exists(self):
        self.assertTrue(os.path.exists(MIGRATION), MIGRATION)

    def test_declares_every_spine_table(self):
        sql = _sql()
        for table in TABLES:
            self.assertIn("create table if not exists public.%s" % table, sql, table)

    def test_every_object_is_idempotent(self):
        """A non-idempotent statement breaks re-application on a rolling host."""
        sql = _sql()
        created = re.findall(r"^\s*create (?:table|unique index|index)\b.*", sql, re.M)
        self.assertGreaterEqual(len(created), len(TABLES))
        for stmt in created:
            self.assertIn("if not exists", stmt.lower(), stmt.strip())

    def test_no_destructive_statements(self):
        """Only policies may be dropped, and only to be recreated below."""
        sql = _sql().lower()
        for forbidden in ("drop table", "truncate", "delete from", "drop column"):
            self.assertNotIn(forbidden, sql, forbidden)

    def test_rls_enabled_for_every_table(self):
        sql = _sql()
        self.assertIn("enable row level security", sql)
        rls_block = sql[sql.index("enable row level security") - 600 :]
        for table in TABLES:
            self.assertIn("'%s'" % table, rls_block, table)


class TestInvariantsMirrorTheTypeLayer(unittest.TestCase):
    def test_compound_status_matches_contract_union(self):
        expected = _ts_union("common.ts", "CompoundStatus")
        if not expected:
            self.skipTest("contracts/common.ts not present on this base")
        self.assertEqual(_check_literals("spine_compounds", "status"), expected)

    def test_wave_status_matches_contract_union(self):
        expected = _ts_union("wave.ts", "WaveStatus")
        if not expected:
            self.skipTest("contracts/wave.ts not present on this base")
        self.assertEqual(_check_literals("spine_waves", "status"), expected)

    def test_event_kind_matches_contract_union(self):
        expected = _ts_union("event.ts", "PlatformEventKind")
        if not expected:
            self.skipTest("contracts/event.ts not present on this base")
        self.assertEqual(_check_literals("spine_events", "kind"), expected)

    def test_terminal_status_carries_its_timestamp(self):
        """The constraint form of TerminalCompoundStatus / TerminalWaveStatus."""
        sql = _sql()
        self.assertIn("spine_compounds_terminal_at_matches_status", sql)
        self.assertIn("spine_waves_settled_at_matches_status", sql)

    def test_output_requires_a_settled_wave(self):
        """An unsettled wave publishing output would leak a partial result."""
        self.assertIn("spine_waves_output_requires_settled", _sql())

    def test_event_sequence_is_unique_per_compound(self):
        """Gap detection is only meaningful if a replay cannot take a new slot."""
        self.assertIn(
            "uq_spine_events_compound_sequence\n  on public.spine_events(compound_id, sequence)",
            _sql(),
        )

    def test_rejection_reason_is_present_exactly_when_unapplied(self):
        self.assertIn("spine_events_rejection_matches_applied", _sql())

    def test_idempotency_key_is_unique_per_scope(self):
        """Without this the retry-returns-the-original-effect promise is unbacked."""
        self.assertIn("uq_spine_idempotency_scope_key", _sql())

    def test_duplicate_owner_name_is_rejected_by_the_schema(self):
        self.assertIn("uq_spine_compounds_owner_name", _sql())


class TestMigrationParses(unittest.TestCase):
    def test_statements_parse_as_postgres(self):
        try:
            import sqlglot
        except ImportError:
            self.skipTest("sqlglot not installed")

        import sys

        sys.path.insert(0, os.path.join(ROOT, "runner"))
        try:
            from apply_sql_migrations import _split  # type: ignore
        except Exception:
            self.skipTest("apply_sql_migrations not importable here")

        statements = [s for s in _split(_sql()) if s.strip()]
        self.assertGreaterEqual(len(statements), len(TABLES))
        for stmt in statements:
            # PL/pgSQL bodies are not SQL; the DO block is covered structurally
            # by test_rls_enabled_for_every_table.
            if stmt.strip().lower().startswith("do"):
                continue
            sqlglot.parse_one(stmt, dialect="postgres")

    def test_do_block_is_balanced(self):
        sql = _sql()
        self.assertEqual(sql.count("do $$"), sql.count("end $$;"))


if __name__ == "__main__":
    unittest.main()
