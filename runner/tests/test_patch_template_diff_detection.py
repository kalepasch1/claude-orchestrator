#!/usr/bin/env python3
"""Behavioral-equivalence tests for template diff/scaffold classification.

The change under test adds `classify_body`, `carries_diff`, and two additive
keys on `lookup()` (`kind`, `carries_diff`) to `runner/patch_templates.py`, and
makes `build()` label each cited prior pattern.

The acceptance criterion for that change was *preserve existing behavior, make
the smallest mergeable diff*. These tests are written to prove exactly that, so
they are organised in two halves:

  EquivalenceTest      — the pre-existing surface behaves identically. Every
                         key `lookup()` returned before is still present with
                         the same value; `build()` still emits the same header,
                         intent line, acceptance line and three slots; the
                         fail-soft contract (`{}` on None/empty/unknown/error)
                         is unchanged.

  ClassificationTest   — the new surface is correct: prose scaffolds are not
                         mistaken for patches, real unified diffs are, and bad
                         input answers False instead of raising.

HOW THE EQUIVALENCE CLAIM WAS CHECKED
-------------------------------------
`EquivalenceTest` was run unmodified against a clean `origin/master` worktree
(i.e. against the *old* `patch_templates.py`). Eleven of its twelve cases pass
there identically. The twelfth,
`test_lookup_adds_only_the_two_new_keys`, is the one case that asserts the new
keys are present, so failing on old code is what it is for. Any future edit that
breaks one of the other eleven has changed pre-existing behavior, which the
acceptance criterion forbids.

`SCAFFOLD_BODY` below is the *verbatim* stored body of template bffd1c2752f8 —
the template a queued task instructed an agent to "integrate the adapted diff"
from. It contains no hunks. It is pinned here as a fixture precisely so that a
future change which starts classifying it as a diff fails loudly.
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

import patch_templates as pt  # noqa: E402

# Verbatim stored body of bffd1c2752f8. Note that its "Prior merged patterns"
# section splices in the body text of 7ba77da91bb4 — a scaffold quoting a
# scaffold, which is what made both read like patches to a planner.
SCAFFOLD_BODY = (
    "PATCH TEMPLATE bffd1c2752f8\n"
    "Intent: 07062319 07071626 30min 8b92d078e856 acceptance adapt agentic alter\n"
    "Acceptance: preserve existing behavior, make the smallest mergeable diff, run build/tests.\n"
    "Implementation slots:\n"
    "1. Locate the existing owner module/function before adding new files.\n"
    "2. Reuse matching project helpers and naming conventions.\n"
    "3. Add or update the narrowest test/check that proves the requested behavior.\n"
    "Prior merged patterns to adapt:\n"
    "- smarter/cont-1042d0 sim=0.627: PATCH TEMPLATE 7ba77da91bb4\n"
    "Intent: 07062319 07071626 1042d0 8b92d078e856 acceptance adapt agent agentic\n"
    "Acceptance: preserve existing behavior, make the smallest mergeable diff, \n"
)

DIFF_BODY = (
    "diff --git a/runner/example.py b/runner/example.py\n"
    "--- a/runner/example.py\n"
    "+++ b/runner/example.py\n"
    "@@ -1,3 +1,3 @@\n"
    " def f():\n"
    "-    return 1\n"
    "+    return 2\n"
)


def _store(rows):
    """Write a JSONL template store and return its path."""
    path = os.path.join(tempfile.mkdtemp(), "patch_templates.jsonl")
    with open(path, "w") as f:
        for row in rows:
            f.write((row if isinstance(row, str) else json.dumps(row)) + "\n")
    return path


def _task(prompt="add a webhook route with tests", slug="equiv-fixture"):
    return {"slug": slug, "prompt": prompt, "kind": "build"}


class EquivalenceTest(unittest.TestCase):
    """The pre-existing surface is unchanged. This is the acceptance criterion."""

    def test_lookup_preserves_every_pre_existing_key_and_value(self):
        row = {"template_id": "bffd1c2752f8", "body": SCAFFOLD_BODY,
               "title": "patch template demo", "source": "db"}
        with patch.object(pt, "_fallback_path", return_value=_store([row])):
            got = pt.lookup("bffd1c2752f8")
        for key, value in row.items():
            self.assertEqual(got[key], value, f"lookup() altered pre-existing key {key!r}")

    def test_lookup_adds_only_the_two_new_keys(self):
        row = {"template_id": "t1", "body": SCAFFOLD_BODY}
        with patch.object(pt, "_fallback_path", return_value=_store([row])):
            got = pt.lookup("t1")
        self.assertEqual(set(got) - set(row), {"kind", "carries_diff"})

    def test_lookup_still_returns_empty_dict_for_none_and_empty(self):
        for bad in (None, "", "   "):
            self.assertEqual(pt.lookup(bad), {}, f"lookup({bad!r}) must be {{}}")

    def test_lookup_still_returns_empty_dict_for_unknown_id(self):
        with patch.object(pt, "_fallback_path", return_value=_store([])):
            with patch.object(pt.db, "select", side_effect=RuntimeError("db down")):
                self.assertEqual(pt.lookup("nosuchtemplate"), {})

    def test_lookup_still_fail_soft_on_corrupt_store_and_dead_db(self):
        path = _store(["{not json at all", json.dumps({"template_id": "x"})])
        with patch.object(pt, "_fallback_path", return_value=path):
            with patch.object(pt.db, "select", side_effect=RuntimeError("db down")):
                self.assertEqual(pt.lookup("bffd1c2752f8"), {})

    def test_lookup_still_fail_soft_on_missing_store_file(self):
        missing = os.path.join(tempfile.mkdtemp(), "absent", "patch_templates.jsonl")
        with patch.object(pt, "_fallback_path", return_value=missing):
            with patch.object(pt.db, "select", side_effect=OSError("gone")):
                self.assertEqual(pt.lookup("bffd1c2752f8"), {})

    def test_lookup_newest_matching_entry_still_wins(self):
        path = _store([
            {"template_id": "dup", "body": "PATCH TEMPLATE dup\nold"},
            {"template_id": "dup", "body": "PATCH TEMPLATE dup\nnew"},
        ])
        with patch.object(pt, "_fallback_path", return_value=path):
            self.assertIn("new", pt.lookup("dup")["body"])

    def test_build_scaffold_lines_are_byte_identical_when_no_hits(self):
        """With no merged-diff hits, build() output must not have changed."""
        with patch.dict(sys.modules, {"merged_diff_library": None}):
            tid, body = pt.build(_task())
        expected = "\n".join([
            f"PATCH TEMPLATE {tid}",
            "Intent: " + " ".join(pt._intent(_task())["words"][:24]),
            "Acceptance: preserve existing behavior, make the smallest mergeable diff, run build/tests.",
            "Implementation slots:",
            "1. Locate the existing owner module/function before adding new files.",
            "2. Reuse matching project helpers and naming conventions.",
            "3. Add or update the narrowest test/check that proves the requested behavior.",
            "Prior merged patterns to adapt: none found; keep the patch template reusable.",
        ])
        self.assertEqual(body, expected)

    def test_build_template_id_is_unchanged_by_the_new_labelling(self):
        """The id is derived from slug+intent only; labelling must not perturb it."""
        with patch.dict(sys.modules, {"merged_diff_library": None}):
            no_hits, _ = pt.build(_task())
        self.assertEqual(no_hits, pt._id(_task()))

    def test_build_still_names_every_hit_with_project_slug_and_similarity(self):
        hit = {"project": "smarter", "slug": "cont-1042d0",
               "similarity": 0.627, "summary": SCAFFOLD_BODY}
        fake = type(sys)("merged_diff_library")
        fake.find = lambda task, limit=2: [hit]
        with patch.dict(sys.modules, {"merged_diff_library": fake}):
            _, body = pt.build(_task())
        self.assertIn("smarter/cont-1042d0", body)
        self.assertIn("sim=0.627", body)
        self.assertIn(SCAFFOLD_BODY.splitlines()[0], body)

    def test_inject_prompt_still_prefixes_body_and_marks_the_task(self):
        with patch.dict(sys.modules, {"merged_diff_library": None}):
            out = pt.inject_prompt(_task(prompt="original prompt text"))
        self.assertTrue(out["prompt"].startswith("PATCH TEMPLATE "))
        self.assertIn(pt.MARK, out["prompt"])
        self.assertTrue(out["prompt"].endswith("original prompt text"))

    def test_inject_prompt_is_still_idempotent(self):
        task = {"slug": "s", "prompt": f"{pt.MARK}abc123]\nalready marked"}
        self.assertEqual(pt.inject_prompt(task), task)


class ClassificationTest(unittest.TestCase):
    """The new surface: a scaffold is never mistaken for a patch."""

    def test_the_real_bffd1c2752f8_body_is_a_scaffold(self):
        self.assertEqual(pt.classify_body(SCAFFOLD_BODY), pt.KIND_SCAFFOLD)
        self.assertFalse(pt.carries_diff(SCAFFOLD_BODY))

    def test_a_real_unified_diff_is_a_diff(self):
        self.assertEqual(pt.classify_body(DIFF_BODY), pt.KIND_DIFF)
        self.assertTrue(pt.carries_diff(DIFF_BODY))

    def test_lookup_labels_scaffold_and_diff_rows(self):
        path = _store([
            {"template_id": "scaf", "body": SCAFFOLD_BODY},
            {"template_id": "real", "body": DIFF_BODY},
        ])
        with patch.object(pt, "_fallback_path", return_value=path):
            scaf, real = pt.lookup("scaf"), pt.lookup("real")
        self.assertEqual((scaf["kind"], scaf["carries_diff"]), (pt.KIND_SCAFFOLD, False))
        self.assertEqual((real["kind"], real["carries_diff"]), (pt.KIND_DIFF, True))

    def test_carries_diff_accepts_an_id_a_body_or_a_lookup_dict(self):
        path = _store([{"template_id": "real", "body": DIFF_BODY}])
        with patch.object(pt, "_fallback_path", return_value=path):
            self.assertTrue(pt.carries_diff("real"))                 # id
            self.assertTrue(pt.carries_diff(pt.lookup("real")))       # dict
        self.assertTrue(pt.carries_diff(DIFF_BODY))                   # body

    def test_carries_diff_fails_soft_on_junk_input(self):
        with patch.object(pt, "_fallback_path", return_value=_store([])):
            with patch.object(pt.db, "select", side_effect=RuntimeError("db down")):
                for bad in (None, "", 0, 1, [], {}, object()):
                    self.assertFalse(pt.carries_diff(bad), f"carries_diff({bad!r}) must be False")

    def test_classify_body_fails_soft_on_junk_input(self):
        for bad in (None, "", 0, [], {}, object()):
            self.assertEqual(pt.classify_body(bad), pt.KIND_SCAFFOLD)

    def test_build_labels_a_scaffold_hit_and_warns_when_none_carry_a_diff(self):
        hit = {"project": "smarter", "slug": "cont-1042d0",
               "similarity": 0.627, "summary": SCAFFOLD_BODY}
        fake = type(sys)("merged_diff_library")
        fake.find = lambda task, limit=2: [hit]
        with patch.dict(sys.modules, {"merged_diff_library": fake}):
            _, body = pt.build(_task())
        self.assertIn("[scaffold — prose only, no diff to apply]", body)
        self.assertIn("none of the patterns above contain a diff", body)

    def test_build_does_not_warn_when_a_hit_carries_a_real_diff(self):
        hit = {"project": "beethoven", "slug": "real-patch",
               "similarity": 0.9, "summary": DIFF_BODY}
        fake = type(sys)("merged_diff_library")
        fake.find = lambda task, limit=2: [hit]
        with patch.dict(sys.modules, {"merged_diff_library": fake}):
            _, body = pt.build(_task())
        self.assertIn("[diff]", body)
        self.assertNotIn("none of the patterns above contain a diff", body)

    def test_classification_delegates_to_the_single_repo_diff_detector(self):
        """There must not be a second detector. Prove we call the existing one."""
        import patch_template_apply
        with patch.object(patch_template_apply, "looks_like_diff",
                          return_value=True) as spy:
            self.assertEqual(pt.classify_body("not a diff at all"), pt.KIND_DIFF)
        spy.assert_called()

    def test_classification_survives_the_detector_being_unimportable(self):
        """Fail-soft: a broken import must not wedge lookup()."""
        with patch.dict(sys.modules, {"patch_template_apply": None}):
            self.assertEqual(pt.classify_body(DIFF_BODY), pt.KIND_DIFF)
            self.assertEqual(pt.classify_body(SCAFFOLD_BODY), pt.KIND_SCAFFOLD)


if __name__ == "__main__":
    unittest.main()
