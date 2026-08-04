#!/usr/bin/env python3
"""test_improvement_loop.py — regression tests for the rebuilt self-improvement loop.

Each test pins one autopsy finding so it cannot silently return:

  B. ship gate rejects a zero-diff "ship"        -> test_ship_gate_*
  D. rollback actually reverts                    -> test_rollback_*
  E. liveness alarms on a degenerate gate         -> test_liveness_*
  F. scoring refuses instead of fabricating       -> test_score_refuses_*
  G. semantic dedupe beats title-equality         -> test_dedupe_*
  A/C. baseline -> target -> evaluate -> act      -> test_end_to_end_*

Runs entirely on a throwaway git repo and an in-memory fake DB: no network, no
Supabase writes, no side effects on the real fleet.
"""
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def git(repo, *a):
    return subprocess.run(["git", *a], cwd=repo, capture_output=True, encoding="utf-8")


def make_repo():
    d = tempfile.mkdtemp(prefix="improveloop-")
    git(d, "init", "-q", "-b", "master")
    git(d, "config", "user.email", "t@example.com")
    git(d, "config", "user.name", "t")
    open(os.path.join(d, "a.txt"), "w").write("one\n")
    git(d, "add", "-A"); git(d, "commit", "-q", "-m", "root")
    return d


class FakeDB:
    """Minimal stand-in for db.select/insert/update over PostgREST-ish params."""

    def __init__(self, tables=None):
        self.tables = tables or {}
        self.updates = []

    def select(self, table, params=None):
        rows = list(self.tables.get(table, []))
        for k, v in (params or {}).items():
            if k in ("select", "limit", "order"):
                continue
            if isinstance(v, str) and v.startswith("eq."):
                rows = [r for r in rows if str(r.get(k)) == v[3:]]
        return rows

    def insert(self, table, row, upsert=False):
        self.tables.setdefault(table, []).append(dict(row))
        return row

    def update(self, table, match, patch):
        self.updates.append((table, match, patch))
        for r in self.tables.get(table, []):
            if all(str(r.get(k)) == str(v) for k, v in match.items()):
                r.update(patch)
        return patch

    def rpc(self, fn, args):
        return None


# --------------------------------------------------------------------------- B
class TestShipGate(unittest.TestCase):
    def setUp(self):
        self.repo = make_repo()

    def test_ship_gate_rejects_empty_commit(self):
        """A commit that names the slug but changes NOTHING is not a ship."""
        import improvement_verify
        slug = "improve-terminal-yield-pct-do-a-thing-abc12345"
        git(self.repo, "commit", "-q", "--allow-empty", "-m", f"agent: {slug}")
        sha = git(self.repo, "rev-parse", "HEAD").stdout.strip()
        self.assertFalse(improvement_verify.diff_is_nonempty(self.repo, sha),
                         "zero-diff commit must not count as a diff")
        import landed_evidence
        self.assertIsNone(landed_evidence.find_evidence(self.repo, slug, refs=["master"]),
                          "evidence finder must reject a tree-identical commit")

    def test_ship_gate_accepts_real_diff(self):
        import improvement_verify, landed_evidence
        slug = "improve-terminal-yield-pct-do-a-thing-abc12345"
        open(os.path.join(self.repo, "b.txt"), "w").write("real change\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", f"agent: {slug}")
        ev = landed_evidence.find_evidence(self.repo, slug, refs=["master"])
        self.assertIsNotNone(ev, "a tree-changing commit naming the slug IS evidence")
        self.assertTrue(improvement_verify.diff_is_nonempty(self.repo, ev[0]))
        self.assertTrue(improvement_verify.sha_reachable_from(self.repo, ev[0], "master"))

    def test_ship_gate_rejects_unreachable_sha(self):
        """Evidence must be reachable from the release ref, not merely present."""
        import improvement_verify
        slug = "improve-x-unreachable-deadbeef"
        git(self.repo, "checkout", "-q", "-b", "side")
        open(os.path.join(self.repo, "c.txt"), "w").write("side\n")
        git(self.repo, "add", "-A"); git(self.repo, "commit", "-q", "-m", f"agent: {slug}")
        side = git(self.repo, "rev-parse", "HEAD").stdout.strip()
        git(self.repo, "checkout", "-q", "master")
        self.assertFalse(improvement_verify.sha_reachable_from(self.repo, side, "master"))


