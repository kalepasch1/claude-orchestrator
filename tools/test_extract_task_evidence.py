#!/usr/bin/env python3
"""Tests for tools/extract_task_evidence.py.

The failure this file exists to prevent: a snapshot that is silently truncated
still parses as "some evidence", and a run that classifies a truncated snapshot
reports zero UNKNOWN items while having never seen the dropped ones.
"""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from extract_task_evidence import (  # noqa: E402
    ExtractionError,
    count_items,
    extract_snapshot,
    find_fingerprint,
    scan_json_array,
)


class TestFingerprint(unittest.TestCase):
    def test_backticked_fingerprint(self):
        p = "use audit fingerprint `7bd5c9d0be16ae945cdbcef3093f941270885f0a` here"
        self.assertEqual(find_fingerprint(p), "7bd5c9d0be16ae945cdbcef3093f941270885f0a")

    def test_bare_fingerprint(self):
        self.assertEqual(find_fingerprint("audit fingerprint abcdef0123456789"),
                         "abcdef0123456789")

    def test_absent_fingerprint_is_none(self):
        self.assertIsNone(find_fingerprint("no marker at all"))


class TestScanJsonArray(unittest.TestCase):
    def test_bracket_inside_string_does_not_terminate(self):
        raw = '[{"subject": "fix: handle ] and [ in parser"}] trailing prose'
        self.assertEqual(scan_json_array(raw, 0),
                         '[{"subject": "fix: handle ] and [ in parser"}]')

    def test_escaped_quote_inside_string(self):
        raw = r'[{"subject": "say \"hi\" ]"}] after'
        self.assertEqual(json.loads(scan_json_array(raw, 0))[0]["subject"], 'say "hi" ]')

    def test_nested_arrays(self):
        raw = '[[1,2],[3,[4,5]]] tail'
        self.assertEqual(json.loads(scan_json_array(raw, 0)), [[1, 2], [3, [4, 5]]])

    def test_unterminated_array_raises(self):
        with self.assertRaises(ExtractionError):
            scan_json_array('[{"a": 1}', 0)


class TestExtractSnapshot(unittest.TestCase):
    def _prompt(self, body):
        return f"preamble\n\nEvidence snapshot (digest plus sample):\n{body}\n\nProof: done\n"

    def test_extracts_and_stops_before_prose(self):
        snap = extract_snapshot(self._prompt('[{"ref": "refs/x", "sha": "aa"}]'))
        self.assertEqual(len(snap), 1)
        self.assertEqual(snap[0]["ref"], "refs/x")

    def test_trailing_prose_with_brackets_is_not_swallowed(self):
        snap = extract_snapshot(self._prompt('[{"ref": "a"}]') + "\nsee [docs] for more]")
        self.assertEqual(snap, [{"ref": "a"}])

    def test_missing_marker_raises(self):
        with self.assertRaises(ExtractionError):
            extract_snapshot("no snapshot here")

    def test_marker_without_array_raises(self):
        with self.assertRaises(ExtractionError):
            extract_snapshot("Evidence snapshot: none recorded")

    def test_truncated_array_raises_not_returns_partial(self):
        with self.assertRaises(ExtractionError):
            extract_snapshot("Evidence snapshot:\n[{\"ref\": \"a\"},")

    def test_invalid_json_raises(self):
        with self.assertRaises(ExtractionError):
            extract_snapshot("Evidence snapshot:\n[{ref: 'a'}]")

    def test_empty_snapshot_is_allowed(self):
        self.assertEqual(extract_snapshot("Evidence snapshot:\n[]"), [])


class TestCountItems(unittest.TestCase):
    def test_digest_count_beats_sample_length(self):
        snap = [{"count": 550, "items_sample": [{"ref": "a"}, {"ref": "b"}]}]
        self.assertEqual(count_items(snap), 550)

    def test_plain_entries_count_as_one(self):
        self.assertEqual(count_items([{"path": "/a"}, {"path": "/b"}]), 2)

    def test_mixed(self):
        self.assertEqual(count_items([{"count": 10}, {"path": "/a"}]), 11)


if __name__ == "__main__":
    unittest.main()
