#!/usr/bin/env python3
"""Tests for runner/new_migration.py — the migration scaffolder.

This replaces the refused `shared/db_migrations/migration.ts` placeholder. The
behaviour that matters is not "a file exists" but "the file lands in the one
canonical home, with the naming and idempotence the repo already uses, and
refuses everything else". These tests assert exactly that.
"""
import datetime as dt
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import new_migration as nm  # noqa: E402

FIXED = dt.datetime(2026, 8, 11, 9, 30, 0, tzinfo=dt.timezone.utc)


class SlugifyTest(unittest.TestCase):
    def test_spaces_and_punctuation_become_single_underscores(self):
        self.assertEqual(nm.slugify("Add Widget  Table!"), "add_widget_table")

    def test_already_snake_case_is_unchanged(self):
        self.assertEqual(nm.slugify("add_widget_table"), "add_widget_table")

    def test_a_typed_timestamp_prefix_is_stripped_so_it_is_not_doubled(self):
        self.assertEqual(nm.slugify("20260811093000_add_widget"), "add_widget")

    def test_unusable_names_yield_empty_string(self):
        for bad in (None, "", "   ", "!!!", "___", 0, []):
            self.assertEqual(nm.slugify(bad), "", f"slugify({bad!r})")

    def test_long_names_are_truncated_without_a_trailing_underscore(self):
        slug = nm.slugify("x " * 200)
        self.assertLessEqual(len(slug), nm.MAX_SLUG_CHARS)
        self.assertFalse(slug.endswith("_"))


class HomeTest(unittest.TestCase):
    def test_default_home_is_supabase_migrations(self):
        self.assertEqual(nm.resolve_home(None), "supabase/migrations")
        self.assertEqual(nm.DEFAULT_HOME, "supabase/migrations")

    def test_every_declared_home_resolves(self):
        for home in nm.MIGRATION_HOMES:
            self.assertEqual(nm.resolve_home(home), home)

    def test_trailing_slashes_are_tolerated(self):
        self.assertEqual(nm.resolve_home("/runner/migrations/"), "runner/migrations")

    def test_a_fourth_home_is_refused(self):
        """The whole point: no new migration convention gets invented."""
        for bad in ("shared/db_migrations", "migrations", "db/migrate", "", "  "):
            self.assertEqual(nm.resolve_home(bad), "", f"resolve_home({bad!r}) must be refused")

    def test_create_refuses_a_non_canonical_home(self):
        out = nm.create("add widget", home="shared/db_migrations", root=tempfile.mkdtemp())
        self.assertFalse(out["ok"])
        self.assertIn("not a migration home", out["reason"])


class FilenameTest(unittest.TestCase):
    def test_filename_uses_the_current_timestamp_convention(self):
        self.assertEqual(nm.filename("add widget table", now=FIXED),
                         "20260811093000_add_widget_table.sql")

    def test_filename_is_empty_for_an_unusable_name(self):
        self.assertEqual(nm.filename("!!!", now=FIXED), "")

    def test_filename_does_not_use_the_colliding_legacy_prefix(self):
        """Five distinct 0038_* files exist; never emit that shape again."""
        name = nm.filename("add widget", now=FIXED)
        self.assertRegex(name, r"^\d{14}_")
        self.assertNotRegex(name, r"^\d{4}_")


class RenderTest(unittest.TestCase):
    def test_body_states_the_idempotence_requirement(self):
        body = nm.render("add widget")
        self.assertIn("Idempotent", body)
        self.assertIn("apply_sql_migrations.py", body)

    def test_body_scaffolds_only_if_not_exists_forms(self):
        body = nm.render("add widget")
        self.assertIn("create table if not exists", body)
        self.assertIn("add column if not exists", body)
        self.assertIn("create index if not exists", body)

    def test_body_is_entirely_comments_so_an_unedited_file_is_a_no_op(self):
        for line in nm.render("add widget").splitlines():
            if line.strip():
                self.assertTrue(line.startswith("--"), f"uncommented SQL: {line!r}")

    def test_summary_is_carried_into_the_header(self):
        self.assertIn("adds the widget table", nm.render("add widget", summary="adds the widget table"))

    def test_missing_summary_leaves_an_explicit_todo(self):
        self.assertIn("TODO", nm.render("add widget"))


class CreateTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()

    def test_writes_into_the_default_home_with_the_expected_name(self):
        out = nm.create("add widget table", root=self.root, now=FIXED)
        self.assertTrue(out["ok"], out.get("reason"))
        self.assertEqual(out["path"], "supabase/migrations/20260811093000_add_widget_table.sql")
        written = os.path.join(self.root, *out["path"].split("/"))
        self.assertTrue(os.path.exists(written))
        with open(written) as handle:
            self.assertEqual(handle.read(), out["body"])

    def test_writes_into_an_alternate_canonical_home_when_asked(self):
        out = nm.create("claim next rpc", home="runner/migrations", root=self.root, now=FIXED)
        self.assertTrue(out["ok"], out.get("reason"))
        self.assertTrue(out["path"].startswith("runner/migrations/"))

    def test_refuses_to_overwrite_an_existing_migration(self):
        first = nm.create("add widget", root=self.root, now=FIXED)
        self.assertTrue(first["ok"])
        second = nm.create("add widget", root=self.root, now=FIXED)
        self.assertFalse(second["ok"])
        self.assertIn("append-only", second["reason"])

    def test_dry_run_writes_nothing_but_reports_the_path_and_body(self):
        out = nm.create("add widget", root=self.root, now=FIXED, dry_run=True)
        self.assertTrue(out["ok"])
        self.assertTrue(out["dry_run"])
        self.assertIn("body", out)
        self.assertFalse(os.path.exists(os.path.join(self.root, *out["path"].split("/"))))

    def test_unusable_name_fails_soft_without_writing(self):
        out = nm.create("!!!", root=self.root, now=FIXED)
        self.assertFalse(out["ok"])
        self.assertIn("no usable slug", out["reason"])
        self.assertFalse(os.path.exists(os.path.join(self.root, "supabase")))

    def test_unwritable_root_fails_soft_instead_of_raising(self):
        blocked = os.path.join(self.root, "blocked")
        open(blocked, "w").close()  # a FILE where a directory must go
        out = nm.create("add widget", root=blocked, now=FIXED)
        self.assertFalse(out["ok"])
        self.assertIn("could not write", out["reason"])

    def test_never_raises_on_any_junk_input(self):
        for bad in (None, "", 0, [], {}, object()):
            out = nm.create(bad, root=self.root, now=FIXED)
            self.assertIn("ok", out)
            self.assertFalse(out["ok"], f"create({bad!r}) should fail soft")


class CliTest(unittest.TestCase):
    def test_dry_run_exits_zero(self):
        self.assertEqual(nm.main(["add widget", "--dry-run"]), 0)

    def test_bad_home_exits_nonzero(self):
        self.assertEqual(nm.main(["add widget", "--home", "shared/db_migrations", "--dry-run"]), 1)

    def test_bad_name_exits_nonzero(self):
        self.assertEqual(nm.main(["!!!", "--dry-run"]), 1)


class RepoConventionTest(unittest.TestCase):
    """Generated names must match what is already on disk."""

    def test_generated_name_matches_the_shape_of_existing_migrations(self):
        real = os.path.join(nm.ROOT, "supabase", "migrations")
        if not os.path.isdir(real):
            self.skipTest("supabase/migrations not present in this checkout")
        existing = [f for f in os.listdir(real) if f.endswith(".sql")]
        self.assertTrue(existing, "expected existing migrations to compare against")
        generated = nm.filename("add widget table", now=FIXED)
        self.assertTrue(any(len(f.split("_")[0]) == len(generated.split("_")[0])
                            for f in existing),
                        "generated timestamp width matches no existing migration")

    def test_shared_db_migrations_is_not_a_home(self):
        """Regression guard for the artifact this module replaces."""
        self.assertNotIn("shared/db_migrations", nm.MIGRATION_HOMES)


if __name__ == "__main__":
    unittest.main()
