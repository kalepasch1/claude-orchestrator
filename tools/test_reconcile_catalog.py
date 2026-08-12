#!/usr/bin/env python3
"""Tests for tools/reconcile_catalog.py — the acceptance test of the
'reconcile clean modifications' slice: every change in `reconciled/` is a
subset of the union of changes described in catalog.json, and no original line
ends up inconsistently modified across artifacts.
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from reconcile_catalog import (  # noqa: E402
    candidate_weight,
    load_catalog,
    looks_like_diff,
    reconcile_catalog,
    reconcile_file,
    strip_diff_markers,
)

BASELINE = "def greet():\n    return 'hi'\n"


class StripDiffMarkersTest(unittest.TestCase):
    def test_plain_source_passes_through(self):
        self.assertEqual(strip_diff_markers("a = 1\nb = 2"), "a = 1\nb = 2")

    def test_unified_diff_yields_post_state(self):
        diff = (
            "diff --git a/m.py b/m.py\n"
            "index 1111111..2222222 100644\n"
            "--- a/m.py\n"
            "+++ b/m.py\n"
            "@@ -1,2 +1,2 @@\n"
            " def greet():\n"
            "-    return 'hi'\n"
            "+    return 'hello'\n"
        )
        self.assertEqual(strip_diff_markers(diff), "def greet():\n    return 'hello'")

    def test_headers_and_noise_removed(self):
        self.assertNotIn("@@", strip_diff_markers("@@ -1 +1 @@\n+x = 1\n"))
        self.assertNotIn("No newline", strip_diff_markers("+x\n\\ No newline at end of file\n"))

    def test_non_string_is_fail_soft(self):
        self.assertEqual(strip_diff_markers(None), "")
        self.assertEqual(strip_diff_markers(42), "")
        self.assertEqual(strip_diff_markers(""), "")

    def test_looks_like_diff(self):
        self.assertTrue(looks_like_diff("@@ -1 +1 @@\n+a\n"))
        self.assertFalse(looks_like_diff("x = 1\ny = 2\n"))
        self.assertFalse(looks_like_diff(None))


class CandidateWeightTest(unittest.TestCase):
    def test_patch_outranks_log(self):
        patch = {"kind": "patch", "confidence": 0.1}
        log = {"kind": "log", "confidence": 1.0}
        self.assertGreater(candidate_weight(patch), candidate_weight(log))

    def test_unknown_kind_is_lowest_band(self):
        self.assertLess(
            candidate_weight({"kind": "wat"}), candidate_weight({"kind": "stash"})
        )

    def test_bad_confidence_is_fail_soft(self):
        self.assertIsInstance(candidate_weight({"kind": "patch", "confidence": "x"}), float)
        self.assertIsInstance(candidate_weight("not-a-dict"), float)


class ReconcileFileTest(unittest.TestCase):
    def test_patch_beats_log_on_conflict(self):
        entry = {
            "path": "m.py",
            "candidates": [
                {"artifact": "run.log", "kind": "log", "content": "def greet():\n    return 'WRONG'\n"},
                {
                    "artifact": "fix.patch",
                    "kind": "patch",
                    "content": "@@ -1,2 +1,2 @@\n def greet():\n-    return 'hi'\n+    return 'hello'\n",
                },
            ],
        }
        body = reconcile_file(entry)
        self.assertIn("return 'hello'", body)
        self.assertNotIn("WRONG", body)

    def test_majority_vote_within_same_reliability_band(self):
        agree = "def greet():\n    return 'hello'\n"
        dissent = "def greet():\n    return 'nope'\n"
        entry = {
            "path": "m.py",
            "candidates": [
                {"kind": "log", "content": dissent},
                {"kind": "log", "content": agree},
                {"kind": "log", "content": agree},
            ],
        }
        body = reconcile_file(entry)
        self.assertIn("hello", body)
        self.assertNotIn("nope", body)

    def test_no_usable_candidates_returns_none(self):
        self.assertIsNone(reconcile_file({"path": "m.py", "candidates": []}))
        self.assertIsNone(reconcile_file({"path": "m.py", "candidates": [{"content": "  "}]}))
        self.assertIsNone(reconcile_file("not-a-dict"))

    def test_output_carries_no_diff_markers(self):
        entry = {
            "path": "m.py",
            "candidates": [
                {
                    "kind": "patch",
                    "content": "diff --git a/m.py b/m.py\n@@ -1 +1 @@\n-old\n+new\n",
                }
            ],
        }
        body = reconcile_file(entry)
        for marker in ("diff --git", "@@", "+++", "--- a/"):
            self.assertNotIn(marker, body)

    def test_emitted_lines_are_subset_of_union(self):
        """The acceptance invariant: nothing is invented."""
        candidates = [
            {"kind": "patch", "content": "alpha\nbeta\n"},
            {"kind": "log", "content": "alpha\ngamma\n"},
        ]
        body = reconcile_file({"path": "m.py", "candidates": candidates})
        union = set()
        for candidate in candidates:
            union.update(strip_diff_markers(candidate["content"]).splitlines())
        for line in body.splitlines():
            if line.strip():
                self.assertIn(line, union)

    def test_original_line_not_inconsistently_modified(self):
        """One winning replacement per position — never a blend of two."""
        candidates = [
            {"kind": "log", "content": "keep\nvariant-a\n"},
            {"kind": "log", "content": "keep\nvariant-b\n"},
        ]
        body = reconcile_file({"path": "m.py", "candidates": candidates})
        lines = body.splitlines()
        self.assertEqual(lines[0], "keep")
        self.assertEqual(len([ln for ln in lines if ln.startswith("variant-")]), 1)


class ReconcileCatalogTest(unittest.TestCase):
    def test_writes_files_preserving_relative_paths(self):
        catalog = {
            "files": [
                {
                    "path": "pkg/sub/mod.py",
                    "candidates": [{"kind": "patch", "content": "x = 1\n"}],
                }
            ]
        }
        with tempfile.TemporaryDirectory() as tmp:
            written = reconcile_catalog(catalog, os.path.join(tmp, "reconciled"))
            self.assertIn("pkg/sub/mod.py", written)
            target = Path(tmp) / "reconciled" / "pkg" / "sub" / "mod.py"
            self.assertTrue(target.exists())
            self.assertEqual(target.read_text(), "x = 1\n")

    def test_refuses_unsafe_paths(self):
        catalog = {
            "files": [
                {"path": "../escape.py", "candidates": [{"kind": "patch", "content": "x\n"}]},
                {"path": "/abs.py", "candidates": [{"kind": "patch", "content": "x\n"}]},
            ]
        }
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(reconcile_catalog(catalog, tmp), {})

    def test_empty_catalog_is_fail_soft(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(reconcile_catalog({}, tmp), {})
            self.assertEqual(reconcile_catalog({"files": None}, tmp), {})

    def test_baseline_is_read_when_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            baseline_dir = Path(tmp) / "base"
            baseline_dir.mkdir()
            (baseline_dir / "m.py").write_text(BASELINE)
            catalog = {
                "baseline_root": str(baseline_dir),
                "files": [
                    {
                        "path": "m.py",
                        "candidates": [
                            {"kind": "patch", "content": "def greet():\n    return 'hello'\n"}
                        ],
                    }
                ],
            }
            written = reconcile_catalog(catalog, os.path.join(tmp, "out"))
            self.assertIn("hello", written["m.py"])


class LoadCatalogTest(unittest.TestCase):
    def test_missing_file_is_fail_soft(self):
        self.assertEqual(load_catalog("/nonexistent/catalog.json"), {"files": []})

    def test_malformed_json_is_fail_soft(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
            handle.write("{not json")
            path = handle.name
        try:
            self.assertEqual(load_catalog(path), {"files": []})
        finally:
            os.unlink(path)

    def test_non_object_catalog_is_fail_soft(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
            json.dump([1, 2, 3], handle)
            path = handle.name
        try:
            self.assertEqual(load_catalog(path), {"files": []})
        finally:
            os.unlink(path)

    def test_round_trip(self):
        catalog = {"files": [{"path": "m.py", "candidates": [{"kind": "patch", "content": "x\n"}]}]}
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
            json.dump(catalog, handle)
            path = handle.name
        try:
            self.assertEqual(load_catalog(path)["files"][0]["path"], "m.py")
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
