"""Tests for agentic_repair error handling and recovery mechanisms.

Validates that:
  - Technical vs replacement categories are classified correctly
  - Repair prompts are built safely without leaking secrets
  - Max prompt length is enforced
  - Edge cases (None, empty, unknown) fail gracefully
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import agentic_repair
import db


class TestCategoryClassification(unittest.TestCase):
    """Verify is_technical and replacement_required handle all categories."""

    def test_technical_categories(self):
        # REWRITTEN. This used to assert that "noop" and "transient" are technical. They are not,
        # and deliberately so: is_technical() is documented as "categories with a CONCRETE
        # technical failure signal a coder can act on directly", and a no-op run or a flake
        # carries no such signal — that is exactly the case the module's _BLIND_DIRECTIVE and
        # _never_ran_patch() exist to handle instead. The real set is _TECHNICAL_CATEGORIES;
        # assert its full membership so adding or dropping one is a visible change.
        for cat in ("buildfail", "testfail", "timeout", "conflict", "regressfail", "missing-branch"):
            self.assertTrue(agentic_repair.is_technical(cat), f"{cat} should be technical")
        self.assertEqual(
            set(agentic_repair._TECHNICAL_CATEGORIES),
            {"buildfail", "testfail", "timeout", "conflict", "regressfail", "missing-branch"})

    def test_signal_free_categories_are_not_technical(self):
        # REWRITTEN companion to the above: the categories the old test wrongly demanded be
        # technical must stay OUT, or a blind repair would be handed the technical directive and
        # told to act on evidence it does not have.
        for cat in ("noop", "transient", "flake", "rework", "capacity", "orphaned-running"):
            self.assertFalse(agentic_repair.is_technical(cat), f"{cat} must not be technical")

    def test_replacement_categories(self):
        for cat in ("legal", "secret", "security"):
            self.assertTrue(agentic_repair.replacement_required(cat), f"{cat} should require replacement")
            self.assertFalse(agentic_repair.is_technical(cat), f"{cat} should NOT be technical")

    def test_category_matching_is_case_insensitive(self):
        # ADDED: both predicates lower() their argument before the set lookup, and callers pass
        # categories straight off DB rows.
        self.assertTrue(agentic_repair.is_technical("BuildFail"))
        self.assertTrue(agentic_repair.replacement_required("SECRET"))

    def test_absent_category_is_neither_technical_nor_replacement(self):
        # REWRITTEN (was test_none_defaults_to_technical, which asserted is_technical(None) is
        # True). Nothing in the module defaults an absent category to technical: both predicates
        # are `str(category or "").lower() in <frozenset>`, and "" is in neither set. That is the
        # safe reading — an unknown category carries no evidence, so claiming it carries a
        # concrete technical signal would route a blind repair down the technical path.
        for missing in (None, "", "unknown-xyz"):
            self.assertFalse(agentic_repair.is_technical(missing), repr(missing))
            self.assertFalse(agentic_repair.replacement_required(missing), repr(missing))


class TestOriginalPrompt(unittest.TestCase):
    """Verify original_prompt extracts and truncates safely."""

    def test_basic_prompt_extraction(self):
        task = {"slug": "fix-bug", "prompt": "Fix the login bug in auth.py"}
        result = agentic_repair._original_prompt(task)
        self.assertEqual(result, "Fix the login bug in auth.py")

    def test_missing_prompt_yields_empty_and_slug_fallback_lives_in_the_builder(self):
        # REWRITTEN (was test_missing_prompt_uses_slug, asserting "my-task" in
        # _original_prompt({"slug": "my-task", "prompt": None})). It tested the wrong function.
        # original_prompt() only strips repair directives off an EXISTING prompt and returns ""
        # when there is none — and it must, because repair_patch() writes its result straight
        # back to tasks.prompt, so inventing a slug sentence there would overwrite the real
        # specification of any task whose caller did not select the prompt column. The slug
        # fallback is in in_session_prompt(), which is where this now asserts it.
        task = {"slug": "my-task", "prompt": None}
        self.assertEqual(agentic_repair._original_prompt(task), "")
        built = agentic_repair.in_session_prompt(task, "boom", category="testfail")
        self.assertTrue(built.startswith("Complete the task 'my-task'."), built[:80])

    def test_empty_task_does_not_crash(self):
        self.assertEqual(agentic_repair._original_prompt({}), "")

    def test_prompt_length_bounded(self):
        # Tightened from `<= MAX_PROMPT_CHARS + 500` (a bound so loose an off-by-hundreds
        # truncation bug would pass) to the exact documented cap.
        long_prompt = "x" * 50000
        task = {"slug": "long", "prompt": long_prompt}
        result = agentic_repair._original_prompt(task)
        self.assertEqual(len(result), agentic_repair.MAX_PROMPT_CHARS)

    def test_stacked_repair_directives_are_stripped_back_to_the_original(self):
        # ADDED: this is original_prompt()'s stated reason for existing — a task repaired N times
        # must carry exactly one directive, not N stacked contradicting ones.
        task = {"slug": "s", "prompt": "Do the real work."}
        once = agentic_repair.in_session_prompt(task, "fail one", category="testfail")
        twice = agentic_repair.in_session_prompt({**task, "prompt": once}, "fail two",
                                                 category="buildfail")
        self.assertEqual(twice.count(agentic_repair.MARKER), 1)
        self.assertEqual(agentic_repair._original_prompt({"prompt": twice}), "Do the real work.")


class TestMarkerConstant(unittest.TestCase):
    """Ensure the repair marker is stable for downstream parsing."""

    def test_marker_value(self):
        self.assertEqual(agentic_repair.MARKER, "AGENTIC-REPAIR DIRECTIVE")

    def test_marker_is_the_boundary_original_prompt_cuts_on(self):
        # REWRITTEN (was test_marker_in_technical_set: `assertIn("rework",
        # agentic_repair.TECHNICAL_CATEGORIES)`). Two things were wrong — there is no public
        # TECHNICAL_CATEGORIES (the set is _TECHNICAL_CATEGORIES), and "rework" is not in it;
        # "rework" is the DEFAULT category of repair_patch(), which is a different thing.
        # Nor is a marker a category. What actually makes MARKER load-bearing is that
        # original_prompt() cuts on the exact string "\n\n" + MARKER + "\n", so the marker's
        # spelling AND its surrounding whitespace are a parsing contract between the two
        # functions. That round trip is what this now asserts.
        built = agentic_repair.in_session_prompt({"slug": "s", "prompt": "Body."}, "failure text")
        self.assertIn("\n\n" + agentic_repair.MARKER + "\n", built)
        self.assertEqual(agentic_repair._original_prompt({"prompt": built}), "Body.")

    def test_repair_prompt_includes_agentic_artifacts_when_available(self):
        # REWRITTEN. This used to patch sys.modules["task_artifacts"] with a mock whose
        # get_artifacts() returned commit_sha/touched_files/patch_diff, then assert those values
        # appeared in the prompt. agentic_repair never imports task_artifacts — grep the module:
        # the prior-run artifact block is filled from the TASK ROW's own touched_files and
        # commit_sha columns, so the mock could not have been consulted and the assertions were
        # passing/failing on the mock's own return_value, not on any product behaviour. The
        # intent (prior-run artifacts reach the repair prompt) is preserved against the real
        # source of those values.
        task = {
            "id": "t2",
            "slug": "add-widget",
            "prompt": "Add a new widget.",
            "commit_sha": "abc1234",
            "touched_files": '["src/widget.py", "tests/test_widget.py"]',
        }
        prompt = agentic_repair.repair_prompt(task, "some failure", "Fix it.", category="testfail")

        self.assertIn("Agentic analysis artifacts from prior run:", prompt)
        self.assertIn("Touched files from prior run: [\"src/widget.py\", \"tests/test_widget.py\"]", prompt)
        self.assertIn("Prior commit SHA: abc1234", prompt)
        self.assertIn("Repair category: testfail", prompt)
        self.assertIn("Original task slug: add-widget", prompt)
        self.assertIn("Fix it.", prompt)
        self.assertIn("Failure context:", prompt)
        self.assertIn("some failure", prompt)

    def test_repair_prompt_marks_artifacts_unknown_when_the_row_has_none(self):
        # REWRITTEN (was test_repair_prompt_is_unchanged_when_no_artifacts, which asserted
        # "Agentic analysis artifacts" is ABSENT when a mocked task_artifacts module returned
        # None). The block is unconditional in in_session_prompt(); what varies is its content,
        # which degrades to the literal "unknown" when the row carries no commit_sha /
        # touched_files. That is the behaviour the coder agent actually sees, and asserting the
        # placeholders is what would catch a regression that quietly dropped the real values.
        task = {
            "id": "t3",
            "slug": "new-feature",
            "prompt": "Implement new feature.",
        }
        prompt = agentic_repair.repair_prompt(task, "build failed", "Fix the build.", category="buildfail")

        self.assertIn("Touched files from prior run: unknown", prompt)
        self.assertIn("Prior commit SHA: unknown", prompt)
        self.assertIn("Failure context:", prompt)
        self.assertIn("build failed", prompt)
        self.assertIn(agentic_repair.MARKER, prompt)
        self.assertTrue(prompt.startswith("Implement new feature."), prompt[:60])

    def test_true_counters_are_fail_soft_when_the_control_plane_is_unreachable(self):
        # REWRITTEN (was test_agentic_artifacts_context_is_fail_soft_on_import_error, calling
        # agentic_repair._agentic_artifacts_context — a function that exists nowhere in the repo,
        # so the test only ever raised AttributeError). agentic_repair has exactly one lazy-import
        # + fail-soft path, _true_counters(), which re-reads remediation_count/attempt by id when
        # the caller selected a narrow column set. Substituting the nearest REAL fail-soft
        # behaviour: a db that raises must degrade to the row's own values, never propagate —
        # otherwise a control-plane blip takes down every repair call site at once.
        task = {"id": "abc"}  # neither counter selected -> forces the db re-read
        with patch.object(db, "select", side_effect=RuntimeError("control plane down")):
            self.assertEqual(agentic_repair._true_counters(task), (0, 0))
        with patch.object(db, "select", return_value=[{"remediation_count": 6, "attempt": 170}]):
            self.assertEqual(agentic_repair._true_counters(task), (6, 170))

    def test_true_counters_prefer_the_row_and_skip_the_read(self):
        # ADDED: the read is only supposed to happen when a counter is genuinely absent.
        with patch.object(db, "select", side_effect=AssertionError("must not query")) as sel:
            self.assertEqual(
                agentic_repair._true_counters({"id": "abc", "remediation_count": 2, "attempt": 5}),
                (2, 5))
            sel.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
