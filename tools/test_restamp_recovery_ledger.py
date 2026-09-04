#!/usr/bin/env python3
"""Tests for tools/restamp_recovery_ledger.py."""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import restamp_recovery_ledger as R  # noqa: E402


def ledger(items=None, repo="/repo", base_sha="a" * 40, fingerprint="old"):
    return {
        "meta": {"project": "beethoven", "repo": repo, "base": "origin/master",
                 "baseSha": base_sha, "fingerprint": fingerprint,
                 "generatedAt": "2026-01-01T00:00:00.000Z",
                 "jsonName": "old.json"},
        "counts": {"BOGUS_STALE_COUNT": 999},
        "items": items if items is not None else [
            {"kind": "rescue_ref", "source": "refs/orch-rescue/x",
             "classification": "RECOVERABLE_VALUE", "reason": "absent"},
            {"kind": "rescue_ref", "source": "refs/orch-rescue/y",
             "classification": "ALREADY_PRESENT", "reason": "identical"},
        ],
    }


class TestRecount(unittest.TestCase):
    def test_counts_recomputed_not_copied(self):
        out = R.restamp(ledger(), "newfp")
        self.assertEqual(out["counts"],
                         {"RECOVERABLE_VALUE": 1, "ALREADY_PRESENT": 1})
        self.assertNotIn("BOGUS_STALE_COUNT", out["counts"])

    def test_unrecognised_label_becomes_unknown(self):
        out = R.restamp(ledger([{"classification": "WAT"}]), "newfp")
        self.assertEqual(out["counts"], {"UNKNOWN": 1})
        self.assertEqual(R.unknown_count([{"classification": "WAT"}]), 1)

    def test_missing_classification_becomes_unknown(self):
        self.assertEqual(R.unknown_count([{"kind": "x"}]), 1)

    def test_non_dict_item_becomes_unknown(self):
        self.assertEqual(R.unknown_count(["junk", None]), 2)

    def test_empty_and_none_items(self):
        self.assertEqual(R.recount([]), {})
        self.assertEqual(R.recount(None), {})
        self.assertEqual(R.unknown_count(None), 0)

    def test_all_known_classifications_pass_through(self):
        items = [{"classification": c} for c in sorted(R.KNOWN_CLASSIFICATIONS)]
        self.assertEqual(R.unknown_count(items), 0)


class TestRestamp(unittest.TestCase):
    def test_fingerprint_replaced_and_provenance_recorded(self):
        out = R.restamp(ledger(fingerprint="oldfp"), "newfp",
                        json_name="n.json", source_path="/tmp/src.json")
        self.assertEqual(out["meta"]["fingerprint"], "newfp")
        self.assertEqual(out["meta"]["restampedFrom"], "oldfp")
        self.assertEqual(out["meta"]["restampedFromLedger"], "src.json")
        self.assertEqual(out["meta"]["jsonName"], "n.json")
        self.assertTrue(out["meta"]["restampedAt"].endswith("Z"))

    def test_source_ledger_not_mutated(self):
        src = ledger(fingerprint="oldfp")
        R.restamp(src, "newfp")
        self.assertEqual(src["meta"]["fingerprint"], "oldfp")
        self.assertEqual(src["counts"], {"BOGUS_STALE_COUNT": 999})

    def test_items_preserved_verbatim(self):
        src = ledger()
        out = R.restamp(src, "newfp")
        self.assertEqual(out["items"], src["items"])

    def test_missing_meta_is_tolerated(self):
        out = R.restamp({"items": [{"classification": "ALREADY_PRESENT"}]}, "fp")
        self.assertEqual(out["meta"]["fingerprint"], "fp")
        self.assertEqual(out["meta"]["restampedFrom"], "")

    def test_non_dict_input_returns_stamped_shell(self):
        out = R.restamp("not a ledger", "fp")
        self.assertEqual(out["meta"]["fingerprint"], "fp")
        self.assertEqual(out["counts"], {})


