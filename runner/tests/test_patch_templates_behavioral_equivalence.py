#!/usr/bin/env python3
"""Behavioral-equivalence characterization tests for `patch_templates`.

The two-session reconciliation repeatedly re-integrated `runner/patch_templates.py`
(adaptation directive, template lookup, branch recovery), and each pass claimed
"preserve existing behavior" without anything that could actually falsify that
claim. Rebases then dropped the work silently because no test failed.

This module pins the OBSERVABLE contract of the module as it exists on master, so
any future re-integration that changes output — not just one that fails to compile
— is caught. Every assertion below is a property of the CURRENT implementation and
is deliberately independent of the internal refactorings in flight:

- `_id`/`build` are deterministic and depend only on (slug, prompt intent)
- `build` output is byte-identical when the merged-diff library yields no hits
- adaptation failures are fail-soft: a raising `patch_adaptation` must not change
  the no-hits body beyond the "Prior merged patterns" line
- `lookup` fail-soft contract: `{}` on None/empty/unknown, corrupt JSONL, dead DB
- `inject_prompt`/`pre_claim_hook` are idempotent, prefix-preserving, and never
  raise — `pre_claim_hook` must return the input task unchanged on any error
"""
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("ORCH_DB_URL", "")
os.environ.setdefault("ORCH_DB_ENABLED", "false")

import patch_templates as pt

TASK = {"slug": "demo-slug", "prompt": "Add a webhook route and a migration test", "kind": "build"}


def _no_hits():
    """Force build() down the no-prior-patterns path deterministically."""
    return patch.dict(sys.modules, {"merged_diff_library": None})


class IdentityTest(unittest.TestCase):
    """_id and _intent are pure functions of slug + prompt."""

    def test_id_is_deterministic(self):
        self.assertEqual(pt._id(TASK), pt._id(dict(TASK)))

    def test_id_is_twelve_hex_chars(self):
        tid = pt._id(TASK)
        self.assertEqual(len(tid), 12)
        int(tid, 16)  # raises if not hex

    def test_id_ignores_fields_outside_slug_and_prompt(self):
        other = dict(TASK, kind="bugfix", attempt=7, project_id="whatever")
        self.assertEqual(pt._id(TASK), pt._id(other))

    def test_id_changes_with_slug(self):
        self.assertNotEqual(pt._id(TASK), pt._id(dict(TASK, slug="other-slug")))

    def test_id_changes_with_prompt(self):
        self.assertNotEqual(pt._id(TASK), pt._id(dict(TASK, prompt="totally different words")))

    def test_words_are_lowercased_deduped_and_sorted(self):
        words = pt._words("Alpha ALPHA bravo Charlie alpha")
        self.assertEqual(words, sorted(set(words)))
        self.assertEqual(words, [w.lower() for w in words])

    def test_words_drops_short_tokens(self):
        self.assertTrue(all(len(w) > 4 for w in pt._words("a bb ccc dddd eeeee ffffff")))

    def test_words_is_fail_soft_on_none(self):
        self.assertEqual(pt._words(None), [])

    def test_intent_on_empty_task_returns_empty_lists(self):
        intent = pt._intent({})
        self.assertEqual(intent["words"], [])
        self.assertEqual(intent["hints"], [])


class BuildOutputTest(unittest.TestCase):
    """build() emits a stable, byte-identical scaffold when there are no hits."""

    def test_build_is_byte_identical_across_calls(self):
        with _no_hits():
            first = pt.build(TASK)
            second = pt.build(dict(TASK))
        self.assertEqual(first, second)

    def test_build_returns_the_same_id_as_the_id_helper(self):
        with _no_hits():
            tid, _ = pt.build(TASK)
        self.assertEqual(tid, pt._id(TASK))

    def test_build_header_and_acceptance_lines_are_pinned(self):
        with _no_hits():
            tid, body = pt.build(TASK)
        lines = body.split("\n")
        self.assertEqual(lines[0], f"PATCH TEMPLATE {tid}")
        self.assertTrue(lines[1].startswith("Intent: "))
        self.assertEqual(
            lines[2],
            "Acceptance: preserve existing behavior, make the smallest mergeable diff, run build/tests.",
        )
        self.assertEqual(lines[3], "Implementation slots:")

    def test_build_emits_exactly_three_implementation_slots(self):
        with _no_hits():
            _, body = pt.build(TASK)
        slots = [ln for ln in body.split("\n") if ln[:2] in ("1.", "2.", "3.")]
        self.assertEqual(len(slots), 3)

    def test_build_no_hits_ends_with_the_none_found_note(self):
        with _no_hits():
            _, body = pt.build(TASK)
        self.assertTrue(
            body.endswith("Prior merged patterns to adapt: none found; keep the patch template reusable.")
        )

    def test_build_is_fail_soft_when_the_diff_library_raises(self):
        boom = type(sys)("merged_diff_library")
        boom.find = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("library down"))
        with patch.dict(sys.modules, {"merged_diff_library": boom}):
            tid, body = pt.build(TASK)
        self.assertEqual(tid, pt._id(TASK))
        self.assertIn("none found", body)

    def test_adaptation_failure_does_not_alter_the_rest_of_the_body(self):
        """A raising patch_adaptation must be swallowed; the scaffold survives."""
        lib = type(sys)("merged_diff_library")
        lib.find = lambda *a, **k: [
            {"project": "p", "slug": "s", "similarity": 0.5, "summary": "prior"}
        ]
        bad = type(sys)("patch_adaptation")
        bad.directive = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("adaptation down"))
        with patch.dict(sys.modules, {"merged_diff_library": lib, "patch_adaptation": bad}):
            tid, body = pt.build(TASK)
        self.assertEqual(tid, pt._id(TASK))
        self.assertIn("Prior merged patterns to adapt:", body)
        # Match the hit payload, not the whole line: a sibling slice labels each hit
        # with whether it carries a real diff, and that prefix is an intended change.
        # Pinning the full line here would turn this equivalence test into a veto on it.
        self.assertIn("p/s sim=0.5: prior", body)


