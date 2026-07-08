import os
import sys
import types
import tempfile
import shutil
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import prompt_factory as pf


class SlugifyTest(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(pf._slugify("Ship the new feature!"), "ship-the-new-feature")

    def test_collapses_repeated_punctuation(self):
        self.assertEqual(pf._slugify("cut $/task 30%"), "cut-task-30")

    def test_empty_falls_back(self):
        self.assertEqual(pf._slugify(""), "objective")

    def test_truncates_long_text(self):
        self.assertLessEqual(len(pf._slugify("x" * 200)), 60)


class ExtractProofTest(unittest.TestCase):
    def test_extracts_backtick_proof_line(self):
        text = "Do the thing.\nProof: `npm test` exits 0"
        self.assertEqual(pf._extract_proof(text, {}), "`npm test` exits 0")

    def test_extracts_acceptance_test_phrasing(self):
        text = "Build X. Acceptance test: pytest tests/test_x.py passes"
        self.assertIn("pytest", pf._extract_proof(text, {}))

    def test_falls_back_to_project_test_cmd(self):
        text = "Build X with no proof mentioned anywhere."
        self.assertEqual(pf._extract_proof(text, {"test_cmd": "npm run test:ci"}), "npm run test:ci")

    def test_falls_back_to_default_when_no_project_row(self):
        with patch.dict(os.environ, {"TEST_CMD": "make test"}):
            self.assertEqual(pf._extract_proof("no proof here", None), "make test")


class GatherObjectivesTest(unittest.TestCase):
    def test_returns_rows_from_goals_table(self):
        rows = [{"objective": "a"}, {"objective": "b"}]
        with patch.object(pf, "db", types.SimpleNamespace(select=lambda *a, **kw: rows)):
            result = pf.gather_objectives()
        self.assertEqual(result, rows)

    def test_db_failure_returns_empty_list(self):
        broken = types.SimpleNamespace(select=lambda *a, **kw: (_ for _ in ()).throw(OSError("down")))
        with patch.object(pf, "db", broken):
            result = pf.gather_objectives()
        self.assertEqual(result, [])


class GatherBlockersTest(unittest.TestCase):
    def test_db_failure_returns_empty_list(self):
        broken = types.SimpleNamespace(select=lambda *a, **kw: (_ for _ in ()).throw(OSError("down")))
        with patch.object(pf, "db", broken):
            result = pf.gather_blockers()
        self.assertEqual(result, [])

    def test_filters_out_recently_updated_rows(self):
        import datetime
        recent = (datetime.datetime.now(datetime.timezone.utc)).isoformat()
        rows = [{"id": "1", "slug": "s1", "state": "BLOCKED", "updated_at": recent}]
        with patch.object(pf, "db", types.SimpleNamespace(select=lambda *a, **kw: rows)):
            result = pf.gather_blockers()
        self.assertEqual(result, [])

    def test_includes_old_rows(self):
        import datetime
        old = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=3)).isoformat()
        rows = [{"id": "1", "slug": "s1", "state": "BLOCKED", "updated_at": old}]
        with patch.object(pf, "db", types.SimpleNamespace(select=lambda *a, **kw: rows)):
            result = pf.gather_blockers()
        self.assertEqual(len(result), 1)

    def test_unparsable_timestamp_is_treated_as_old(self):
        rows = [{"id": "1", "slug": "s1", "state": "BLOCKED", "updated_at": "not-a-date"}]
        with patch.object(pf, "db", types.SimpleNamespace(select=lambda *a, **kw: rows)):
            result = pf.gather_blockers()
        self.assertEqual(len(result), 1)

    def test_respects_limit(self):
        import datetime
        old = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=3)).isoformat()
        rows = [{"id": str(i), "slug": f"s{i}", "state": "BLOCKED", "updated_at": old} for i in range(10)]
        with patch.object(pf, "db", types.SimpleNamespace(select=lambda *a, **kw: rows)):
            result = pf.gather_blockers(limit=2)
        self.assertEqual(len(result), 2)


class KpiGapsStubTest(unittest.TestCase):
    def test_returns_empty_list(self):
        self.assertEqual(pf.gather_kpi_gaps(), [])