# --------------------------------------------------------------------------- D
class TestRollback(unittest.TestCase):
    def setUp(self):
        self.repo = make_repo()

    def test_rollback_actually_reverts_the_content(self):
        import improvement_verify
        p = os.path.join(self.repo, "a.txt")
        open(p, "w").write("one\ntwo-REGRESSION\n")
        git(self.repo, "add", "-A"); git(self.repo, "commit", "-q", "-m", "bad change")
        bad = git(self.repo, "rev-parse", "HEAD").stdout.strip()
        self.assertIn("REGRESSION", open(p).read())
        out = improvement_verify.revert_commit(self.repo, bad, dry_run=True)
        self.assertTrue(out["ok"], out)
        self.assertTrue(out["revert_sha"], "a revert commit must exist")
        # The revert commit's tree must restore the pre-change content.
        show = git(self.repo, "show", f"{out['revert_sha']}:a.txt").stdout
        self.assertEqual(show, "one\n", "revert must restore the original content")
        self.assertNotIn("REGRESSION", show)

    def test_rollback_refuses_unknown_sha(self):
        import improvement_verify
        out = improvement_verify.revert_commit(self.repo, "0" * 40, dry_run=True)
        self.assertFalse(out["ok"])


# --------------------------------------------------------------------------- E
class TestLiveness(unittest.TestCase):
    def _with_hist(self, hist):
        import gate_liveness
        rows = []
        for verdict, n in hist.items():
            rows += [{"gate": "build_gate", "verdict": verdict}] * n
        gate_liveness.db = FakeDB({"orch_gate_verdicts": rows, "orch_gate_alarms": []})
        return gate_liveness

    def test_liveness_alarms_on_degenerate_gate(self):
        """The 18-day outage: 200 inputs, 200 'false'. Must alarm."""
        gl = self._with_hist({"false": 200})
        a = gl.assess("build_gate")
        self.assertEqual(a["alarm"], "degenerate")
        self.assertEqual(a["share"], 1.0)
        self.assertIsNotNone(gl.raise_or_resolve(a), "an alarm row must be opened")

    def test_liveness_quiet_on_healthy_mix(self):
        gl = self._with_hist({"true": 120, "false": 80})
        self.assertIsNone(gl.assess("build_gate")["alarm"])

    def test_liveness_ignores_small_samples(self):
        """3 identical verdicts is not evidence of breakage."""
        gl = self._with_hist({"false": 3})
        self.assertIsNone(gl.assess("build_gate")["alarm"])

    def test_liveness_alarms_on_silent_always_on_gate(self):
        import gate_liveness
        gate_liveness.db = FakeDB({"orch_gate_verdicts": [], "orch_gate_alarms": []})
        self.assertEqual(gate_liveness.assess("preflight")["alarm"], "silent")
        self.assertIsNone(gate_liveness.assess("some_optional_gate")["alarm"])


