#!/usr/bin/env python3
"""Tests for objective_intake.py - parsing and idempotent ingestion."""
import sys, os, types, unittest, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

_inserted = []
_existing_goals = []

_db_mod = types.ModuleType("db")
def _fake_select(table, params=None):
    if table == "goals":
        return list(_existing_goals)
    return []
def _fake_insert(table, row, **kw):
    _inserted.append(row)
_db_mod.select = _fake_select
_db_mod.insert = _fake_insert
_db_mod.update = lambda *a, **k: None
sys.modules["db"] = _db_mod

import objective_intake


class TestParseObjectives(unittest.TestCase):
    def test_basic_parse(self):
        text = "- Raise coverage to 80% | metric: coverage_pct | target: 80 | project: beethoven"
        r = objective_intake.parse_objectives(text)
        self.assertEqual(len(r), 1)
        self.assertEqual(r[0]["objective"], "Raise coverage to 80%")
        self.assertEqual(r[0]["metric"], "coverage_pct")
        self.assertEqual(r[0]["target"], "80")
        self.assertEqual(r[0]["project"], "beethoven")

    def test_minimal_objective(self):
        text = "- Fix all bugs"
        r = objective_intake.parse_objectives(text)
        self.assertEqual(len(r), 1)
        self.assertEqual(r[0]["objective"], "Fix all bugs")
        self.assertNotIn("metric", r[0])

    def test_skip_comments(self):
        text = "# Header\n- Real objective"
        r = objective_intake.parse_objectives(text)
        self.assertEqual(len(r), 1)

    def test_skip_empty_lines(self):
        text = "\n\n- Objective\n\n"
        r = objective_intake.parse_objectives(text)
        self.assertEqual(len(r), 1)

    def test_skip_non_list_lines(self):
        text = "Some text\n- Real item\nMore text"
        r = objective_intake.parse_objectives(text)
        self.assertEqual(len(r), 1)

    def test_multiple_objectives(self):
        text = "- First\n- Second | metric: x | target: 5\n- Third"
        r = objective_intake.parse_objectives(text)
        self.assertEqual(len(r), 3)

    def test_empty_input(self):
        r = objective_intake.parse_objectives("")
        self.assertEqual(len(r), 0)

    def test_only_comments(self):
        r = objective_intake.parse_objectives("# Just a header\n# Another")
        self.assertEqual(len(r), 0)

    def test_malformed_pipe_fields_skipped(self):
        text = "- Good objective | badfield without colon | metric: ok"
        r = objective_intake.parse_objectives(text)
        self.assertEqual(len(r), 1)
        self.assertEqual(r[0]["metric"], "ok")
        self.assertNotIn("badfield without colon", r[0])

    def test_priority_field(self):
        text = "- Important thing | priority: 1"
        r = objective_intake.parse_objectives(text)
        self.assertEqual(r[0]["priority"], "1")

    def test_status_defaults_active(self):
        text = "- Something"
        r = objective_intake.parse_objectives(text)
        self.assertEqual(r[0]["status"], "active")

    def test_empty_list_item(self):
        text = "- "
        r = objective_intake.parse_objectives(text)
        self.assertEqual(len(r), 0)

    def test_whitespace_handling(self):
        text = "-   Lots of spaces   |  metric :  val  "
        r = objective_intake.parse_objectives(text)
        self.assertEqual(r[0]["objective"], "Lots of spaces")
        self.assertEqual(r[0]["metric"], "val")

    def test_unknown_keys_ignored(self):
        text = "- Obj | unknown: val | metric: m"
        r = objective_intake.parse_objectives(text)
        self.assertNotIn("unknown", r[0])
        self.assertEqual(r[0]["metric"], "m")


class TestIngest(unittest.TestCase):
    def setUp(self):
        global _inserted, _existing_goals
        _inserted = []
        _existing_goals = []

    def test_ingest_from_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write("- Objective one\n- Objective two\n")
            f.flush()
            ins, skip = objective_intake.ingest(f.name)
        os.unlink(f.name)
        self.assertEqual(ins, 2)
        self.assertEqual(skip, 0)
        self.assertEqual(len(_inserted), 2)

    def test_idempotent_skip_existing(self):
        global _existing_goals
        _existing_goals = [{"objective": "Already here"}]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write("- Already here\n- New one\n")
            f.flush()
            ins, skip = objective_intake.ingest(f.name)
        os.unlink(f.name)
        self.assertEqual(ins, 1)
        self.assertEqual(skip, 1)

    def test_idempotent_case_insensitive(self):
        global _existing_goals
        _existing_goals = [{"objective": "UPPER CASE"}]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write("- upper case\n")
            f.flush()
            ins, skip = objective_intake.ingest(f.name)
        os.unlink(f.name)
        self.assertEqual(ins, 0)
        self.assertEqual(skip, 1)

    def test_missing_file(self):
        ins, skip = objective_intake.ingest("/nonexistent/path.md")
        self.assertEqual(ins, 0)
        self.assertEqual(skip, 0)

    def test_empty_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write("")
            f.flush()
            ins, skip = objective_intake.ingest(f.name)
        os.unlink(f.name)
        self.assertEqual(ins, 0)

    def test_duplicate_within_file(self):
        """Same objective twice in one file -> only inserted once."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write("- Same thing\n- Same thing\n")
            f.flush()
            ins, skip = objective_intake.ingest(f.name)
        os.unlink(f.name)
        self.assertEqual(ins, 1)
        self.assertEqual(skip, 1)

    def test_db_select_failure_still_inserts(self):
        """If db.select fails, we still try to insert (no dedup but no crash)."""
        old = _db_mod.select
        _db_mod.select = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("fail"))
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write("- Test obj\n")
            f.flush()
            ins, skip = objective_intake.ingest(f.name)
        os.unlink(f.name)
        _db_mod.select = old
        self.assertEqual(ins, 1)


if __name__ == "__main__":
    unittest.main()