class TestDriftGuard(unittest.TestCase):
    def test_no_expectations_means_no_drift(self):
        self.assertEqual(R.check_drift(ledger()["meta"], "", ""), "")

    def test_repo_mismatch_detected(self):
        r = R.check_drift(ledger(repo="/a")["meta"], "/b", "")
        self.assertIn("repo mismatch", r)

    def test_repo_match_via_realpath(self):
        self.assertEqual(R.check_drift(ledger(repo="/tmp")["meta"], "/tmp", ""), "")

    def test_base_sha_mismatch_detected(self):
        r = R.check_drift(ledger(base_sha="a" * 40)["meta"], "", "b" * 40)
        self.assertIn("base drift", r)

    def test_abbreviated_base_sha_accepted(self):
        self.assertEqual(
            R.check_drift(ledger(base_sha="abcdef1234567890")["meta"], "", "abcdef1"), "")

    def test_missing_base_sha_is_refused(self):
        m = ledger()["meta"]
        del m["baseSha"]
        self.assertIn("no baseSha", R.check_drift(m, "", "abcdef1"))

    def test_non_dict_meta_refused(self):
        self.assertIn("no meta", R.check_drift(None, "", ""))


class TestLoadLedger(unittest.TestCase):
    def test_missing_file_returns_empty(self):
        self.assertEqual(R.load_ledger("/nonexistent/nope.json"), {})

    def test_malformed_json_returns_empty(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            fh.write("{not json")
            p = fh.name
        try:
            self.assertEqual(R.load_ledger(p), {})
        finally:
            os.unlink(p)

    def test_json_list_returns_empty(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            fh.write("[1,2]")
            p = fh.name
        try:
            self.assertEqual(R.load_ledger(p), {})
        finally:
            os.unlink(p)


def flat_ledger(items=None, fingerprint="oldfp", base_sha="a" * 40):
    """`reconcile_all_evidence.py`'s native output shape."""
    items = items if items is not None else [
        {"kind": "orchestrator_rescue_refs", "classification": "RECOVERABLE_VALUE"},
        {"kind": "dirty_worktree", "classification": "ALREADY_PRESENT"},
    ]
    return {"audit_fingerprint": fingerprint, "base": "origin/master",
            "base_sha": base_sha, "evidence_kind": "combined",
            "counts": {"STALE": 99}, "total": 0, "unknown": 7,
            "stages": {"reconcile_rescue_refs.py": "ok"}, "items": items}


class TestFlatShape(unittest.TestCase):
    def test_flat_shape_detected(self):
        self.assertTrue(R.is_flat(flat_ledger()))
        self.assertFalse(R.is_flat(ledger()))
        self.assertFalse(R.is_flat("junk"))

    def test_read_fingerprint_both_shapes(self):
        self.assertEqual(R.read_fingerprint(flat_ledger(fingerprint="f1")), "f1")
        self.assertEqual(R.read_fingerprint(ledger(fingerprint="f2")), "f2")
        self.assertEqual(R.read_fingerprint("junk"), "")

    def test_read_base_sha_both_shapes(self):
        self.assertEqual(R.read_base_sha(flat_ledger(base_sha="bb")), "bb")
        self.assertEqual(R.read_base_sha(ledger(base_sha="cc")), "cc")

    def test_flat_restamp_updates_top_level_fields(self):
        out = R.restamp(flat_ledger(fingerprint="oldfp"), "newfp",
                        source_path="/tmp/src.json")
        self.assertEqual(out["audit_fingerprint"], "newfp")
        self.assertEqual(out["restamped_from"], "oldfp")
        self.assertEqual(out["restamped_from_ledger"], "src.json")
        self.assertNotIn("meta", out)

    def test_flat_restamp_recomputes_total_and_unknown(self):
        out = R.restamp(flat_ledger(), "newfp")
        self.assertEqual(out["total"], 2)
        self.assertEqual(out["unknown"], 0)   # source claimed 7
        self.assertEqual(out["counts"],
                         {"RECOVERABLE_VALUE": 1, "ALREADY_PRESENT": 1})

    def test_flat_restamp_surfaces_unknown(self):
        out = R.restamp(flat_ledger(items=[{"classification": "WAT"}]), "fp")
        self.assertEqual(out["unknown"], 1)

    def test_flat_stages_preserved(self):
        out = R.restamp(flat_ledger(), "fp")
        self.assertEqual(out["stages"], {"reconcile_rescue_refs.py": "ok"})

    def test_flat_cli_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "src.json")
            with open(src, "w") as fh:
                json.dump(flat_ledger(), fh)
            out = os.path.join(d, "out.json")
            rc = R.main(["--in", src, "--out", out, "--fingerprint", "newfp",
                         "--expect-base-sha", "a" * 40])
            self.assertEqual(rc, 0)
            got = json.load(open(out))
            self.assertEqual(got["audit_fingerprint"], "newfp")
            self.assertEqual(got["unknown"], 0)

    def test_flat_project_and_repo_stamped(self):
        out = R.restamp(flat_ledger(), "fp", project="beethoven", repo="/r")
        self.assertEqual(out["project"], "beethoven")
        self.assertEqual(out["repo"], "/r")

    def test_meta_project_and_repo_stamped(self):
        out = R.restamp(ledger(), "fp", project="beethoven", repo="/r")
        self.assertEqual(out["meta"]["project"], "beethoven")
        self.assertEqual(out["meta"]["repo"], "/r")

    def test_project_omitted_leaves_shape_untouched(self):
        self.assertNotIn("project", R.restamp(flat_ledger(), "fp"))

    def test_flat_cli_base_drift_refused(self):
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "src.json")
            with open(src, "w") as fh:
                json.dump(flat_ledger(base_sha="a" * 40), fh)
            rc = R.main(["--in", src, "--out", os.path.join(d, "o.json"),
                         "--fingerprint", "f", "--expect-base-sha", "b" * 40])
            self.assertEqual(rc, 2)

    def test_flat_drift_override_recorded_without_keyerror(self):
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "src.json")
            with open(src, "w") as fh:
                json.dump(flat_ledger(base_sha="a" * 40), fh)
            out = os.path.join(d, "o.json")
            rc = R.main(["--in", src, "--out", out, "--fingerprint", "f",
                         "--expect-base-sha", "b" * 40, "--allow-base-drift"])
            self.assertEqual(rc, 0)
            self.assertIn("base drift",
                          json.load(open(out))["restamp_drift_override"])


