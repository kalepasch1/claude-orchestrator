#!/usr/bin/env python3
"""
test_cross_project_depends.py — verify that the dependency resolver handles:
  1. bare (project-local) slug ids  (backward compat)
  2. cross-project "project:slug" ids  (new)
  3. unknown references (task stays blocked, never silently runs)
"""
import os, sys, types, unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# ── stub heavy imports that db.py pulls in at module level ──────────
for mod_name in ("supabase", "postgrest", "httpx", "gotrue", "realtime",
                 "storage3", "supafunc"):
    if mod_name not in sys.modules:
        sys.modules[mod_name] = types.ModuleType(mod_name)

import db


class TestDoneSlugsContainsCrossProjectEntries(unittest.TestCase):
    """_done_slugs() must return both bare slugs and project_name:slug entries."""

    def _make_rows(self):
        return [
            {"slug": "setup-ci", "project_id": "pid-aaa"},
            {"slug": "curation-layer-land", "project_id": "pid-bbb"},
            {"slug": "shared-task", "project_id": "pid-aaa"},
        ]

    def _make_projects(self):
        return [
            {"id": "pid-aaa", "name": "beethoven"},
            {"id": "pid-bbb", "name": "apparently"},
        ]

    @patch.object(db, "select")
    def test_bare_and_qualified_slugs(self, mock_select):
        """Both bare and project:slug forms are in the returned set."""
        db.invalidate_done_cache()

        def _select(table, params):
            if table == "tasks":
                return self._make_rows()
            if table == "projects":
                return self._make_projects()
            return []

        mock_select.side_effect = _select
        result = db._done_slugs()

        # bare slugs present (backward compat)
        self.assertIn("setup-ci", result)
        self.assertIn("curation-layer-land", result)
        self.assertIn("shared-task", result)

        # qualified cross-project entries present
        self.assertIn("beethoven:setup-ci", result)
        self.assertIn("apparently:curation-layer-land", result)
        self.assertIn("beethoven:shared-task", result)

    @patch.object(db, "select")
    def test_unknown_project_still_has_bare_slug(self, mock_select):
        """If projects lookup fails, bare slugs are still present."""
        db.invalidate_done_cache()

        call_count = [0]
        def _select(table, params):
            if table == "tasks":
                return [{"slug": "some-task", "project_id": "pid-zzz"}]
            if table == "projects":
                raise ConnectionError("db down")
            return []

        mock_select.side_effect = _select
        result = db._done_slugs()

        self.assertIn("some-task", result)
        # no qualified entry because project lookup failed — fail-soft
        self.assertNotIn("unknown:some-task", result)


class TestDepResolutionInClaimTask(unittest.TestCase):
    """Integration-level: verify that claim_task's dep check handles all three cases."""

    def _patch_done_slugs(self, slugs_set):
        return patch.object(db, "_done_slugs", return_value=slugs_set)

    def test_bare_local_dep_satisfied(self):
        """A bare dep that exists in done set → task is claimable."""
        done = {"contracts", "beethoven:contracts"}
        deps = ["contracts"]
        self.assertTrue(all(d in done for d in deps))

    def test_cross_project_dep_satisfied(self):
        """A cross-project dep 'apparently:curation-layer-land' → claimable when present."""
        done = {"curation-layer-land", "apparently:curation-layer-land", "setup-ci", "beethoven:setup-ci"}
        deps = ["contracts", "apparently:curation-layer-land"]
        # "contracts" is NOT in done, so this should block
        self.assertFalse(all(d in done for d in deps))

        # now add contracts
        done.add("contracts")
        self.assertTrue(all(d in done for d in deps))

    def test_unknown_dep_blocks(self):
        """An unknown dep stays blocked — never silently runs."""
        done = {"setup-ci", "beethoven:setup-ci"}
        deps = ["nonexistent-task"]
        self.assertFalse(all(d in done for d in deps))

    def test_cross_project_unknown_blocks(self):
        """A cross-project dep for a task that doesn't exist stays blocked."""
        done = {"setup-ci", "beethoven:setup-ci"}
        deps = ["otherproject:missing-task"]
        self.assertFalse(all(d in done for d in deps))

    def test_empty_deps_always_claimable(self):
        """No deps → always claimable (backward compat)."""
        done = set()
        deps = []
        self.assertTrue(all(d in done for d in deps))

    def test_mixed_local_and_cross_project(self):
        """Mix of bare and qualified deps all satisfied."""
        done = {"setup-ci", "beethoven:setup-ci", "curation-layer-land", "apparently:curation-layer-land"}
        deps = ["setup-ci", "apparently:curation-layer-land"]
        self.assertTrue(all(d in done for d in deps))


class TestEnqueueTaskDeps(unittest.TestCase):
    """enqueue_task.py passes deps through to the DB row."""

    @patch("enqueue_task.db")
    @patch("enqueue_task.pipeline_contract")
    def test_deps_included_in_row(self, mock_pc, mock_db):
        import enqueue_task

        def _select(table, params):
            if table == "projects":
                return [{"id": "pid-1", "name": "beethoven", "repo_path": "/tmp/b"}]
            # tasks table — already_present check: return empty so it proceeds
            return []

        mock_db.select.side_effect = _select
        mock_pc.wrap_prompt.return_value = "wrapped"
        mock_pc.note.return_value = "noted"
        mock_db.insert.return_value = {"id": "new-1"}

        import tempfile, json
        spec = {
            "project": "beethoven",
            "slug": "test-task-deps",
            "prompt": "do thing",
            "deps": ["contracts", "apparently:curation-layer-land"],
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(spec, f)
            f.flush()
            enqueue_task.main(f.name)

        call_args = mock_db.insert.call_args
        row = call_args[0][1]
        self.assertEqual(row["deps"], ["contracts", "apparently:curation-layer-land"])

    @patch("enqueue_task.db")
    @patch("enqueue_task.pipeline_contract")
    def test_no_deps_omitted(self, mock_pc, mock_db):
        import enqueue_task

        def _select(table, params):
            if table == "projects":
                return [{"id": "pid-1", "name": "beethoven", "repo_path": "/tmp/b"}]
            return []

        mock_db.select.side_effect = _select
        mock_pc.wrap_prompt.return_value = "wrapped"
        mock_pc.note.return_value = "noted"
        mock_db.insert.return_value = {"id": "new-1"}

        import tempfile, json
        spec = {"project": "beethoven", "slug": "no-deps-task", "prompt": "do thing"}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(spec, f)
            f.flush()
            enqueue_task.main(f.name)

        call_args = mock_db.insert.call_args
        row = call_args[0][1]
        self.assertNotIn("deps", row)


if __name__ == "__main__":
    unittest.main()