# --------------------------------------------------------------------------- F
class TestHonestScoring(unittest.TestCase):
    def test_score_refuses_when_returns_table_is_empty(self):
        """The whole point: no realized history -> refuse, don't multiply by 1.0."""
        import improvement_ledger
        improvement_ledger.db = FakeDB({"improvement_calibration": []})
        s = improvement_ledger.score({"surface": "reliability", "metric_name": "m",
                                      "headroom_multiplier": 19.3})
        self.assertIsNone(s["score"])
        self.assertEqual(s["basis"], "refused")
        self.assertIn("REFUSING", s["reason"])

    def test_score_uses_realized_deltas_when_available(self):
        import improvement_ledger
        improvement_ledger.db = FakeDB({"improvement_calibration": [
            {"surface": "reliability", "metric_name": "m", "realized_multiplier": 2.0},
            {"surface": "reliability", "metric_name": "m", "realized_multiplier": 4.0},
            {"surface": "reliability", "metric_name": "m", "realized_multiplier": 3.0},
        ]})
        s = improvement_ledger.score({"surface": "reliability", "metric_name": "m",
                                      "headroom_multiplier": 2.0})
        self.assertEqual(s["basis"], "realized_delta")
        self.assertAlmostEqual(s["score"], 6.0, places=3)   # mean 3.0 x headroom 2.0

    def test_rank_falls_back_to_measured_headroom(self):
        import improvement_ledger
        improvement_ledger.db = FakeDB({"improvement_calibration": []})
        out = improvement_ledger.rank([
            {"surface": "a", "metric_name": "m", "headroom_multiplier": 2.2},
            {"surface": "b", "metric_name": "m", "headroom_multiplier": 143.7},
        ])
        self.assertEqual(out[0]["headroom_multiplier"], 143.7)
        self.assertTrue(all(c["score_basis"] == "refused" for c in out))

    def test_predicted_multiplier_cannot_exceed_measured_headroom(self):
        """'100x' is not sayable when the arithmetic only supports 8.79x."""
        import improvement_ledger
        improvement_ledger.db = FakeDB({"improvement_calibration": []})
        b = {"bottleneck_key": "merge_to_deploy_pct", "surface": "orchestration-layer",
             "metric_name": "pct", "metric_collector": "c", "metric_query": "select 1",
             "value": 10.24, "ideal_value": 90.0, "comparator": "gt",
             "headroom_multiplier": 8.79, "sample_n": 166, "detail": "d"}
        row = improvement_ledger.build_proposal(b, "app", predicted_multiplier=100.0)
        self.assertEqual(row["predicted_multiplier"], 8.79)
        self.assertEqual(row["expected_multiplier"], "8.79x")


# --------------------------------------------------------------------------- G
class TestDedupe(unittest.TestCase):
    def test_dedupe_catches_reworded_restatement(self):
        import improvement_ledger
        hist = [{"title": "Reduce phantom merged tasks by requiring commit evidence",
                 "proposal": "require a commit sha before marking merged",
                 "metric_name": "pct_shipped_tasks_with_no_artifact_commit",
                 "status": "regressed"}]
        improvement_ledger.db = FakeDB({"improvement_proposals": hist})
        cand = {"app": "x", "surface": "reliability",
                "title": "Require commit evidence to reduce phantom merged tasks",
                "proposal": "a commit sha must be required before a task is marked merged",
                "metric_name": "pct_shipped_tasks_with_no_artifact_commit"}
        out = improvement_ledger.is_duplicate(cand, history=hist)
        self.assertTrue(out["duplicate"])
        self.assertEqual(out["status"], "regressed",
                         "must specifically block re-trying something that regressed")

    def test_dedupe_allows_a_genuinely_different_idea(self):
        import improvement_ledger
        hist = [{"title": "Reduce phantom merged tasks by requiring commit evidence",
                 "proposal": "require a commit sha", "metric_name": "phantom",
                 "status": "shipped"}]
        improvement_ledger.db = FakeDB({"improvement_proposals": hist})
        cand = {"app": "x", "surface": "performance",
                "title": "Cut median cycle time by parallelising worktree checkout",
                "proposal": "checkout worktrees concurrently and cache node_modules",
                "metric_name": "median_hours_task_created_to_merged"}
        self.assertFalse(improvement_ledger.is_duplicate(cand, history=hist)["duplicate"])

    def test_slugs_do_not_collide_on_a_shared_prefix(self):
        """The 40-char truncation collided 40.6% of the time. These must not."""
        import improvement_ledger
        improvement_ledger.db = FakeDB({"improvement_proposals": []})
        a = improvement_ledger.make_slug(
            "Attribute train and deploy outcomes back to coder routing weights", "k", set())
        b = improvement_ledger.make_slug(
            "Attribute train and deploy outcomes back to coder routing policy", "k", set())
        self.assertNotEqual(a, b)
        self.assertGreater(len(a), 48, "slug must not be truncated to the old 48 chars")


