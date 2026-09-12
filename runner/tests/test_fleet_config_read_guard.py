#!/usr/bin/env python3
"""The read side of the fleet_config credential ban.

Incident chain this pins:

  2026-08-02  four live credentials found in plaintext in fleet_config. The
              rows were purged and the WRITE path was made fail-closed.
  after that  code that still asked fleet_config for GITHUB_PAT did not fail.
              fleet_config_dao.get() is fail-soft by contract, so it returned
              None, the caller coerced it to "", built an origin URL with an
              empty token in it, and pushed. Every run of all sixteen cowork
              executors failed that way.

A write guard that raises and a read path that returns None are not symmetric.
These tests hold the read path to the same standard, and hold three exemptions
open on purpose: the audit path, the before-image read inside a write, and the
ordinary config keys the fleet actually uses.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fleet_config_guard as g  # noqa: E402


CREDENTIAL_KEYS = [
    "GITHUB_PAT",
    "VERCEL_TOKEN",
    "OPENAI_API_KEY",
    "GEMINI_API_KEY",
    "SUPABASE_SERVICE_KEY",
    "ANTHROPIC_API_KEY",
    "SLACK_BOT_TOKEN",
    "DATABASE_URL",
    "SESSION_COOKIE",
    "SENTRY_DSN",
    "PAT",
    "db_password",
]

ORDINARY_KEYS = [
    "ORCH_MAX_WORKERS",
    "ORCH_GLOBAL_REPAIR_CEILING",
    "COWORK_EXECUTOR_V6_LAST_RUN",
    "MAX_PARALLEL",
    "LOG_LEVEL",
    "ORCH_RELEASE_TRAIN_ENABLED",
]


class TestAssertReadable(unittest.TestCase):
    def test_every_credential_key_is_refused(self):
        for key in CREDENTIAL_KEYS:
            with self.assertRaises(g.CredentialReadError, msg=key):
                g.assert_readable(key)

    def test_ordinary_config_keys_are_allowed(self):
        for key in ORDINARY_KEYS:
            self.assertTrue(g.assert_readable(key), msg=key)

    def test_the_refusal_names_the_environment_as_the_fix(self):
        with self.assertRaises(g.CredentialReadError) as ctx:
            g.assert_readable("GITHUB_PAT")
        message = str(ctx.exception)
        self.assertIn("os.environ.get('GITHUB_PAT')", message)
        self.assertIn("fleet-config-guard", message)

    def test_it_is_a_valueerror_so_existing_handlers_still_catch_it(self):
        # assert_writable raises ValueError; callers wrap config access in
        # `except ValueError`. The read refusal must not slip past them.
        with self.assertRaises(ValueError):
            g.assert_readable("VERCEL_TOKEN")

    def test_read_and_write_guards_agree_on_what_a_credential_is(self):
        for key in CREDENTIAL_KEYS:
            self.assertTrue(g.is_secret(key), msg=key)
            self.assertFalse(g.is_readable(key), msg=key)
        for key in ORDINARY_KEYS:
            self.assertFalse(g.is_secret(key), msg=key)
            self.assertTrue(g.is_readable(key), msg=key)

    def test_empty_and_none_keys_are_readable_not_crashes(self):
        self.assertTrue(g.assert_readable(""))
        self.assertTrue(g.assert_readable(None))


class _FakeDB:
    """Stands in for db.py: records queries, returns whatever it is told to."""

    def __init__(self, rows=None):
        self.rows = rows or []
        self.selects = []
        self.upserts = []

    def select(self, table, params):
        self.selects.append((table, params))
        return list(self.rows)

    def upsert(self, table, row):
        # db.py enforces fleet_config_guard.assert_writable inside upsert (see
        # runner/db.py). A fake that skipped it would make the write path look
        # unguarded and let a real regression pass.
        if table == "fleet_config":
            g.assert_writable(row.get("key"), row.get("value"))
        self.upserts.append((table, row))
        return [row]


class TestDaoReadPath(unittest.TestCase):
    """The guard has to sit at the DAO choke point, not at one call site."""

    def setUp(self):
        import fleet_config_dao
        self.dao = fleet_config_dao
        self.fake = _FakeDB(rows=[{"key": "ORCH_MAX_WORKERS", "value": "10"}])
        self._real_db = self.dao.db
        self.dao.db = self.fake

    def tearDown(self):
        self.dao.db = self._real_db

    def test_get_refuses_a_credential_key_and_issues_no_query(self):
        with self.assertRaises(g.CredentialReadError):
            self.dao.get("GITHUB_PAT")
        self.assertEqual(self.fake.selects, [],
                         "a refused read must not reach the database")

    def test_get_still_works_for_ordinary_keys(self):
        row = self.dao.get("ORCH_MAX_WORKERS")
        self.assertEqual(row, {"key": "ORCH_MAX_WORKERS", "value": "10"})
        self.assertEqual(len(self.fake.selects), 1)

    def test_get_many_refuses_when_one_key_in_the_batch_is_a_credential(self):
        with self.assertRaises(g.CredentialReadError):
            self.dao.get_many(["ORCH_MAX_WORKERS", "LOG_LEVEL", "VERCEL_TOKEN"])
        self.assertEqual(self.fake.selects, [],
                         "batching must not be a way around the guard")

    def test_get_many_still_works_for_ordinary_keys(self):
        out = self.dao.get_many(["ORCH_MAX_WORKERS"])
        self.assertIn("ORCH_MAX_WORKERS", out)

    def test_get_many_of_nothing_is_still_empty(self):
        self.assertEqual(self.dao.get_many([]), {})
        self.assertEqual(self.dao.get_many(None), {})

    def test_get_is_not_fail_soft_about_this(self):
        # The whole failure was `None` where an error belonged. If a future edit
        # wraps assert_readable in the DAO's try/except, this test fails.
        self.fake.rows = []
        with self.assertRaises(g.CredentialReadError):
            self.dao.get("OPENAI_API_KEY")


class TestWritePathStillReportsWriteErrors(unittest.TestCase):
    """The before-image read inside a write must not shadow assert_writable."""

    def setUp(self):
        import fleet_config_dao
        self.dao = fleet_config_dao
        self.fake = _FakeDB(rows=[])
        self._real_db = self.dao.db
        self.dao.db = self.fake

    def tearDown(self):
        self.dao.db = self._real_db

    def test_writing_a_credential_fails_with_the_write_message(self):
        with self.assertRaises(ValueError) as ctx:
            self.dao.set_value("GITHUB_PAT", "ghp_" + "x" * 30)
        message = str(ctx.exception)
        self.assertIn("refusing to store a credential", message)
        self.assertNotIn("refusing to read a credential", message)

    def test_a_transport_error_is_still_fail_soft(self):
        # The refusal propagates; a dropped connection must not start doing so
        # too, or every caller in the tree gains a new exception path.
        def boom(table, row):
            raise ConnectionError("postgrest unreachable")

        self.fake.upsert = boom
        old, new = self.dao.set_value("ORCH_MAX_WORKERS", 12)
        self.assertIsNone(new)

    def test_an_ordinary_write_still_round_trips(self):
        old, new = self.dao.set_value("ORCH_MAX_WORKERS", 12)
        self.assertIsNone(old)
        self.assertEqual(new["key"], "ORCH_MAX_WORKERS")
        self.assertEqual(new["value"], "12")


class TestAuditPathIsNotBlinded(unittest.TestCase):
    """Finding credentials in the table requires being able to see them."""

    def setUp(self):
        import fleet_config_dao
        self.dao = fleet_config_dao
        self.fake = _FakeDB(rows=[
            {"key": "ORCH_MAX_WORKERS", "value": "10"},
            {"key": "GITHUB_PAT", "value": "ghp_" + "x" * 30},
        ])
        self._real_db = self.dao.db
        self.dao.db = self.fake

    def tearDown(self):
        self.dao.db = self._real_db

    def test_get_all_is_unguarded_so_the_auditor_can_still_run(self):
        rows = self.dao.get_all()
        self.assertEqual(len(rows), 2)

    def test_scan_rows_finds_the_offender_without_echoing_the_value(self):
        hits = g.scan_rows(self.dao.get_all())
        self.assertEqual([h["key"] for h in hits], ["GITHUB_PAT"])
        self.assertNotIn("ghp_", hits[0]["reason"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
