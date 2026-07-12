"""
test_intake_compiler.py - verify intake_compiler produces valid, watcher-parseable
intake blocks from coordination_task rows. No live DB — uses fixtures via injected client.
"""
import os, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import intake_compiler
import intake_watcher


def _sample_row(**overrides):
    row = {
        "id": "test-task-1",
        "slug": "test-task-1",
        "title": "Add feature X",
        "material": False,
        "model": "haiku",
        "depends": [],
        "proof": "`python -m pytest` exits 0",
        "prompt": "Implement feature X in runner/foo.py.\nMake it work.",
        "description": "",
    }
    row.update(overrides)
    return row


class FakeClient:
    """Injected client returning fixture rows instead of hitting Supabase."""
    def __init__(self, rows):
        self._rows = rows

    def fetch_queued(self):
        return list(self._rows)


class TestFormatTask(unittest.TestCase):

    def test_basic_format(self):
        row = _sample_row()
        block = intake_compiler._format_task(row)
        self.assertIn("- id: test-task-1", block)
        self.assertIn("  title: Add feature X", block)
        self.assertIn("  material: no", block)
        self.assertIn("  model: haiku", block)
        self.assertIn("  depends: []", block)
        self.assertIn("  prompt: |", block)
        self.assertIn("    Implement feature X", block)

    def test_material_yes(self):
        block = intake_compiler._format_task(_sample_row(material=True))
        self.assertIn("  material: yes", block)

    def test_depends_list(self):
        block = intake_compiler._format_task(_sample_row(depends=["a", "b"]))
        self.assertIn("  depends: [a, b]", block)


class TestCompileTasks(unittest.TestCase):

    def test_produces_canonical_output(self):
        rows = [_sample_row()]
        content, skipped = intake_compiler.compile_tasks(rows, "beethoven", intake_dir=tempfile.mkdtemp())
        self.assertTrue(content.startswith("PROJECT: beethoven"))
        self.assertEqual(skipped, [])

    def test_round_trippable_through_watcher(self):
        """Output must parse back through intake_watcher.parse() successfully."""
        rows = [_sample_row(slug="roundtrip-1", title="RT task", prompt="Do the thing.")]
        content, _ = intake_compiler.compile_tasks(rows, "myproject", intake_dir=tempfile.mkdtemp())
        tasks, operator = intake_watcher.parse(content)
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["slug"], "roundtrip-1")
        self.assertEqual(tasks[0]["project"], "myproject")
        self.assertIn("Do the thing", tasks[0]["prompt"])

    def test_multiple_tasks(self):
        rows = [_sample_row(slug="a"), _sample_row(slug="b")]
        content, _ = intake_compiler.compile_tasks(rows, "p", intake_dir=tempfile.mkdtemp())
        tasks, _ = intake_watcher.parse(content)
        self.assertEqual(len(tasks), 2)
        slugs = {t["slug"] for t in tasks}
        self.assertEqual(slugs, {"a", "b"})

    def test_dedup_skips_existing(self):
        """Tasks whose slug already exists in intake/ are skipped."""
        d = tempfile.mkdtemp()
        os.makedirs(os.path.join(d, "processed"), exist_ok=True)
        with open(os.path.join(d, "existing.md"), "w") as f:
            f.write("PROJECT: beethoven\n\n- id: already-here\n  title: old\n  prompt: |\n    x\n")
        rows = [_sample_row(slug="already-here"), _sample_row(slug="new-one")]
        content, skipped = intake_compiler.compile_tasks(rows, "beethoven", intake_dir=d)
        self.assertIn("already-here", skipped)
        tasks, _ = intake_watcher.parse(content)
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["slug"], "new-one")

    def test_empty_rows(self):
        content, skipped = intake_compiler.compile_tasks([], "p", intake_dir=tempfile.mkdtemp())
        self.assertEqual(content, "")
        self.assertEqual(skipped, [])


class TestRun(unittest.TestCase):

    def test_run_with_fixture_client(self):
        d = tempfile.mkdtemp()
        client = FakeClient([_sample_row(slug="from-queue")])
        path, skipped = intake_compiler.run(client=client, project_name="beethoven", intake_dir=d)
        self.assertIsNotNone(path)
        self.assertTrue(os.path.exists(path))
        with open(path) as f:
            content = f.read()
        tasks, _ = intake_watcher.parse(content)
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["slug"], "from-queue")

    def test_run_empty_queue(self):
        client = FakeClient([])
        path, skipped = intake_compiler.run(client=client, intake_dir=tempfile.mkdtemp())
        self.assertIsNone(path)


class TestEmitFile(unittest.TestCase):

    def test_writes_file(self):
        d = tempfile.mkdtemp()
        path = intake_compiler.emit_file("PROJECT: test\n", intake_dir=d, filename="test.md")
        self.assertTrue(os.path.exists(path))
        with open(path) as f:
            self.assertEqual(f.read(), "PROJECT: test\n")


if __name__ == "__main__":
    unittest.main()