# ------------------------------------------------------------------------- A/C
class TestEndToEnd(unittest.TestCase):
    """baseline -> target -> window closes -> validated  OR  regressed + revert."""

    def setUp(self):
        self.repo = make_repo()
        p = os.path.join(self.repo, "a.txt")
        open(p, "w").write("one\ntwo\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "agent: improve-phantom-rate-pct-fix-xyz")
        self.sha = git(self.repo, "rev-parse", "HEAD").stdout.strip()
        self.past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()

    def _proposal(self):
        return {"id": "p1", "app": "x", "surface": "reliability", "task_slug": "s1",
                "metric_name": "phantom_rate_pct", "metric_collector": "phantom_rate_pct",
                "metric_query": "select 1", "baseline_value": 7.58, "target_value": 1.0,
                "comparator": "lt", "required_margin": 2.0, "predicted_multiplier": 7.58,
                "status": "shipped", "evaluate_after": self.past,
                "artifact_commit": self.sha, "artifact_repo": self.repo}

    def test_window_still_open_defers(self):
        import improvement_verify
        improvement_verify.db = FakeDB()
        p = dict(self._proposal(),
                 evaluate_after=(datetime.now(timezone.utc) + timedelta(hours=5)).isoformat())
        self.assertEqual(improvement_verify.evaluate(p, injected=1.0)["verdict"], "pending")

    def test_pass_path_marks_validated_and_does_not_revert(self):
        import improvement_verify
        fake = FakeDB({"improvement_proposals": [self._proposal()]})
        improvement_verify.db = fake
        import gate_liveness; gate_liveness.db = fake
        # metric fell 7.58 -> 1.20 == 6.3x, comfortably past the 2.0x margin
        out = improvement_verify.settle(self._proposal(), injected=1.20, dry_run=True)
        self.assertEqual(out["verdict"], "validated")
        self.assertAlmostEqual(out["multiplier"], 6.3167, places=3)
        self.assertFalse(out["rolled_back"])
        self.assertIn("one\ntwo\n", open(os.path.join(self.repo, "a.txt")).read())
        cal = fake.tables.get("improvement_calibration", [])
        self.assertEqual(cal[0]["outcome"], "validated")
        self.assertEqual(cal[0]["predicted_multiplier"], 7.58,
                         "the prediction must be recorded against the realized value")

    def test_fail_path_marks_regressed_and_reverts_for_real(self):
        import improvement_verify
        fake = FakeDB({"improvement_proposals": [self._proposal()]})
        improvement_verify.db = fake
        import gate_liveness; gate_liveness.db = fake
        # metric barely moved: 7.58 -> 7.20 == 1.05x, short of the 2.0x margin
        out = improvement_verify.settle(self._proposal(), injected=7.20, dry_run=True)
        self.assertEqual(out["verdict"], "regressed")
        self.assertTrue(out["rolled_back"], out.get("rollback"))
        rsha = out["rollback"]["revert_sha"]
        self.assertEqual(git(self.repo, "show", f"{rsha}:a.txt").stdout, "one\n",
                         "the revert must actually undo the shipped change")
        statuses = [pt["status"] for _, _, pt in fake.updates if "status" in pt]
        self.assertIn("regressed", statuses)
        self.assertEqual(fake.tables["improvement_calibration"][0]["outcome"], "regressed")

    def test_missing_baseline_is_unmeasurable_not_a_pass(self):
        """No baseline must never be silently treated as success."""
        import improvement_verify
        improvement_verify.db = FakeDB()
        p = dict(self._proposal()); p["baseline_value"] = None
        self.assertEqual(improvement_verify.evaluate(p, injected=1.0)["verdict"], "unmeasurable")


if __name__ == "__main__":
    unittest.main(verbosity=2)