class LookupContractTest(unittest.TestCase):
    """lookup() never raises and returns {} for every miss."""

    def test_none_and_empty_ids_return_empty(self):
        for bad in (None, "", "   "):
            self.assertEqual(pt.lookup(bad), {})

    def test_missing_fallback_file_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(pt, "_fallback_path", return_value=os.path.join(tmp, "nope.jsonl")):
                with patch.object(pt.db, "select", side_effect=RuntimeError("db down")):
                    self.assertEqual(pt.lookup("deadbeef0000"), {})

    def test_corrupt_jsonl_lines_are_skipped_not_raised(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "t.jsonl")
            with open(path, "w") as f:
                f.write("{not json at all\n")
                f.write(json.dumps({"template_id": "aaaabbbbcccc", "body": "B"}) + "\n")
            with patch.object(pt, "_fallback_path", return_value=path):
                self.assertEqual(pt.lookup("aaaabbbbcccc").get("body"), "B")

    def test_newest_matching_entry_wins(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "t.jsonl")
            with open(path, "w") as f:
                f.write(json.dumps({"template_id": "aaaabbbbcccc", "body": "old"}) + "\n")
                f.write(json.dumps({"template_id": "aaaabbbbcccc", "body": "new"}) + "\n")
            with patch.object(pt, "_fallback_path", return_value=path):
                self.assertEqual(pt.lookup("aaaabbbbcccc").get("body"), "new")

    def test_dead_db_is_swallowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(pt, "_fallback_path", return_value=os.path.join(tmp, "x.jsonl")):
                with patch.object(pt.db, "select", side_effect=Exception("boom")):
                    self.assertEqual(pt.lookup("aaaabbbbcccc"), {})


class InjectionTest(unittest.TestCase):
    """inject_prompt / pre_claim_hook are idempotent and prefix-only."""

    def test_inject_prefixes_the_original_prompt_verbatim(self):
        with _no_hits():
            out = pt.inject_prompt(TASK)
        self.assertTrue(out["prompt"].endswith(TASK["prompt"]))
        self.assertIn(pt.MARK, out["prompt"])

    def test_inject_is_idempotent(self):
        with _no_hits():
            once = pt.inject_prompt(TASK)
            twice = pt.inject_prompt(once)
        self.assertEqual(once["prompt"], twice["prompt"])

    def test_inject_preserves_every_other_task_field(self):
        with _no_hits():
            out = pt.inject_prompt(dict(TASK, kind="bugfix", attempt=3))
        self.assertEqual(out["slug"], TASK["slug"])
        self.assertEqual(out["kind"], "bugfix")
        self.assertEqual(out["attempt"], 3)

    def test_pre_claim_hook_is_idempotent(self):
        with _no_hits(), patch.object(pt, "_ensure_branch"), patch.object(pt, "_store"):
            once = pt.pre_claim_hook(dict(TASK))
            twice = pt.pre_claim_hook(once)
        self.assertEqual(once["prompt"], twice["prompt"])

    def test_pre_claim_hook_never_writes_back_to_the_db(self):
        """Regression guard for the 2026-07-11 prompt-corruption incident."""
        with _no_hits(), patch.object(pt, "_ensure_branch"), patch.object(pt, "_store"):
            with patch.object(pt.db, "update") as upd:
                pt.pre_claim_hook(dict(TASK))
        upd.assert_not_called()

    def test_pre_claim_hook_returns_input_unchanged_on_non_dict(self):
        for bad in (None, "string", 42, ["list"]):
            self.assertIs(pt.pre_claim_hook(bad), bad)

    def test_pre_claim_hook_returns_input_unchanged_when_build_raises(self):
        task = dict(TASK)
        with patch.object(pt, "_ensure_branch"), patch.object(pt, "build", side_effect=RuntimeError("x")):
            self.assertIs(pt.pre_claim_hook(task), task)

    def test_pre_claim_hook_skips_already_marked_prompts(self):
        marked = dict(TASK, prompt=f"{pt.MARK}abc123abc123]\nalready done")
        self.assertIs(pt.pre_claim_hook(marked), marked)


if __name__ == "__main__":
    unittest.main()
