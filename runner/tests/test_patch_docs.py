"""The acceptance criterion for patches/ documentation, as a test that can fail.

    "Every .patch file has a corresponding .md file with a non-empty description for each
     hunk, and patches/README.md aggregates them correctly."

Written as a check rather than a one-off document on purpose: hand-written docs satisfy
that sentence for exactly as long as the directory does not change. The next recovered
patch lands undocumented and the index goes quietly stale, because nothing was watching.
"""
import os
import sys
import tempfile
import unittest

_RUNNER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_REPO = os.path.dirname(_RUNNER)
sys.path.insert(0, os.path.join(_REPO, "tools"))

import patch_docs as pd  # noqa: E402

SAMPLE = """diff --git a/runner/x.py b/runner/x.py
--- a/runner/x.py
+++ b/runner/x.py
@@ -10,3 +10,5 @@ def existing():
 context
-OLD_CONST = ("a", "b")
+# Bare nouns over-triggered the boost on incidental mentions.
+OLD_CONST = ("a b", "c d")
+EXTRA = 1
@@ -40,2 +42,3 @@ class Thing:
 context
+    def added_method(self):
+        pass
"""


class ParseTest(unittest.TestCase):
    def setUp(self):
        self.hunks = pd.parse_patch(SAMPLE)

    def test_finds_every_hunk(self):
        self.assertEqual(len(self.hunks), 2)

    def test_hunks_are_numbered_per_file(self):
        self.assertEqual([h["index"] for h in self.hunks], [1, 2])

    def test_attributes_the_right_file(self):
        self.assertTrue(all(h["file"] == "runner/x.py" for h in self.hunks))

    def test_counts_added_and_removed(self):
        self.assertEqual((self.hunks[0]["added"], self.hunks[0]["removed"]), (3, 1))

    def test_extracts_touched_symbols(self):
        self.assertIn("OLD_CONST", self.hunks[0]["symbols"])
        self.assertIn("added_method", self.hunks[1]["symbols"])

    def test_captures_author_rationale_from_added_comments(self):
        self.assertTrue(any("over-triggered" in r for r in self.hunks[0]["rationale"]))

    def test_empty_patch_is_not_an_error(self):
        self.assertEqual(pd.parse_patch(""), [])
        self.assertEqual(pd.parse_patch(None), [])


class SummaryTest(unittest.TestCase):
    """Concrete, not template-based: the text must reflect what the hunk does."""

    def setUp(self):
        self.hunks = pd.parse_patch(SAMPLE)

    def test_rewrite_names_the_symbol_it_rewrites(self):
        self.assertIn("OLD_CONST", pd.summarize(self.hunks[0]))

    def test_pure_addition_reads_as_an_addition(self):
        self.assertTrue(pd.summarize(self.hunks[1]).startswith("Adds"))

    def test_summaries_differ_between_hunks(self):
        self.assertNotEqual(pd.summarize(self.hunks[0]), pd.summarize(self.hunks[1]))

    def test_authors_own_reason_wins_over_inference(self):
        self.assertIn("over-triggered", pd.justify(self.hunks[0]))

    def test_prior_record_beats_inference_when_there_is_no_comment(self):
        self.assertEqual(pd.justify(self.hunks[1], "recovered from branch X"),
                         "recovered from branch X")

    def test_inference_is_still_specific_without_either(self):
        j = pd.justify(self.hunks[1])
        self.assertTrue(j)
        self.assertIn("additive", j.lower())


class AcceptanceTest(unittest.TestCase):
    """The stated acceptance criterion, applied to the real patches/ directory."""

    PATCH_DIR = os.path.join(_REPO, "patches")

    def _patches(self):
        if not os.path.isdir(self.PATCH_DIR):
            return []
        return [f for f in sorted(os.listdir(self.PATCH_DIR)) if f.endswith(".patch")]

    def test_every_patch_has_a_companion_doc(self):
        for name in self._patches():
            doc = os.path.join(self.PATCH_DIR, name + ".md")
            self.assertTrue(os.path.isfile(doc), f"missing {name}.md")

    def test_every_hunk_has_a_non_empty_description(self):
        for name in self._patches():
            with open(os.path.join(self.PATCH_DIR, name), errors="replace") as fh:
                hunks = pd.parse_patch(fh.read())
            with open(os.path.join(self.PATCH_DIR, name + ".md")) as fh:
                doc = fh.read()
            for h in hunks:
                head = f"## {h['file']} — hunk {h['index']}"
                self.assertIn(head, doc, f"{name}.md is missing {head}")
            for marker in ("**Summary:**", "**Justification:**"):
                self.assertEqual(doc.count(marker), len(hunks),
                                 f"{name}.md needs one {marker} per hunk")
            for line in doc.split("\n"):
                for marker in ("**Summary:**", "**Justification:**"):
                    if marker in line:
                        self.assertTrue(line.split(marker, 1)[1].strip(),
                                        f"empty {marker} in {name}.md")

    def test_index_exists_and_lists_every_patch(self):
        index = os.path.join(self.PATCH_DIR, "README.md")
        if not self._patches():
            return
        self.assertTrue(os.path.isfile(index), "patches/README.md is missing")
        with open(index) as fh:
            text = fh.read()
        for name in self._patches():
            self.assertIn(name, text, f"{name} is not in the index")

    def test_docs_are_not_stale(self):
        # regenerating must be a no-op — otherwise the docs no longer describe the patches
        wanted = pd.build(self.PATCH_DIR)
        stale = []
        for path, content in wanted.items():
            if not os.path.isfile(path):
                stale.append(os.path.basename(path))
                continue
            with open(path, errors="replace") as fh:
                if fh.read() != content:
                    stale.append(os.path.basename(path))
        self.assertEqual(stale, [],
                         "run `python3 tools/patch_docs.py --write`")


class GeneratorBehaviourTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_generates_a_doc_and_an_index_for_a_new_patch(self):
        with open(os.path.join(self.tmp.name, "new.patch"), "w") as fh:
            fh.write(SAMPLE)
        built = pd.build(self.tmp.name)
        names = {os.path.basename(p) for p in built}
        self.assertEqual(names, {"new.patch.md", "README.md"})

    def test_index_is_written_even_with_no_patches(self):
        built = pd.build(self.tmp.name)
        self.assertEqual({os.path.basename(p) for p in built}, {"README.md"})

    def test_missing_directory_is_not_an_error(self):
        self.assertEqual(pd.build("/no/such/patches"), {})

    def test_generation_is_deterministic(self):
        with open(os.path.join(self.tmp.name, "new.patch"), "w") as fh:
            fh.write(SAMPLE)
        self.assertEqual(pd.build(self.tmp.name), pd.build(self.tmp.name))

    def test_unreadable_patch_still_produces_a_doc(self):
        path = os.path.join(self.tmp.name, "bin.patch")
        with open(path, "wb") as fh:
            fh.write(b"\xff\xfe\x00binary")
        built = pd.build(self.tmp.name)
        self.assertIn(os.path.join(self.tmp.name, "bin.patch.md"), built)


if __name__ == "__main__":
    unittest.main()
