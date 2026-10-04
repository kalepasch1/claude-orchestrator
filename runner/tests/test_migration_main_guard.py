#!/usr/bin/env python3
"""Tests for migration_main_guard — "the orchestrator only applies migrations that are already
on main" (owner decision 2026-10-03) — and the paths it gates (apply_sql_migrations,
action_runner, the Claude Code hook).

Every git repository here is a throwaway on disk: a bare repo plays `origin`, a clone plays the
checkout. No network, no database: the ledger is a list and every database call is stubbed.
"""
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import migration_main_guard as guard  # noqa: E402

MIG = "supabase/migrations"
GOOD = b"create table if not exists public.widgets (id bigint primary key);\n"
DROP = b"drop table if exists public.legacy_widgets;\n"
TARGET = {"app": "smarter", "github_repo": "kalepasch1/smarter", "branch": "main",
          "repo_path": "", "supabase_project_ref": "olaxnyrzoptjcntrrjgn"}


def _git(cwd, *args):
    p = subprocess.run(["git", "-c", "core.hooksPath=/dev/null", "-c", "user.name=t",
                        "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false"] + list(args),
                       cwd=cwd, capture_output=True, text=True, timeout=60)
    if p.returncode != 0:
        raise AssertionError("git %s: %s" % (" ".join(args), p.stderr))
    return p.stdout.strip()


def _write(root, rel, data):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(data)
    return path


