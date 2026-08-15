#!/usr/bin/env python3
"""Tests for backlog_audit — the collapsed-task inventory.

The named acceptance is "the JSON array contains entries with keys id, intent_summary and
hashes". The rest pin the detector: a prompt that merely mentions a sha is not collapsed,
a generated stub is, and a failed read never overwrites a previous good audit.
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

import backlog_audit as ba  # noqa: E402


COLLAPSED_PROMPT = """PATCH TEMPLATE 11e3eb1efa96
Intent: 258e15 333b7e269c12 aaac4e acceptance access active adapt adding architecture
Acceptance: preserve existing behavior, make the smallest mergeable diff, run build/tests.
Implementation slots:
1. Locate the existing owner module/function before adding new files.
Prior merged patterns to adapt:
- vigil/cont-258e15 sim=0.366: PATCH TEMPLATE 333b7e269c12
[patch-template:11e3eb1efa96]

SOURCE vigil/cont-aaac4e similarity=0.15: PATCH TEMPLATE c1486760bb7d

# Original improvement request
In the repository, repair any configured base branch mismatch so the active base is master.
"""

REAL_PROMPT = """Integrate the new pricing configuration module into the economic scheduler.
Wire up the config loading into the scheduler's initialization path, ensure existing
behavior is preserved, and verify no existing tests break.
"""

MENTIONS_A_SHA = """Revert the change introduced in 64a7b0ef1234 because it broke the
release train, and add a regression test that pins the previous behaviour.
"""


def row(task_id, prompt, slug=None, state="QUEUED"):
    return {"id": task_id, "slug": slug or task_id, "kind": "build", "state": state,
            "prompt": prompt, "project_id": "p1", "attempt": 0,
            "created_at": "2026-08-01T00:00:00Z"}


class FakeDB:
    """Honours limit/offset and caps each response like PostgREST does."""

    def __init__(self, rows, fail=False):
        self.rows = rows
        self.fail = fail

    def select(self, table, params=None):
        if self.fail:
            raise RuntimeError("tasks unreadable")
        params = params or {}
        rows = list(self.rows)
        for key, raw in params.items():
            if key in ("select", "order", "limit", "offset"):
                continue
            value = str(raw)
            if value.startswith("eq."):
                rows = [r for r in rows if str(r.get(key)) == value[3:]]
        offset = int(params.get("offset", 0) or 0)
        limit = min(int(params.get("limit", 1000) or 1000), 1000)
        return rows[offset:offset + limit]


class DetectorTests(unittest.TestCase):
    def test_a_generated_stub_is_collapsed(self):
        self.assertTrue(ba.is_collapsed(COLLAPSED_PROMPT))

    def test_an_ordinary_prompt_is_not_collapsed(self):
        self.assertFalse(ba.is_collapsed(REAL_PROMPT))

    def test_merely_mentioning_a_sha_is_not_collapse(self):
        """The distinction the ratio exists for: a sha in prose is not a hex bag."""
        self.assertFalse(ba.is_collapsed(MENTIONS_A_SHA))

    def test_a_hex_bag_intent_line_is_collapsed_without_the_header(self):
        self.assertTrue(ba.is_collapsed(
            "Intent: 258e15 333b7e269c12 aaac4e c1486760bb7d adapt after before"))

    def test_empty_and_garbage_are_not_collapsed_and_do_not_raise(self):
        for bad in (None, "", "   ", 7, []):
            self.assertFalse(ba.is_collapsed(bad))

    def test_hex_ratio_never_raises(self):
        for bad in (None, "", 7, [], {}):
            self.assertIsInstance(ba.hex_ratio(bad), float)


class ExtractionTests(unittest.TestCase):
    def test_template_and_tag_hashes_are_collected_first(self):
        hashes = ba.extract_hashes(COLLAPSED_PROMPT)
        self.assertEqual(hashes[0], "11e3eb1efa96")
        self.assertIn("333b7e269c12", hashes)
        self.assertIn("c1486760bb7d", hashes)

    def test_hashes_are_deduplicated(self):
        hashes = ba.extract_hashes(COLLAPSED_PROMPT)
        self.assertEqual(len(hashes), len(set(hashes)))

    def test_transplant_sources_are_captured_with_their_scores(self):
        sources = ba.extract_sources(COLLAPSED_PROMPT)
        names = {s["source"] for s in sources}
        self.assertIn("vigil/cont-258e15", names)
        self.assertIn("vigil/cont-aaac4e", names)
        self.assertTrue(all(0.0 <= s["similarity"] <= 1.0 for s in sources))

    def test_intent_summary_recovers_the_english_the_generator_left(self):
        summary = ba.intent_summary(COLLAPSED_PROMPT)
        self.assertIn("base branch mismatch", summary)
        self.assertNotIn("PATCH TEMPLATE", summary)

    def test_intent_summary_falls_back_to_the_hex_bag_rather_than_nothing(self):
        """Even a bag of tokens beats an empty string as a reconstruction seed."""
        summary = ba.intent_summary("PATCH TEMPLATE abc123\nIntent: 258e15 333b7e269c12 aaac4e\n")
        self.assertTrue(summary)

    def test_intent_summary_strips_boilerplate(self):
        summary = ba.intent_summary(COLLAPSED_PROMPT)
        self.assertNotIn("preserve existing behavior", summary)

    def test_intent_summary_is_capped(self):
        long_line = "word " * 500
        self.assertLessEqual(len(ba.intent_summary(f"# Original improvement request\n{long_line}")), 280)


class AuditTests(unittest.TestCase):
    def _db(self):
        return FakeDB([
            row("t1", COLLAPSED_PROMPT),
            row("t2", REAL_PROMPT),
            row("t3", COLLAPSED_PROMPT),
            row("t4", MENTIONS_A_SHA),
            row("t5", COLLAPSED_PROMPT, state="DONE"),
        ])

    def test_only_collapsed_queued_tasks_are_listed(self):
        result = ba.audit(self._db().select)
        self.assertEqual(result["collapsed"], 2)
        self.assertEqual({e["id"] for e in result["entries"]}, {"t1", "t3"})

    def test_every_entry_has_the_three_required_keys(self):
        for entry in ba.audit(self._db().select)["entries"]:
            for key in ("id", "intent_summary", "hashes"):
                self.assertIn(key, entry)
            self.assertTrue(entry["id"])
            self.assertTrue(entry["intent_summary"])
            self.assertTrue(entry["hashes"])

    def test_limit_is_honoured(self):
        self.assertEqual(ba.audit(self._db().select, limit=1)["collapsed"], 1)

    def test_an_unreadable_table_is_not_ok_and_lists_nothing(self):
        result = ba.audit(FakeDB([], fail=True).select)
        self.assertFalse(result["ok"])
        self.assertEqual(result["entries"], [])

    def test_paging_reads_past_the_implicit_cap(self):
        rows = [row(f"t{i}", COLLAPSED_PROMPT) for i in range(1500)]
        self.assertEqual(ba.audit(FakeDB(rows).select)["scanned"], 1500)


class WriteTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = os.path.join(self._tmp.name, "backlog_audit.json")

    def test_the_file_is_a_json_array_of_entries(self):
        result = ba.audit(FakeDB([row("t1", COLLAPSED_PROMPT)]).select)
        ok, path = ba.write_audit(result, self.path)
        self.assertTrue(ok, path)
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 1)
        for key in ("id", "intent_summary", "hashes"):
            self.assertIn(key, data[0])

    def test_a_failed_read_never_overwrites_a_previous_audit(self):
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write('[{"id": "previous"}]')
        ok, reason = ba.write_audit(ba.audit(FakeDB([], fail=True).select), self.path)
        self.assertFalse(ok)
        self.assertIn("refusing to overwrite", reason)
        with open(self.path, encoding="utf-8") as handle:
            self.assertEqual(json.load(handle)[0]["id"], "previous")


if __name__ == "__main__":
    unittest.main()
