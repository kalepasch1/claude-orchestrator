#!/usr/bin/env python3
"""`integration_sweeper.py --verify-phantom` — bounded batch verification of phantom merges.

Acceptance (from the backlog item): `python3 runner/integration_sweeper.py
--verify-phantom --project <name> --limit 100` runs a bounded batch and prints which
task ids got MERGED (evidence found) vs requeued (no evidence after 2 attempts).

Before this, the module had no argparse at all: those flags were silently ignored and a
full unbounded sweep ran instead, which is worse than an error because it looks like it
worked.
"""
import os
import sys
import unittest
from unittest.mock import patch

RUNNER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RUNNER)

os.environ.setdefault("SUPABASE_URL", "http://localhost")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test-key")

import integration_sweeper as isw  # noqa: E402

PROJECT = {"id": "p1", "name": "beethoven", "repo_path": "/tmp/repo", "default_base": "master"}


def _task(slug, note="", attempts=None):
    row = {"id": f"id-{slug}", "slug": slug, "project_id": "p1",
           "state": "PHANTOM_UNVERIFIED", "note": note, "kind": "build",
           "base_branch": "master"}
    if attempts is not None:
        row["verify_attempts"] = attempts
    return row


class ParserTest(unittest.TestCase):

    def test_flags_are_parsed_not_ignored(self):
        args = isw._build_parser().parse_args(
            ["--verify-phantom", "--project", "beethoven", "--limit", "100"])
        self.assertTrue(args.verify_phantom)
        self.assertEqual(args.project, "beethoven")
        self.assertEqual(args.limit, 100)

    def test_dry_run_flag(self):
        self.assertTrue(isw._build_parser().parse_args(["--dry-run"]).dry_run)

    def test_defaults_are_a_plain_sweep(self):
        args = isw._build_parser().parse_args([])
        self.assertFalse(args.verify_phantom)
        self.assertIsNone(args.project)
        self.assertIsNone(args.limit)

    def test_unknown_flag_is_an_error_not_a_silent_full_sweep(self):
        with self.assertRaises(SystemExit):
            isw._build_parser().parse_args(["--not-a-flag"])


class VerifyPhantomTest(unittest.TestCase):

    def _run(self, tasks, evidence_for=(), *, dry_run=False, project=None, limit=100,
             isdir=True):
        updates, guarded = [], []

        def fake_select(table, params=None):
            if table == "projects":
                return [PROJECT]
            return list(tasks)

        def fake_evidence(repo, slug):
            if slug in evidence_for:
                return ("c" * 40, "origin/master", f"land {slug}")
            return None

        merge_truth = type("MT", (), {
            "guarded_task_update": staticmethod(
                lambda t, patch_, repo=None: guarded.append((t["slug"], patch_)))})()

        with patch.object(isw.db, "select", side_effect=fake_select), \
             patch.object(isw.db, "update", side_effect=lambda t, w, p: updates.append((w, p))), \
             patch.object(isw, "_integration_evidence", side_effect=fake_evidence), \
             patch.object(isw.os.path, "isdir", return_value=isdir), \
             patch.dict(sys.modules, {"merge_truth": merge_truth}):
            out = isw.verify_phantom(project=project, limit=limit, dry_run=dry_run)
        return out, updates, guarded

    def test_evidence_found_marks_merged_with_the_proving_sha(self):
        out, _, guarded = self._run([_task("alpha")], evidence_for={"alpha"})
        self.assertEqual([m["slug"] for m in out["merged"]], ["alpha"])
        self.assertEqual(len(guarded), 1)
        slug, patch_ = guarded[0]
        self.assertEqual(patch_["state"], "MERGED")
        self.assertEqual(patch_["artifact_commit"], "c" * 40)

    def test_merge_goes_through_merge_truth_not_a_raw_write(self):
        """A MERGED write must stay behind the reachability guard."""
        _, updates, guarded = self._run([_task("alpha")], evidence_for={"alpha"})
        self.assertEqual(len(guarded), 1)
        self.assertEqual([p for _, p in updates if p.get("state") == "MERGED"], [])

    def test_no_evidence_first_pass_only_records_an_attempt(self):
        out, updates, _ = self._run([_task("beta")])
        self.assertEqual([r["slug"] for r in out["still_unproven"]], ["beta"])
        self.assertEqual(out["requeued"], [])
        self.assertIn("verify-attempt 1/2", updates[0][1]["note"])

    def test_no_evidence_after_the_cap_requeues(self):
        out, updates, _ = self._run([_task("beta", attempts=1)])
        self.assertEqual([r["slug"] for r in out["requeued"]], ["beta"])
        self.assertEqual(updates[0][1]["state"], "QUEUED")
        self.assertIsNone(updates[0][1]["artifact_commit"])

    def test_attempt_count_survives_a_missing_column_via_the_note_stamp(self):
        """The cap must work before the verify_attempts migration lands."""
        out, _, _ = self._run([_task("beta", note="[verify-attempt 1/2] no evidence yet")])
        self.assertEqual([r["slug"] for r in out["requeued"]], ["beta"])

    def test_batch_is_bounded_and_mixed_outcomes_are_reported_separately(self):
        tasks = [_task("alpha"), _task("beta", attempts=1), _task("gamma")]
        out, _, _ = self._run(tasks, evidence_for={"alpha"})
        self.assertEqual(out["scanned"], 3)
        self.assertEqual([m["slug"] for m in out["merged"]], ["alpha"])
        self.assertEqual([r["slug"] for r in out["requeued"]], ["beta"])
        self.assertEqual([r["slug"] for r in out["still_unproven"]], ["gamma"])

    def test_limit_is_passed_to_the_query(self):
        seen = {}

        def fake_select(table, params=None):
            if table == "projects":
                return [PROJECT]
            seen.update(params or {})
            return []

        with patch.object(isw.db, "select", side_effect=fake_select):
            isw.verify_phantom(limit=100)
        self.assertEqual(seen.get("limit"), "100")
        self.assertEqual(seen.get("state"), "eq.PHANTOM_UNVERIFIED")

    def test_project_filter_is_applied(self):
        seen = {}

        def fake_select(table, params=None):
            if table == "projects":
                return [PROJECT]
            seen.update(params or {})
            return []

        with patch.object(isw.db, "select", side_effect=fake_select):
            isw.verify_phantom(project="beethoven", limit=10)
        self.assertEqual(seen.get("project_id"), "eq.p1")

    def test_unknown_project_is_an_explicit_error_not_a_full_scan(self):
        with patch.object(isw.db, "select", return_value=[PROJECT]):
            out = isw.verify_phantom(project="nope")
        self.assertIn("unknown project", out["error"])
        self.assertEqual(out["scanned"], 0)

    def test_dry_run_writes_nothing(self):
        tasks = [_task("alpha"), _task("beta", attempts=1)]
        out, updates, guarded = self._run(tasks, evidence_for={"alpha"}, dry_run=True)
        self.assertEqual(updates, [])
        self.assertEqual(guarded, [])
        self.assertEqual([m["slug"] for m in out["merged"]], ["alpha"])
        self.assertEqual([r["slug"] for r in out["requeued"]], ["beta"])

    def test_absent_repo_is_skipped_not_treated_as_missing_evidence(self):
        """The fleet spans two Macs; a repo this machine lacks proves nothing."""
        out, updates, _ = self._run([_task("alpha")], isdir=False)
        self.assertEqual(out["skipped_no_repo"], ["alpha"])
        self.assertEqual(out["requeued"], [])
        self.assertEqual(updates, [])

    def test_never_raises_on_a_db_failure(self):
        with patch.object(isw.db, "select", side_effect=Exception("db down")):
            out = isw.verify_phantom()
        self.assertIn("error", out)
        self.assertEqual(out["scanned"], 0)

    def test_bad_limit_falls_back_instead_of_raising(self):
        with patch.object(isw.db, "select", return_value=[PROJECT]):
            out = isw.verify_phantom(limit="lots")
        self.assertNotIn("Traceback", str(out))