class RenderObjectiveDagTest(unittest.TestCase):
    def test_renders_tasks_with_prefixed_ids_and_deps(self):
        planner_mock = types.SimpleNamespace(plan=lambda master, repo=None: [
            {"slug": "contracts", "prompt": "define contracts. proof: `pytest` passes", "deps": [], "model_hint": "opus"},
            {"slug": "impl", "prompt": "implement it. proof: `pytest` passes", "deps": ["contracts"], "model_hint": "sonnet"},
        ])
        with patch.dict(sys.modules, {"planner": planner_mock}):
            slug, entries = pf.render_objective_dag({"objective": "Ship feature X"}, {"repo_path": "/tmp"})
        self.assertEqual(len(entries), 2)
        self.assertTrue(entries[0]["id"].startswith(f"factory-{slug}-"))
        self.assertIn(f"factory-{slug}-contracts", entries[1]["depends"])
        self.assertEqual(entries[1]["model"], "claude-sonnet-4-6")

    def test_includes_metric_and_target_in_master_prompt(self):
        seen = {}

        def fake_plan(master, repo=None):
            seen["master"] = master
            return [{"slug": "t1", "prompt": "x", "deps": [], "model_hint": "haiku"}]

        with patch.dict(sys.modules, {"planner": types.SimpleNamespace(plan=fake_plan)}):
            pf.render_objective_dag({"objective": "cut cost", "metric": "$/task", "target": "-30%"}, {})
        self.assertIn("$/task", seen["master"])
        self.assertIn("-30%", seen["master"])

    def test_planner_failure_propagates_not_silently_empty(self):
        broken_planner = types.SimpleNamespace(plan=lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("boom")))
        with patch.dict(sys.modules, {"planner": broken_planner}):
            with self.assertRaises(RuntimeError):
                pf.render_objective_dag({"objective": "x"}, {})


class RenderBlockerTaskTest(unittest.TestCase):
    def test_renders_single_unblock_task(self):
        blocker = {"id": "t1", "slug": "flaky-thing", "state": "TESTFAIL", "note": "test flakes 30% of the time"}
        slug, entries = pf.render_blocker_task(blocker, {"test_cmd": "npm test"})
        self.assertEqual(len(entries), 1)
        self.assertIn("flaky-thing", entries[0]["prompt"])
        self.assertIn("TESTFAIL", entries[0]["prompt"])
        self.assertEqual(entries[0]["proof"], "npm test")

    def test_missing_note_does_not_crash(self):
        blocker = {"id": "t1", "slug": "s", "state": "BLOCKED"}
        slug, entries = pf.render_blocker_task(blocker, {})
        self.assertIn("no note recorded", entries[0]["prompt"])


class RenderIntakeFileTest(unittest.TestCase):
    def test_produces_canonical_format(self):
        entries = [{"id": "factory-x-t1", "title": "Do a thing", "material": False, "model": "haiku",
                   "depends": [], "proof": "`pytest` passes", "prompt": "line1\nline2"}]
        text = pf._render_intake_file("beethoven", entries)
        self.assertIn("PROJECT: beethoven", text)
        self.assertIn("- id: factory-x-t1", text)
        self.assertIn("material: no", text)
        self.assertIn("model: haiku", text)
        self.assertIn("proof: `pytest` passes", text)
        self.assertIn("    line1", text)
        self.assertIn("    line2", text)

    def test_material_yes_rendering(self):
        entries = [{"id": "x", "title": "t", "material": True, "model": "", "depends": [],
                   "proof": "p", "prompt": "x"}]
        text = pf._render_intake_file("proj", entries)
        self.assertIn("material: yes", text)

    def test_depends_line_only_when_present(self):
        entries = [{"id": "x", "title": "t", "material": False, "model": "", "depends": ["a", "b"],
                   "proof": "p", "prompt": "x"}]
        text = pf._render_intake_file("proj", entries)
        self.assertIn("depends: [a, b]", text)


class AlreadyShippedTest(unittest.TestCase):
    def setUp(self):
        self._orig_intake = pf.INTAKE_DIR
        self._orig_processed = pf.PROCESSED_DIR
        pf.INTAKE_DIR = tempfile.mkdtemp()
        pf.PROCESSED_DIR = os.path.join(pf.INTAKE_DIR, "processed")
        os.makedirs(pf.PROCESSED_DIR)

    def tearDown(self):
        shutil.rmtree(pf.INTAKE_DIR, ignore_errors=True)
        pf.INTAKE_DIR = self._orig_intake
        pf.PROCESSED_DIR = self._orig_processed

    def test_not_shipped_when_nothing_exists(self):
        with patch.object(pf, "db", types.SimpleNamespace(select=lambda *a, **kw: [])):
            self.assertFalse(pf._already_shipped("newthing"))

    def test_shipped_when_open_file_exists(self):
        open(os.path.join(pf.INTAKE_DIR, "factory-x.md"), "w").close()
        self.assertTrue(pf._already_shipped("x"))

    def test_shipped_when_processed_file_exists(self):
        open(os.path.join(pf.PROCESSED_DIR, "20260101-000000-factory-x.md"), "w").close()
        self.assertTrue(pf._already_shipped("x"))

    def test_shipped_when_matching_task_already_queued(self):
        with patch.object(pf, "db", types.SimpleNamespace(select=lambda *a, **kw: [{"id": "1"}])):
            self.assertTrue(pf._already_shipped("x"))

    def test_db_error_does_not_block_ship_check_on_file_absence(self):
        broken = types.SimpleNamespace(select=lambda *a, **kw: (_ for _ in ()).throw(OSError("down")))
        with patch.object(pf, "db", broken):
            self.assertFalse(pf._already_shipped("nothingexists"))