class RepoCase(unittest.TestCase):
    """origin (bare) with main carrying two migrations; `work` is a clone on main."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="mmg-")
        self.origin = os.path.join(self.tmp, "origin.git")
        self.work = os.path.join(self.tmp, "work")
        _git(self.tmp, "init", "--bare", "-b", "main", self.origin)
        _git(self.tmp, "clone", "-q", self.origin, self.work)
        _git(self.work, "checkout", "-q", "-B", "main")
        _write(self.work, "%s/20261001000000_widgets.sql" % MIG, GOOD)
        _write(self.work, "%s/20261002000000_drop_legacy.sql" % MIG, DROP)
        _git(self.work, "add", "-A")
        _git(self.work, "commit", "-q", "-m", "main migrations")
        _git(self.work, "push", "-q", "origin", "main")
        self.target = dict(TARGET, repo_path=self.work)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def feature_branch(self, name="feat/licensing-vocabulary", files=None):
        _git(self.work, "checkout", "-q", "-b", name)
        for rel, data in (files or {}).items():
            _write(self.work, rel, data)
        _git(self.work, "add", "-A")
        _git(self.work, "commit", "-q", "-m", "branch work")
        return name


class TestCheckMigration(RepoCase):

    def test_branch_only_migration_is_refused(self):
        rel = "%s/20261030020000_licensing_vocabulary.sql" % MIG
        self.feature_branch(files={rel: b"create table public.licensing_vocab (id int);\n"})
        d = guard.check_file(os.path.join(self.work, rel), self.target, ledger=[])
        self.assertFalse(d["ok"])
        self.assertEqual(d["code"], "not_on_main")
        self.assertIn("20261030020000", d["reason"])
        self.assertIn("feat/licensing-vocabulary", d["reason"])
        self.assertIn("origin/main of kalepasch1/smarter", d["reason"])
        self.assertNotIn("sql", d)

    def test_main_migration_with_drifted_content_is_refused(self):
        # Same filename as main, different bytes — e.g. edited on a branch after merge.
        self.feature_branch(name="fix/prod-posture-drift-1524",
                            files={"%s/20261001000000_widgets.sql" % MIG: GOOD + b"alter table public.widgets add column x int;\n"})
        d = guard.check_file(os.path.join(self.work, MIG, "20261001000000_widgets.sql"), self.target, ledger=[])
        self.assertFalse(d["ok"])
        self.assertEqual(d["code"], "content_drift")
        self.assertIn("20261001000000", d["reason"])
        self.assertIn("fix/prod-posture-drift-1524", d["reason"])
        self.assertNotEqual(d["sha_main"], d["sha_run"])

    def test_drift_is_byte_exact(self):
        main = guard.GitMain(self.work, "main")
        d = guard.check_migration(self.target, "20261001000000", "widgets", GOOD.replace(b"\n", b"\r\n"),
                                  main=main, ledger=[])
        self.assertEqual(d["code"], "content_drift")

    def test_matching_main_migration_passes(self):
        d = guard.check_file(os.path.join(self.work, MIG, "20261001000000_widgets.sql"), self.target, ledger=[])
        self.assertTrue(d["ok"], d.get("reason"))
        self.assertEqual(d["code"], "ok")
        self.assertEqual(d["sql"], GOOD)
        self.assertFalse(d["already_applied"])

    def test_matching_main_migration_passes_from_a_feature_worktree(self):
        # Standing on a branch is fine as long as the file is on main byte-identical.
        self.feature_branch(files={"README": b"x"})
        d = guard.check_file(os.path.join(self.work, MIG, "20261001000000_widgets.sql"), self.target, ledger=[])
        self.assertTrue(d["ok"], d.get("reason"))

    def test_main_is_fetched_fresh(self):
        # Merged to origin/main by someone else after this clone last fetched.
        other = os.path.join(self.tmp, "other")
        _git(self.tmp, "clone", "-q", self.origin, other)
        _write(other, "%s/20261003000000_new.sql" % MIG, b"select 1;\n")
        _git(other, "add", "-A")
        _git(other, "commit", "-q", "-m", "new")
        _git(other, "push", "-q", "origin", "main")
        d = guard.check_migration(self.target, "20261003000000", "new", b"select 1;\n",
                                  main=guard.GitMain(self.work, "main"), ledger=[])
        self.assertTrue(d["ok"], d.get("reason"))

    def test_version_collision_in_ledger_is_refused(self):
        ledger = [{"version": "20261001000000", "name": "benchmark_library"}]
        d = guard.check_file(os.path.join(self.work, MIG, "20261001000000_widgets.sql"), self.target, ledger=ledger)
        self.assertFalse(d["ok"])
        self.assertEqual(d["code"], "ledger_collision")
        self.assertIn("benchmark_library", d["reason"])

    def test_name_already_applied_under_another_version_is_refused(self):
        ledger = [{"version": "20261003121212", "name": "widgets"}]
        d = guard.check_file(os.path.join(self.work, MIG, "20261001000000_widgets.sql"), self.target, ledger=ledger)
        self.assertEqual(d["code"], "ledger_name_collision")

    def test_duplicate_version_on_main_is_refused(self):
        _write(self.work, "%s/20261001000000_other.sql" % MIG, b"select 2;\n")
        _git(self.work, "add", "-A")
        _git(self.work, "commit", "-q", "-m", "dupe")
        _git(self.work, "push", "-q", "origin", "main")
        d = guard.check_file(os.path.join(self.work, MIG, "20261001000000_widgets.sql"), self.target, ledger=[])
        self.assertEqual(d["code"], "duplicate_version_on_main")

    def test_same_version_same_name_is_already_applied(self):
        ledger = [{"version": "20261001000000", "name": "widgets"}]
        d = guard.check_file(os.path.join(self.work, MIG, "20261001000000_widgets.sql"), self.target, ledger=ledger)
        self.assertTrue(d["ok"])
        self.assertTrue(d["already_applied"])

    def test_unreadable_ledger_refuses(self):
        d = guard.check_file(os.path.join(self.work, MIG, "20261001000000_widgets.sql"), self.target, ledger=None)
        self.assertEqual(d["code"], "ledger_unreadable")

    def test_destructive_migration_needs_owner_approval_in_addition(self):
        path = os.path.join(self.work, MIG, "20261002000000_drop_legacy.sql")
        with patch.dict(os.environ, {guard.OWNER_APPROVAL_ENV: ""}):
            d = guard.check_file(path, self.target, ledger=[])
            self.assertEqual(d["code"], "destructive_unapproved")
            self.assertIn("drop table", d["reason"])
            ok = guard.check_file(path, self.target, ledger=[], owner_approved=["20261002000000"])
            self.assertTrue(ok["ok"], ok.get("reason"))
        with patch.dict(os.environ, {guard.OWNER_APPROVAL_ENV: "20261002000000"}):
            self.assertTrue(guard.check_file(path, self.target, ledger=[])["ok"])

    def test_owner_approval_does_not_waive_main(self):
        rel = "%s/20261030030000_drop_stuff.sql" % MIG
        self.feature_branch(files={rel: DROP})
        d = guard.check_file(os.path.join(self.work, rel), self.target, ledger=[],
                             owner_approved=["20261030030000"])
        self.assertEqual(d["code"], "not_on_main")

    def test_unmapped_target_is_refused(self):
        d = guard.check_file(os.path.join(self.work, MIG, "20261001000000_widgets.sql"), None, ledger=[])
        self.assertEqual(d["code"], "no_target")

    def test_unfetchable_main_is_refused(self):
        main = guard.GitMain(os.path.join(self.tmp, "nope"), "main")
        d = guard.check_migration(self.target, "20261001000000", "widgets", GOOD, main=main, ledger=[])
        self.assertEqual(d["code"], "main_unreadable")

    def test_wrong_repo_checkout_is_refused(self):
        _git(self.work, "remote", "set-url", "origin", "git@github.com:kalepasch1/someone-else.git")
        main = guard.GitMain(self.work, "main", expected_repo="kalepasch1/smarter", fetch=False)
        d = guard.check_migration(self.target, "20261001000000", "widgets", GOOD, main=main, ledger=[])
        self.assertEqual(d["code"], "main_unreadable")
        self.assertIn("someone-else", d["reason"])


class TestCheckCheckout(RepoCase):

    def test_main_checkout_passes_and_lists_pending(self):
        d = guard.check_checkout(self.work, self.target, ledger=[{"version": "20261001000000", "name": "widgets"}],
                                 owner_approved=["20261002000000"])
        self.assertTrue(d["ok"], d.get("reason"))
        self.assertEqual(d["pending"], ["20261002000000_drop_legacy.sql"])

    def test_feature_checkout_is_refused(self):
        self.feature_branch(name="feat/benchmark-library-to-prod",
                            files={"%s/20261030020000_benchmarks.sql" % MIG: b"create table b (id int);\n"})
        d = guard.check_checkout(self.work, self.target, ledger=[])
        self.assertFalse(d["ok"])
        self.assertEqual(d["code"], "not_on_main")
        self.assertIn("feat/benchmark-library-to-prod", d["reason"])

    def test_dirty_checkout_is_refused(self):
        _write(self.work, "%s/20261030040000_untracked.sql" % MIG, b"select 1;\n")
        d = guard.check_checkout(self.work, self.target, ledger=[])
        self.assertEqual(d["code"], "dirty_checkout")

    def test_destructive_pending_without_approval_is_refused(self):
        with patch.dict(os.environ, {guard.OWNER_APPROVAL_ENV: ""}):
            d = guard.check_checkout(self.work, self.target, ledger=[])
        self.assertFalse(d["ok"])
        self.assertEqual(d["code"], "destructive_unapproved")

    def test_collision_in_checkout_is_refused(self):
        d = guard.check_checkout(self.work, self.target, owner_approved=["20261002000000"],
                                 ledger=[{"version": "20261001000000", "name": "something_else"}])
        self.assertEqual(d["code"], "ledger_collision")


class TestRecordRefusal(unittest.TestCase):

    def test_refusal_goes_to_fleet_log(self):
        import db
        rows = []
        with patch.object(db, "insert", side_effect=lambda t, r, **k: rows.append((t, r))), \
                patch("sys.stdout", new_callable=io.StringIO) as out:
            guard.record_refusal({"ok": False, "code": "not_on_main", "reason": "refused migration 1",
                                  "sql": b"secret-ish"}, via="test")
        self.assertIn("refused migration 1", out.getvalue())
        self.assertEqual(rows[0][0], "fleet_log")
        self.assertEqual(rows[0][1]["source"], "migration_main_guard")
        self.assertEqual(rows[0][1]["level"], "warn")
        self.assertNotIn("secret-ish", rows[0][1]["meta"])

    def test_log_failure_does_not_raise(self):
        import db
        with patch.object(db, "insert", side_effect=RuntimeError("down")), \
                patch("sys.stdout", new_callable=io.StringIO):
            d = guard.record_refusal({"ok": False, "reason": "x"})
        self.assertFalse(d["ok"])


class TestResolveTarget(unittest.TestCase):

    def test_production_refs_map_to_main(self):
        b = guard.load_bindings()
        smarter = guard.resolve_target(ref="olaxnyrzoptjcntrrjgn", bindings=b)
        self.assertEqual((smarter["github_repo"], smarter["branch"]), ("kalepasch1/smarter", "main"))
        law = guard.resolve_target(ref="cwmeqqtvmjbapjsefbfq", bindings=b)
        self.assertEqual((law["github_repo"], law["branch"]), ("kalepasch1/apparently-law", "main"))
        self.assertEqual(guard.resolve_target(app="apparently", bindings=b)["app"], "smarter")
        self.assertIsNone(guard.resolve_target(ref="unknownref", bindings=b))

    def test_repo_slug(self):
        self.assertEqual(guard.repo_slug("git@github.com:kalepasch1/smarter.git"), "kalepasch1/smarter")
        self.assertEqual(guard.repo_slug("https://x-access-token:abc@github.com/kalepasch1/Smarter"), "kalepasch1/smarter")
        self.assertEqual(guard.repo_slug("/tmp/origin.git"), "")


class TestApplySqlMigrations(RepoCase):

    def _apply(self, paths, ledger=()):
        import apply_sql_migrations as asm
        calls = []

        def fake_query(ref, token, sql):
            calls.append(sql)
            if sql == guard.LEDGER_SQL:
                return list(ledger)
            return []
        with patch.object(asm, "_query", side_effect=fake_query), \
                patch.object(asm.guard, "resolve_target", return_value=self.target), \
                patch.object(asm.guard, "record_refusal", side_effect=lambda d, via="": d), \
                patch.dict(os.environ, {"SUPABASE_ACCESS_TOKEN": "t", "SUPABASE_PROJECT_REF": "olaxnyrzoptjcntrrjgn"}):
            res = asm.apply(paths)
        return res, [c for c in calls if c != guard.LEDGER_SQL]

    def test_branch_only_file_runs_nothing(self):
        rel = "%s/20261030020000_licensing_vocabulary.sql" % MIG
        self.feature_branch(files={rel: b"create table public.lv (id int);\n"})
        res, ddl = self._apply([os.path.join(self.work, rel)])
        self.assertEqual(ddl, [])
        self.assertEqual(res["applied"], [])
        self.assertEqual(res["refused"][0]["code"], "not_on_main")

    def test_main_file_runs_its_verified_statements(self):
        res, ddl = self._apply([os.path.join(self.work, MIG, "20261001000000_widgets.sql")])
        self.assertEqual(res["refused"], [])
        self.assertEqual(len(res["applied"]), 1)
        self.assertEqual(ddl, [GOOD.decode().strip().rstrip(";")])

    def test_collision_runs_nothing(self):
        res, ddl = self._apply([os.path.join(self.work, MIG, "20261001000000_widgets.sql")],
                               ledger=[{"version": "20261001000000", "name": "other"}])
        self.assertEqual(ddl, [])
        self.assertEqual(res["refused"][0]["code"], "ledger_collision")

    def test_unmapped_ref_runs_nothing(self):
        import apply_sql_migrations as asm
        with patch.object(asm, "_query", side_effect=AssertionError("must not query")), \
                patch.object(asm.guard, "record_refusal", side_effect=lambda d, via="": d), \
                patch.dict(os.environ, {"SUPABASE_ACCESS_TOKEN": "t", "SUPABASE_PROJECT_REF": "notmapped"}):
            res = asm.apply([os.path.join(self.work, MIG, "20261001000000_widgets.sql")])
        self.assertEqual(res["refused"][0]["code"], "no_target")


class TestActionRunnerGate(RepoCase):

    def _gate(self, cmd):
        import action_runner
        with patch.object(action_runner, "_project_for", return_value="smarter"), \
                patch.object(guard, "resolve_target", return_value=self.target), \
                patch.object(guard, "read_ledger", return_value=[]), \
                patch.object(guard, "record_refusal", side_effect=lambda d, via="": d):
            return action_runner._migration_gate({"id": 1, "approval_id": "a"}, cmd, self.work)

    def test_non_migration_command_is_not_gated(self):
        self.assertIsNone(self._gate("git pull --ff-only"))

    def test_db_push_from_feature_branch_is_refused(self):
        self.feature_branch(files={"%s/20261030020000_x.sql" % MIG: b"create table x (id int);\n"})
        reason = self._gate("supabase db push")
        self.assertIn("not contained in origin/main", reason)

    def test_db_push_from_main_passes(self):
        with patch.dict(os.environ, {guard.OWNER_APPROVAL_ENV: "20261002000000"}):
            self.assertIsNone(self._gate("supabase db push"))


class TestClaudeHook(unittest.TestCase):
    B = {"targets": [{"app": "smarter", "github_repo": "kalepasch1/smarter", "branch": "main",
                      "supabase_project_ref": "olaxnyrzoptjcntrrjgn"}]}

    def test_apply_migration_on_production_is_refused(self):
        ok, msg = guard.hook_decision({"tool_name": "mcp__supabase__apply_migration",
                                       "tool_input": {"project_id": "olaxnyrzoptjcntrrjgn",
                                                      "name": "x", "query": "create table x();"}}, self.B)
        self.assertFalse(ok)
        self.assertIn("consolidation/main", msg)

    def test_ddl_through_execute_sql_is_refused_reads_pass(self):
        ddl = {"tool_name": "mcp__x__execute_sql",
               "tool_input": {"project_id": "olaxnyrzoptjcntrrjgn", "query": "DROP TABLE public.t"}}
        self.assertFalse(guard.hook_decision(ddl, self.B)[0])
        read = {"tool_name": "mcp__x__execute_sql",
                "tool_input": {"project_id": "olaxnyrzoptjcntrrjgn",
                               "query": "select version, name from supabase_migrations.schema_migrations"}}
        self.assertTrue(guard.hook_decision(read, self.B)[0])

    def test_non_production_project_passes(self):
        ok, _ = guard.hook_decision({"tool_name": "mcp__supabase__apply_migration",
                                     "tool_input": {"project_id": "previewbranchref"}}, self.B)
        self.assertTrue(ok)


class TestDestructiveDetection(unittest.TestCase):

    def test_classes(self):
        self.assertTrue(guard.destructive_statements("DROP TABLE public.x;"))
        self.assertTrue(guard.destructive_statements("alter table public.x drop column y;"))
        self.assertTrue(guard.destructive_statements("truncate public.x;"))
        self.assertFalse(guard.destructive_statements("drop policy if exists p on public.x; create policy p on public.x using (true);"))
        self.assertFalse(guard.destructive_statements("-- drop table x\nselect 'drop table y';"))


if __name__ == "__main__":
    unittest.main()
