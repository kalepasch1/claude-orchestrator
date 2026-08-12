#!/usr/bin/env python3
"""Tests for runner/diff_abstraction.py — in-diff duplication → helper proposals."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import diff_abstraction as da

# Two handlers with the same guard, copy-pasted and renamed. This is the case
# text-based duplicate detection misses.
COPY_PASTE_DIFF = """diff --git a/runner/handler_a.py b/runner/handler_a.py
--- a/runner/handler_a.py
+++ b/runner/handler_a.py
@@ -1,2 +1,8 @@
+def handle_alpha(task):
+    slug = str(task.get("slug") or "")
+    if not slug:
+        return {}
+    repo = lookup_repo(slug)
+    return repo
diff --git a/runner/handler_b.py b/runner/handler_b.py
--- a/runner/handler_b.py
+++ b/runner/handler_b.py
@@ -1,2 +1,8 @@
+def handle_beta(item):
+    name = str(item.get("name") or "")
+    if not name:
+        return {}
+    path = lookup_path(name)
+    return path
"""

UNIQUE_DIFF = """diff --git a/runner/only.py b/runner/only.py
--- a/runner/only.py
+++ b/runner/only.py
@@ -1,2 +1,5 @@
+def compute(x):
+    total = x * 2
+    return total
"""

TS_DIFF = """diff --git a/web/a.ts b/web/a.ts
--- a/web/a.ts
+++ b/web/a.ts
@@ -0,0 +1,6 @@
+export function readAlpha(id: string) {
+  const key = shardKey(id)
+  if (!key) return null
+  return store.read(key)
+}
diff --git a/web/b.ts b/web/b.ts
--- a/web/b.ts
+++ b/web/b.ts
@@ -0,0 +1,6 @@
+export function readBeta(name: string) {
+  const slot = bucketKey(name)
+  if (!slot) return null
+  return cache.read(slot)
+}
"""


class TestAddedBlocks(unittest.TestCase):
    def test_splits_by_file_and_run(self):
        blocks = da.added_blocks(COPY_PASTE_DIFF)
        self.assertEqual(len(blocks), 2)
        self.assertEqual(blocks[0]["file"], "runner/handler_a.py")
        self.assertEqual(blocks[1]["file"], "runner/handler_b.py")
        self.assertEqual(len(blocks[0]["lines"]), 6)

    def test_headers_are_not_treated_as_added_lines(self):
        for block in da.added_blocks(COPY_PASTE_DIFF):
            for line in block["lines"]:
                self.assertFalse(line.startswith("++"))

    def test_fail_soft(self):
        for bad in (None, "", "   ", 0, b"", []):
            self.assertEqual(da.added_blocks(bad), [])


class TestDefinitions(unittest.TestCase):
    def test_python_functions(self):
        names = {d["name"] for d in da.definitions(COPY_PASTE_DIFF)}
        self.assertEqual(names, {"handle_alpha", "handle_beta"})

    def test_typescript_functions(self):
        defs = da.definitions(TS_DIFF)
        self.assertEqual({d["name"] for d in defs}, {"readAlpha", "readBeta"})
        self.assertTrue(all(d["kind"] == "function" for d in defs))

    def test_classes(self):
        diff = "diff --git a/a.py b/a.py\n@@ -0,0 +1,2 @@\n+class Widget:\n+    pass\n"
        self.assertEqual(da.definitions(diff)[0], {
            "name": "Widget", "kind": "class", "params": "", "file": "a.py", "line": 1})

    def test_records_file_and_line(self):
        d = da.definitions(COPY_PASTE_DIFF)[0]
        self.assertEqual(d["file"], "runner/handler_a.py")
        self.assertEqual(d["line"], 1)

    def test_empty_input(self):
        self.assertEqual(da.definitions(None), [])


class TestNormalize(unittest.TestCase):
    def test_renamed_identifiers_collapse_to_one_fingerprint(self):
        a = ["slug = str(task.get('slug') or '')", "if not slug:", "  return {}"]
        b = ["name = str(item.get('name') or '')", "if not name:", "  return {}"]
        self.assertEqual(da.normalize(a), da.normalize(b))
        self.assertEqual(da.fingerprint(a), da.fingerprint(b))

    def test_keywords_survive_so_structure_still_distinguishes(self):
        a = ["if not slug:", "  return {}"]
        b = ["while not slug:", "  return {}"]
        self.assertNotEqual(da.normalize(a), da.normalize(b))

    def test_literals_are_erased(self):
        self.assertEqual(da.normalize(["x = 41"]), da.normalize(["y = 9999"]))

    def test_comments_and_blank_lines_are_ignored(self):
        self.assertEqual(da.normalize(["# note", "", "x = 1"]), da.normalize(["x = 2"]))

    def test_accepts_a_string(self):
        self.assertEqual(da.normalize("x = 1\ny = 2"), da.normalize(["x = 1", "y = 2"]))

    def test_empty_yields_empty_fingerprint(self):
        self.assertEqual(da.fingerprint([]), "")
        self.assertEqual(da.fingerprint(["# only a comment"]), "")


class TestFindDuplicates(unittest.TestCase):
    def test_detects_copy_paste_and_rename_across_files(self):
        dups = da.find_duplicates(COPY_PASTE_DIFF)
        self.assertEqual(len(dups), 1)
        g = dups[0]
        self.assertEqual(g["occurrences"], 2)
        self.assertEqual(g["files"], ["runner/handler_a.py", "runner/handler_b.py"])
        self.assertFalse(g["identical_text"])

    def test_detects_typescript_duplication(self):
        self.assertEqual(len(da.find_duplicates(TS_DIFF)), 1)

    def test_unique_code_produces_nothing(self):
        self.assertEqual(da.find_duplicates(UNIQUE_DIFF), [])

    def test_min_lines_suppresses_trivial_repeats(self):
        diff = ("diff --git a/a.py b/a.py\n@@\n+x = 1\n-\n+y = 2\n"
                "diff --git a/b.py b/b.py\n@@\n+p = 1\n-\n+q = 2\n")
        self.assertEqual(da.find_duplicates(diff), [])

    def test_min_occurrences_is_respected(self):
        self.assertEqual(da.find_duplicates(COPY_PASTE_DIFF, min_occurrences=3), [])

    def test_identical_text_is_flagged(self):
        half = ("+def f(a):\n+    guard = check(a)\n+    if not guard:\n+        return None\n")
        diff = f"diff --git a/a.py b/a.py\n@@\n{half}diff --git a/b.py b/b.py\n@@\n{half}"
        self.assertTrue(da.find_duplicates(diff)[0]["identical_text"])

    def test_fail_soft(self):
        for bad in (None, "", 0, b""):
            self.assertEqual(da.find_duplicates(bad), [])


class TestNoiseSuppression(unittest.TestCase):
    def test_the_same_site_seen_twice_is_not_duplication(self):
        # A multi-commit stream replays the same block; it is one site, not two.
        single = ("diff --git a/a.py b/a.py\n@@\n"
                  "+def f(a):\n+    g = check(a)\n+    if not g:\n+        return None\n")
        self.assertEqual(da.find_duplicates(single + single), [])

    def test_import_only_blocks_are_boilerplate(self):
        self.assertTrue(da.is_boilerplate(["import os", "import sys", "from x import y"]))

    def test_field_declaration_blocks_are_boilerplate(self):
        self.assertTrue(da.is_boilerplate(["child_id: str = \"\"", "parent_id: str = \"\"",
                                           "school_id: str = \"\""]))

    def test_real_logic_is_not_boilerplate(self):
        self.assertFalse(da.is_boilerplate(["slug = str(task.get('slug') or '')",
                                            "if not slug:", "    return {}"]))

    def test_boilerplate_blocks_are_excluded_from_duplicates(self):
        block = "+import os\n+import sys\n+from pathlib import Path\n"
        diff = f"diff --git a/a.py b/a.py\n@@\n{block}diff --git a/b.py b/b.py\n@@\n{block}"
        self.assertEqual(da.find_duplicates(diff), [])

    def test_is_boilerplate_fail_soft(self):
        for bad in (None, [], [""], [None]):
            self.assertTrue(da.is_boilerplate(bad))


class TestProposals(unittest.TestCase):
    def test_proposal_shape_and_rationale(self):
        p = da.propose_abstractions(COPY_PASTE_DIFF)[0]
        self.assertEqual(p["occurrences"], 2)
        self.assertEqual(p["confidence"], "high")
        self.assertTrue(p["name"].endswith("_helper"))
        self.assertTrue(any("copy-paste-and-rename" in r for r in p["rationale"]))
        self.assertGreater(p["saves_lines"], 0)

    def test_proposed_name_never_collides_with_a_definition_in_the_diff(self):
        for p in da.propose_abstractions(COPY_PASTE_DIFF):
            self.assertNotIn(p["name"], {d["name"] for d in da.definitions(COPY_PASTE_DIFF)})

    def test_no_duplication_no_proposals(self):
        self.assertEqual(da.propose_abstractions(UNIQUE_DIFF), [])

    def test_fail_soft(self):
        for bad in (None, "", 0, b"", []):
            self.assertEqual(da.propose_abstractions(bad), [])


class TestRenderDocument(unittest.TestCase):
    def test_renders_sites_rationale_and_sample(self):
        doc = da.render_document(da.propose_abstractions(COPY_PASTE_DIFF), title="Test doc")
        self.assertIn("# Test doc", doc)
        self.assertIn("**Sites:**", doc)
        self.assertIn("**Rationale:**", doc)
        self.assertIn("runner/handler_a.py:1", doc)
        self.assertIn("```", doc)

    def test_empty_proposals_render_nothing(self):
        for bad in ([], None, ["junk"]):
            self.assertEqual(da.render_document(bad), "")


class TestAnalyze(unittest.TestCase):
    def test_one_call_entry_point(self):
        r = da.analyze(COPY_PASTE_DIFF)
        self.assertEqual(len(r["definitions"]), 2)
        self.assertEqual(len(r["duplicates"]), 1)
        self.assertEqual(len(r["proposals"]), 1)
        self.assertIn("Identified abstractions", r["document"])

    def test_analyze_is_fail_soft(self):
        r = da.analyze(None)
        self.assertEqual(r["definitions"], [])
        self.assertEqual(r["document"], "")


if __name__ == "__main__":
    unittest.main()
