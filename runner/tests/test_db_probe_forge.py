"""db_probe_forge: demand → proposal specs → deduped draft PRs (mocked gh)."""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import db_probe_forge as F  # noqa: E402


CLASSIF = {"memo_kind": "access_control_and_least_privilege",
           "arguments": [{"key": "row_level_isolation", "strength": "undermined"},
                         {"key": "anon_surface_minimal", "strength": "unassessed"},
                         {"key": "privileged_paths_bounded", "strength": "unassessed"}]}


class DemandTest(unittest.TestCase):
    def test_uncovered_arguments(self):
        with patch.object(F.db, "select_all", lambda *a, **k: [CLASSIF, dict(CLASSIF)]):
            out = F.uncovered_arguments()
        self.assertEqual(out, {"access_control_and_least_privilege": ["anon_surface_minimal", "privileged_paths_bounded"]})

    def test_db_error_is_empty_not_raise(self):
        with patch.object(F.db, "select_all", side_effect=RuntimeError("down")):
            self.assertEqual(F.uncovered_arguments(), {})

    def test_all_covered_is_empty(self):
        covered = {"memo_kind": "x", "arguments": []}
        with patch.object(F.db, "select_all", lambda *a, **k: [covered]):
            self.assertEqual(F.uncovered_arguments(), {})


class SpecTest(unittest.TestCase):
    def test_spec_shape_and_safety(self):
        s = F.spec_for("access_control_and_least_privilege", "privileged_paths_bounded")
        self.assertTrue(s["probe_id"].startswith("forge_access_"), s["probe_id"])
        self.assertIn("assert_read_only", s["sql_sketch"])
        self.assertIn("-- TODO(host-model)", s["sql_sketch"], "SQL never ships runnable half-scaffolds")
        self.assertEqual(s["tier"], "cheap") and self.assertIn(s["category"], ("security", "privacy", "availability"))
        md = F.proposal_md(s)
        self.assertIn(s["probe_id"], md) and self.assertIn("privileged_paths_bounded", md)

    def test_probe_ids_sanitize(self):
        pid = F._probe_id_for("m", "weird ARG !! key 123")
        self.assertTrue(all(c.islower() or c.isdigit() or c == "_" for c in pid))


class FileProposalsTest(unittest.TestCase):
    def test_dedupe_then_create(self):
        calls = []

        def gh(method, path, body=None):
            calls.append((method, path))
            if "/pulls" in path and method == "GET":
                return []
            if path.count("/") == 2 and method == "GET":
                return {"default_branch": "master"}
            if path.endswith("/git/ref/heads/master"):
                return {"object": {"sha": "b" * 40}}
            if method == "POST" and path.endswith("/git/refs"):
                return {"ref": body["ref"]}
            if method == "PUT":
                return {"content": {}}
            if method == "POST" and path.endswith("/pulls"):
                return {"html_url": "https://example.test/pr/99"}
            return {}

        spec = F.spec_for("access_control_and_least_privilege", "privileged_paths_bounded")
        res = F.file_proposals(gh, [spec])
        self.assertTrue(res[0]["ok"]) and res[0]["pr"].endswith("pr/99")
        self.assertTrue(any("docs/db-probe-proposals/privileged_paths_bounded.md" in p for _m, p in calls))

    def test_existing_open_pr_skips_everything(self):
        def gh(method, path, body=None):
            if "/pulls" in path and method == "GET":
                return [{"html_url": "https://example.test/pr/5"}]
            raise AssertionError("no other call needed when the PR exists")
        res = F.file_proposals(gh, [F.spec_for("x", "k")])
        self.assertTrue(res[0]["ok"]) and res[0]["skipped"] == "open PR exists"


class ForgeRunTest(unittest.TestCase):
    def test_plan_mode_lists_specs_without_gh(self):
        with patch.object(F.db, "select_all", lambda *a, **k: [CLASSIF]), \
             patch.object(F, "ENABLED", False):
            out = F.forge_run(gh=lambda *a, **k: self.fail("no gh in plan mode"))
        self.assertEqual(len(out["planned"]), 2)
        self.assertIn("plan-only", out["note"]) and out.get("results") == []

    def test_zero_demand_short_circuits(self):
        with patch.object(F.db, "select_all", lambda *a, **k: []):
            out = F.forge_run(gh=lambda *a, **k: self.fail("no gh"))
        self.assertIn("evidence coverage", out["note"])


if __name__ == "__main__":
    unittest.main()
