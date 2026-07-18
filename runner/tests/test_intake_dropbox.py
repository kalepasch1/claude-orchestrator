import os
import sys
import types
import tempfile
import shutil
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import intake_watcher as iw


class IsCanonicalTest(unittest.TestCase):
    def test_canonical_with_project_header(self):
        self.assertTrue(iw.is_canonical("PROJECT: beethoven\n\n- id: x\n"))

    def test_canonical_project_header_not_on_first_line(self):
        self.assertTrue(iw.is_canonical("# some title\n\nPROJECT: beethoven\n"))

    def test_freeform_text_is_not_canonical(self):
        self.assertFalse(iw.is_canonical("# MISSION: do a big thing\n\nSome prose here.\n"))

    def test_empty_text_is_not_canonical(self):
        self.assertFalse(iw.is_canonical(""))

    def test_none_text_is_not_canonical(self):
        self.assertFalse(iw.is_canonical(None))

    def test_project_mentioned_in_prose_is_not_canonical(self):
        # "PROJECT:" must start the line, not just appear anywhere
        self.assertFalse(iw.is_canonical("This is about the PROJECT: beethoven work item.\n"))


class DropboxSlugifyTest(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(iw._dropbox_slugify("# MISSION: Ship it"), "mission-ship-it")

    def test_empty_falls_back(self):
        self.assertEqual(iw._dropbox_slugify(""), "dropbox")


    def test_special_chars_stripped(self):
        self.assertEqual(iw._dropbox_slugify("# MISSION: Legal & Radar (v2)!"), "mission-legal-radar-v2")

    def test_consecutive_hyphens_collapsed(self):
        self.assertEqual(iw._dropbox_slugify("# Ship --- fast"), "ship-fast")

    def test_trailing_hyphens_trimmed(self):
        result = iw._dropbox_slugify("# trailing--- ")
        self.assertFalse(result.endswith("-"), f"slug should not end with hyphen: {result}")


class ExtractProofLineTest(unittest.TestCase):
    def test_extracts_proof(self):
        self.assertIn("pytest", iw._extract_proof_line("do x. Proof: `pytest` passes"))

    def test_no_proof_returns_empty(self):
        self.assertEqual(iw._extract_proof_line("nothing here"), "")


class DefaultProjectForDropboxTest(unittest.TestCase):
    def test_finds_mentioned_project(self):
        projects = {"beethoven": {}, "smarter": {}}
        text = "You are working in the smarter repo."
        self.assertEqual(iw._default_project_for_dropbox(text, projects), "smarter")

    def test_falls_back_to_beethoven_when_present(self):
        projects = {"beethoven": {}, "smarter": {}}
        text = "No project mentioned at all here."
        self.assertEqual(iw._default_project_for_dropbox(text, projects), "beethoven")

    def test_falls_back_to_first_project_when_no_beethoven(self):
        projects = {"onlyone": {}}
        text = "No project mentioned."
        self.assertEqual(iw._default_project_for_dropbox(text, projects), "onlyone")

    def test_empty_projects_returns_none(self):
        self.assertIsNone(iw._default_project_for_dropbox("text", {}))

    def test_only_scans_first_2000_chars(self):
        projects = {"beethoven": {}, "farproject": {}}
        text = ("x" * 2500) + " farproject mentioned way too late"
        self.assertEqual(iw._default_project_for_dropbox(text, projects), "beethoven")


class DecomposeFreeformTest(unittest.TestCase):
    def test_renders_tasks_with_dropbox_prefix(self):
        planner_mock = types.SimpleNamespace(plan=lambda master, repo=None: [
            {"slug": "contracts", "prompt": "define. proof: `pytest`", "deps": [], "model_hint": "opus"},
            {"slug": "impl", "prompt": "build it. proof: `pytest`", "deps": ["contracts"], "model_hint": "sonnet"},
        ])
        with patch.dict(sys.modules, {"planner": planner_mock}):
            rendered = iw.decompose_freeform("# MISSION: ship it", "/tmp", "beethoven")
        self.assertEqual(len(rendered), 2)
        self.assertTrue(rendered[0]["slug"].startswith("dropbox-mission-ship-it-"))
        self.assertIn(rendered[0]["slug"], rendered[1]["depends"])
        self.assertEqual(rendered[1]["model"], "sonnet")
        self.assertEqual(rendered[0]["project"], "beethoven")

    def test_all_tasks_non_material_by_default(self):
        planner_mock = types.SimpleNamespace(plan=lambda master, repo=None: [
            {"slug": "t1", "prompt": "x", "deps": [], "model_hint": "haiku"}])
        with patch.dict(sys.modules, {"planner": planner_mock}):
            rendered = iw.decompose_freeform("mission", "/tmp", "beethoven")
        self.assertFalse(rendered[0]["material"])

    def test_planner_import_failure_propagates(self):
        with patch.dict(sys.modules, {"planner": None}):
            with self.assertRaises(ImportError):
                iw.decompose_freeform("mission", "/tmp", "beethoven")


class QueueDropboxTasksTest(unittest.TestCase):
    def test_queues_new_tasks(self):
        rendered = [{"project": "beethoven", "slug": "dropbox-x-t1", "material": False,
                    "model": "haiku", "depends": [], "proof": "p", "prompt": "do it"}]
        projects = {"beethoven": {"id": "p1", "default_base": "master"}}
        inserted = []
        db_mock = types.SimpleNamespace(select=lambda *a, **kw: [], insert=lambda t, r: inserted.append(r))
        with patch.object(iw, "db", db_mock):
            created, skipped = iw._queue_dropbox_tasks(rendered, projects)
        self.assertEqual(created, 1)
        self.assertEqual(skipped, 0)
        self.assertEqual(inserted[0]["slug"], "dropbox-x-t1")

    def test_skips_already_queued_slug(self):
        rendered = [{"project": "beethoven", "slug": "dropbox-x-t1", "material": False,
                    "model": None, "depends": [], "proof": "", "prompt": "do it"}]
        projects = {"beethoven": {"id": "p1"}}
        db_mock = types.SimpleNamespace(select=lambda *a, **kw: [{"slug": "dropbox-x-t1"}],
                                        insert=lambda *a, **kw: (_ for _ in ()).throw(AssertionError("must not insert")))
        with patch.object(iw, "db", db_mock):
            created, skipped = iw._queue_dropbox_tasks(rendered, projects)
        self.assertEqual(created, 0)
        self.assertEqual(skipped, 1)

    def test_skips_unknown_project(self):
        rendered = [{"project": "nosuchproject", "slug": "dropbox-x-t1", "material": False,
                    "model": None, "depends": [], "proof": "", "prompt": "do it"}]
        db_mock = types.SimpleNamespace(select=lambda *a, **kw: [], insert=lambda *a, **kw: None)
        with patch.object(iw, "db", db_mock):
            created, skipped = iw._queue_dropbox_tasks(rendered, {})
        self.assertEqual(created, 0)
        self.assertEqual(skipped, 1)


class IngestDropboxPromptsTest(unittest.TestCase):
    def setUp(self):
        self.repo_root = tempfile.mkdtemp()
        self.intake = os.path.join(self.repo_root, "intake")
        self.processed = os.path.join(self.intake, "processed")
        os.makedirs(self.processed)
        self._patches = [
            patch.object(iw, "REPO_ROOT", self.repo_root),
            patch.object(iw, "INTAKE", self.intake),
            patch.object(iw, "PROCESSED", self.processed),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        shutil.rmtree(self.repo_root, ignore_errors=True)

    def _write_prompt(self, name, text):
        path = os.path.join(self.repo_root, name)
        with open(path, "w") as f:
            f.write(text)
        return path

    def test_canonical_prompt_file_is_left_alone(self):
        self._write_prompt("PROMPT-x.md", "PROJECT: beethoven\n\n- id: t1\n  prompt: |\n    do it\n")
        with patch.object(iw, "db", types.SimpleNamespace(select=lambda *a, **kw: [{"name": "beethoven", "id": "p1"}])):
            total = iw.ingest_dropbox_prompts({"beethoven": {"id": "p1"}})
        self.assertEqual(total, 0)
        self.assertTrue(os.path.isfile(os.path.join(self.repo_root, "PROMPT-x.md")))  # not moved

    def test_freeform_prompt_is_decomposed_and_moved(self):
        self._write_prompt("PROMPT-mission.md", "# MISSION: ship the thing\n\nDo the work.")
        planner_mock = types.SimpleNamespace(plan=lambda master, repo=None: [
            {"slug": "t1", "prompt": "do it. proof: `pytest`", "deps": [], "model_hint": "haiku"}])
        inserted = []
        db_mock = types.SimpleNamespace(select=lambda *a, **kw: [], insert=lambda t, r: inserted.append(r))
        with patch.object(iw, "db", db_mock), patch.dict(sys.modules, {"planner": planner_mock}):
            total = iw.ingest_dropbox_prompts({"beethoven": {"id": "p1", "default_base": "master"}})
        self.assertEqual(total, 1)
        self.assertFalse(os.path.isfile(os.path.join(self.repo_root, "PROMPT-mission.md")))
        moved = os.listdir(self.processed)
        self.assertTrue(any("dropbox-PROMPT-mission.md" in m for m in moved))

    def test_no_resolvable_project_is_claimed_not_left_in_place(self):
        # Claim-before-decompose (2026-07-08 fix): the file is moved as soon as it's confirmed
        # non-canonical, BEFORE project resolution or decomposition — decompose_freeform() calls
        # a real, non-deterministic model call, so leaving the file in place to "retry" on the
        # next tick risks queuing a second, differently-slugged batch of duplicate tasks instead
        # of safely re-reading a static file. See ingest_dropbox_prompts()'s docstring.
        self._write_prompt("PROMPT-orphan.md", "# do something for nobody in particular")
        db_mock = types.SimpleNamespace(select=lambda *a, **kw: [], insert=lambda *a, **kw: None)
        with patch.object(iw, "db", db_mock):
            total = iw.ingest_dropbox_prompts({})
        self.assertEqual(total, 0)
        self.assertFalse(os.path.isfile(os.path.join(self.repo_root, "PROMPT-orphan.md")))
        moved = os.listdir(self.processed)
        self.assertTrue(any("dropbox-PROMPT-orphan.md" in m for m in moved))

    def test_no_resolvable_project_files_an_approval_card(self):
        self._write_prompt("PROMPT-orphan.md", "# do something for nobody in particular")
        inserted = []
        db_mock = types.SimpleNamespace(select=lambda *a, **kw: [],
                                        insert=lambda t, r: inserted.append((t, r)))
        with patch.object(iw, "db", db_mock):
            iw.ingest_dropbox_prompts({})
        approval_inserts = [r for (t, r) in inserted if t == "approvals"]
        self.assertEqual(len(approval_inserts), 1)
        self.assertIn("orphan", approval_inserts[0]["title"])

    def test_decomposition_failure_on_one_file_does_not_block_others(self):
        self._write_prompt("PROMPT-bad.md", "# bad one")
        self._write_prompt("PROMPT-good.md", "# good one")

        def flaky_plan(master, repo=None):
            if "bad" in master:
                raise RuntimeError("boom")
            return [{"slug": "t1", "prompt": "x. proof: `pytest`", "deps": [], "model_hint": "haiku"}]

        db_mock = types.SimpleNamespace(select=lambda *a, **kw: [], insert=lambda *a, **kw: None)
        with patch.object(iw, "db", db_mock), \
             patch.dict(sys.modules, {"planner": types.SimpleNamespace(plan=flaky_plan)}):
            total = iw.ingest_dropbox_prompts({"beethoven": {"id": "p1"}})
        self.assertEqual(total, 1)
        # Both files are claimed (moved) regardless of decomposition outcome — see docstring.
        self.assertFalse(os.path.isfile(os.path.join(self.repo_root, "PROMPT-bad.md")))
        self.assertFalse(os.path.isfile(os.path.join(self.repo_root, "PROMPT-good.md")))
        moved = os.listdir(self.processed)
        self.assertTrue(any("dropbox-PROMPT-bad.md" in m for m in moved))
        self.assertTrue(any("dropbox-PROMPT-good.md" in m for m in moved))

    def test_decomposition_failure_files_an_approval_card_naming_the_claimed_path(self):
        self._write_prompt("PROMPT-bad.md", "# bad one")
        broken_planner = types.SimpleNamespace(plan=lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("kaboom")))
        inserted = []
        db_mock = types.SimpleNamespace(select=lambda *a, **kw: [],
                                        insert=lambda t, r: inserted.append((t, r)))
        with patch.object(iw, "db", db_mock), patch.dict(sys.modules, {"planner": broken_planner}):
            iw.ingest_dropbox_prompts({"beethoven": {"id": "p1"}})
        approval_inserts = [r for (t, r) in inserted if t == "approvals"]
        self.assertEqual(len(approval_inserts), 1)
        self.assertIn("kaboom", approval_inserts[0]["detail"])
        self.assertIn("dropbox-PROMPT-bad.md", approval_inserts[0]["detail"])

    def test_claim_failure_is_fail_soft_and_does_not_decompose(self):
        self._write_prompt("PROMPT-x.md", "# mission")
        exploding_planner = types.SimpleNamespace(
            plan=lambda *a, **kw: (_ for _ in ()).throw(AssertionError("must not decompose")))
        with patch("shutil.move", side_effect=OSError("disk full")), \
             patch.dict(sys.modules, {"planner": exploding_planner}):
            total = iw.ingest_dropbox_prompts({"beethoven": {"id": "p1"}})  # must not raise
        self.assertEqual(total, 0)

    def test_no_prompt_files_returns_zero(self):
        total = iw.ingest_dropbox_prompts({"beethoven": {"id": "p1"}})
        self.assertEqual(total, 0)

    def test_second_run_does_not_reprocess_moved_file(self):
        self._write_prompt("PROMPT-once.md", "# mission once")
        planner_mock = types.SimpleNamespace(plan=lambda master, repo=None: [
            {"slug": "t1", "prompt": "x", "deps": [], "model_hint": "haiku"}])
        db_mock = types.SimpleNamespace(select=lambda *a, **kw: [], insert=lambda *a, **kw: None)
        with patch.object(iw, "db", db_mock), patch.dict(sys.modules, {"planner": planner_mock}):
            first = iw.ingest_dropbox_prompts({"beethoven": {"id": "p1"}})
            second = iw.ingest_dropbox_prompts({"beethoven": {"id": "p1"}})
        self.assertEqual(first, 1)
        self.assertEqual(second, 0)


class RunIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.repo_root = tempfile.mkdtemp()
        self.intake = os.path.join(self.repo_root, "intake")
        self.processed = os.path.join(self.intake, "processed")
        os.makedirs(self.intake)
        self._patches = [
            patch.object(iw, "REPO_ROOT", self.repo_root),
            patch.object(iw, "INTAKE", self.intake),
            patch.object(iw, "PROCESSED", self.processed),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        shutil.rmtree(self.repo_root, ignore_errors=True)

    def test_run_survives_dropbox_scan_exception(self):
        with patch.object(iw, "ingest_dropbox_prompts", side_effect=RuntimeError("boom")), \
             patch.object(iw, "db", types.SimpleNamespace(select=lambda *a, **kw: [])):
            total = iw.run()  # must not raise
        self.assertEqual(total, 0)

    def test_run_combines_dropbox_and_canonical_totals(self):
        with patch.object(iw, "ingest_dropbox_prompts", return_value=2), \
             patch.object(iw, "db", types.SimpleNamespace(select=lambda *a, **kw: [])):
            total = iw.run()
        self.assertEqual(total, 2)


if __name__ == "__main__":
    unittest.main()