class TestCli(unittest.TestCase):
    def _write(self, d, data):
        p = os.path.join(d, "src.json")
        with open(p, "w") as fh:
            json.dump(data, fh)
        return p

    def test_happy_path_writes_restamped_ledger(self):
        with tempfile.TemporaryDirectory() as d:
            src = self._write(d, ledger())
            out = os.path.join(d, "sub", "out.json")
            rc = R.main(["--in", src, "--out", out, "--fingerprint", "newfp"])
            self.assertEqual(rc, 0)
            got = json.load(open(out))
            self.assertEqual(got["meta"]["fingerprint"], "newfp")
            self.assertEqual(got["counts"],
                             {"ALREADY_PRESENT": 1, "RECOVERABLE_VALUE": 1})
            self.assertEqual(got["meta"]["jsonName"], "out.json")

    def test_base_drift_refused_without_override(self):
        with tempfile.TemporaryDirectory() as d:
            src = self._write(d, ledger(base_sha="a" * 40))
            out = os.path.join(d, "out.json")
            rc = R.main(["--in", src, "--out", out, "--fingerprint", "f",
                         "--expect-base-sha", "b" * 40])
            self.assertEqual(rc, 2)
            self.assertFalse(os.path.exists(out))

    def test_base_drift_allowed_records_override(self):
        with tempfile.TemporaryDirectory() as d:
            src = self._write(d, ledger(base_sha="a" * 40))
            out = os.path.join(d, "out.json")
            rc = R.main(["--in", src, "--out", out, "--fingerprint", "f",
                         "--expect-base-sha", "b" * 40, "--allow-base-drift"])
            self.assertEqual(rc, 0)
            self.assertIn("base drift",
                          json.load(open(out))["meta"]["restampDriftOverride"])

    def test_unreadable_source_refused(self):
        with tempfile.TemporaryDirectory() as d:
            rc = R.main(["--in", os.path.join(d, "nope.json"),
                         "--out", os.path.join(d, "o.json"), "--fingerprint", "f"])
            self.assertEqual(rc, 2)

    def test_ledger_without_items_list_refused(self):
        with tempfile.TemporaryDirectory() as d:
            src = self._write(d, {"meta": {}, "counts": {}})
            rc = R.main(["--in", src, "--out", os.path.join(d, "o.json"),
                         "--fingerprint", "f"])
            self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