class MainTest(unittest.TestCase):

    def test_main_verify_phantom_does_not_run_the_sweep(self):
        with patch.object(isw, "verify_phantom", return_value={"scanned": 0, "merged": [],
                                                              "requeued": []}) as vp, \
             patch.object(isw, "sweep") as sweep:
            rc = isw.main(["--verify-phantom", "--project", "beethoven", "--limit", "100"])
        self.assertEqual(rc, 0)
        # include_quarantined is new (2026-08-17) and defaults to False, so the DEFAULT CLI
        # invocation must still scan PHANTOM_UNVERIFIED only. Pinned exactly rather than
        # loosened to ANY: this assertion exists to catch the CLI quietly gaining reach over
        # rows nobody asked it to touch, and a loose matcher would stop catching that.
        vp.assert_called_once_with(project="beethoven", limit=100, dry_run=False,
                                   include_quarantined=False)
        sweep.assert_not_called()

    def test_main_passes_include_quarantined_when_the_flag_is_given(self):
        with patch.object(isw, "verify_phantom", return_value={"scanned": 0, "merged": [],
                                                              "requeued": []}) as vp, \
             patch.object(isw, "sweep") as sweep:
            rc = isw.main(["--verify-phantom", "--include-quarantined", "--limit", "10"])
        self.assertEqual(rc, 0)
        self.assertTrue(vp.call_args.kwargs["include_quarantined"])
        sweep.assert_not_called()

    def test_main_without_flags_runs_the_sweep(self):
        with patch.object(isw, "sweep", return_value={}) as sweep:
            self.assertEqual(isw.main([]), 0)
        sweep.assert_called_once()

    def test_main_reports_a_nonzero_exit_on_error(self):
        with patch.object(isw, "verify_phantom", return_value={"error": "boom"}):
            self.assertEqual(isw.main(["--verify-phantom"]), 1)

    def test_main_prints_merged_and_requeued_lines(self):
        result = {"scanned": 2,
                  "merged": [{"slug": "alpha", "sha": "c" * 40, "ref": "origin/master"}],
                  "requeued": [{"slug": "beta", "attempts": 2}]}
        printed = []
        with patch.object(isw, "verify_phantom", return_value=result), \
             patch("builtins.print", side_effect=lambda *a, **k: printed.append(" ".join(map(str, a)))):
            isw.main(["--verify-phantom"])
        joined = "\n".join(printed)
        self.assertIn("MERGED   alpha", joined)
        self.assertIn("REQUEUED beta", joined)

    def test_no_train_flag_is_honoured(self):
        with patch.object(isw, "sweep", return_value={}) as sweep:
            isw.main(["--no-train"])
        self.assertFalse(sweep.call_args.kwargs["run_train"])


if __name__ == "__main__":
    unittest.main()