class RunIntegrationTest(unittest.TestCase):
    def setUp(self):
        self._orig_intake = pf.INTAKE_DIR
        self._orig_processed = pf.PROCESSED_DIR
        pf.INTAKE_DIR = tempfile.mkdtemp()
        pf.PROCESSED_DIR = os.path.join(pf.INTAKE_DIR, "processed")
        os.makedirs(pf.PROCESSED_DIR)

    def tearDown(self):
        shutil.rmtree(pf.INTAKE_DIR, ignore_errors=True)
        pf.INTAKE_DIR = self._orig_intake
        pf.PROCESSED_DIR = self._orig_processed

    def test_run_with_no_intake_dir_is_a_noop(self):
        shutil.rmtree(pf.INTAKE_DIR)
        result = pf.run()
        self.assertEqual(result["written"], 0)

    def test_run_writes_one_file_per_objective(self):
        goal = {"objective": "Ship widget", "project": "beethoven"}
        proj = {"id": "p1", "name": "beethoven", "repo_path": "/tmp"}
        planner_mock = types.SimpleNamespace(plan=lambda master, repo=None: [
            {"slug": "contracts", "prompt": "define. proof: `pytest` passes", "deps": [], "model_hint": "opus"},
        ])
        db_mock = types.SimpleNamespace(select=lambda table, params=None: (
            [goal] if table == "goals" else
            [proj] if table == "projects" else
            [] if table == "tasks" else []
        ))
        with patch.object(pf, "db", db_mock), \
             patch.dict(sys.modules, {"planner": planner_mock}):
            result = pf.run()
        self.assertEqual(result["written"], 1)
        self.assertTrue(os.path.isfile(os.path.join(pf.INTAKE_DIR, "factory-ship-widget.md")))

    def test_run_respects_max_open_cap(self):
        for i in range(pf.MAX_OPEN):
            open(os.path.join(pf.INTAKE_DIR, f"factory-existing-{i}.md"), "w").close()
        with patch.object(pf, "db", types.SimpleNamespace(select=lambda *a, **kw: [])):
            result = pf.run()
        self.assertEqual(result["written"], 0)
        self.assertEqual(result.get("reason"), "at cap")

    def test_run_skips_already_shipped_objective(self):
        goal = {"objective": "Ship widget", "project": "beethoven"}
        open(os.path.join(pf.INTAKE_DIR, "factory-ship-widget.md"), "w").close()
        db_mock = types.SimpleNamespace(select=lambda table, params=None: (
            [goal] if table == "goals" else []
        ))
        with patch.object(pf, "db", db_mock):
            result = pf.run()
        self.assertEqual(result["written"], 0)
        self.assertGreaterEqual(result["skipped"], 1)

    def test_run_never_calls_planner_for_already_shipped_objective(self):
        # render_objective_dag() -> planner.plan() is a real model call; an already-shipped
        # objective must be skipped BEFORE that call, not after (regression: the first cut of
        # this loop decomposed every objective before checking shipped-status at all).
        goal = {"objective": "Ship widget", "project": "beethoven"}
        open(os.path.join(pf.INTAKE_DIR, "factory-ship-widget.md"), "w").close()
        db_mock = types.SimpleNamespace(select=lambda table, params=None: (
            [goal] if table == "goals" else []
        ))
        exploding_planner = types.SimpleNamespace(
            plan=lambda *a, **kw: (_ for _ in ()).throw(AssertionError("planner.plan must not be called")))
        with patch.object(pf, "db", db_mock), \
             patch.dict(sys.modules, {"planner": exploding_planner}):
            pf.run()  # must not raise

    def test_run_continues_past_one_bad_objective(self):
        goals = [{"objective": "bad one", "project": "beethoven"},
                 {"objective": "good one", "project": "beethoven"}]
        proj = {"id": "p1", "name": "beethoven", "repo_path": "/tmp"}
        calls = {"n": 0}

        def flaky_plan(master, repo=None):
            calls["n"] += 1
            if "bad" in master:
                raise RuntimeError("decomposition exploded")
            return [{"slug": "t1", "prompt": "x. proof: `pytest`", "deps": [], "model_hint": "haiku"}]

        db_mock = types.SimpleNamespace(select=lambda table, params=None: (
            goals if table == "goals" else [proj] if table == "projects" else []
        ))
        with patch.object(pf, "db", db_mock), \
             patch.dict(sys.modules, {"planner": types.SimpleNamespace(plan=flaky_plan)}):
            result = pf.run()
        self.assertEqual(result["written"], 1)  # the good one still landed


if __name__ == "__main__":
    unittest.main()
