#!/usr/bin/env python3
"""Promotion must SEE every task that carries release evidence.

2026-08-06: beethoven's first green release in 17 days (sha 03f5954581, verified)
promoted zero tasks. Not because nothing qualified — because promote_release read an
unordered `limit: 500` slice of a 1,296-row MERGED population. The ~19 promotable
rows could sit entirely outside that page, and two runs could pick different pages.

The fix is server-side filtering + deterministic order + pagination, NOT a bigger
limit; raising the limit is the anti-pattern that caused this same failure in
_pick_cards, ensure_integration_card, ev_scheduler and config_optimizer.

These tests deliberately place the promotable rows beyond the first page.
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("SUPABASE_URL", "http://localhost")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test-key")
os.environ["ORCH_DEPLOY_TERMINAL_ENABLED"] = "1"

import deployment_terminal as dt  # noqa: E402

RELEASE_SHA = "a" * 40
PROMOTABLE = {"p1", "p2", "p3"}          # ancestors of the release
ABSENT = {"gone1"}                        # commit not in the repo at all


def _tasks(n=1500):
    """n MERGED tasks; the 3 promotable ones sit deep past any 500-row page."""
    rows = []
    for i in range(n):
        rows.append({"id": f"t{i:05d}", "slug": f"task-{i}", "state": "MERGED",
                     "artifact_commit": f"c{i:039d}"})
    rows[900]["artifact_commit"] = "p1"
    rows[1200]["artifact_commit"] = "p2"
    rows[1499]["artifact_commit"] = "p3"
    rows[1300]["artifact_commit"] = "gone1"
    rows[10]["artifact_commit"] = ""       # no evidence recorded
    rows[11]["artifact_commit"] = None
    return rows


def _fake_select(all_rows):
    """Emulate PostgREST: honour artifact_commit filter, order, limit and offset."""
    def _select(table, params=None):
        params = params or {}
        if table == "projects":
            return [{"id": "proj-1", "repo_path": "/repo"}]
        rows = list(all_rows)
        if params.get("artifact_commit") == "not.is.null":
            rows = [r for r in rows if r.get("artifact_commit") is not None]
        rows.sort(key=lambda r: r["id"])          # order=id.asc
        offset = int(params.get("offset", 0) or 0)
        limit = int(params.get("limit", 500) or 500)
        return rows[offset:offset + limit]
    return _select


def _fake_classify(repo, commit, release_sha):
    c = (commit or "").strip()
    if not c:
        return dt.BUCKET_NO_COMMIT
    if c in ABSENT:
        return dt.BUCKET_COMMIT_ABSENT
    if c in PROMOTABLE:
        return dt.BUCKET_PROMOTABLE
    return dt.BUCKET_NOT_ANCESTOR


class PromotionWindowTest(unittest.TestCase):
    def setUp(self):
        self.rows = _tasks()
        self.updated = []
        self.release = {"project": "beethoven", "created_at": "2026-08-06T22:52:00Z"}
        self.verify = {"ok": True, "sha": RELEASE_SHA, "url": "https://x", "reason": "verified"}

        self.p_select = mock.patch.object(dt.db, "select", side_effect=_fake_select(self.rows))
        self.p_update = mock.patch.object(
            dt.db, "update", side_effect=lambda t, w, p: self.updated.append(w["id"]))
        self.p_verify = mock.patch.object(dt, "verify_release", return_value=self.verify)
        self.p_class = mock.patch.object(dt, "_classify_candidate", side_effect=_fake_classify)
        self.p_isdir = mock.patch.object(dt.os.path, "isdir", return_value=True)
        for p in (self.p_select, self.p_update, self.p_verify, self.p_class, self.p_isdir):
            p.start()
            self.addCleanup(p.stop)

    # 1
    def test_promotable_beyond_the_first_page_are_still_promoted(self):
        out = dt.promote_release(self.release)
        self.assertEqual(out["promoted"], 3,
                         "all 3 promotable rows must be found despite sitting past row 500")
        self.assertEqual(len(self.updated), 3)

    # 2
    def test_task_without_artifact_commit_is_never_promoted(self):
        out = dt.promote_release(self.release)
        self.assertGreaterEqual(out["funnel"][dt.BUCKET_NO_COMMIT], 1)
        promoted_commits = {r["artifact_commit"] for r in self.rows if r["id"] in self.updated}
        self.assertNotIn("", promoted_commits)
        self.assertNotIn(None, promoted_commits)

    # 3
    def test_non_ancestor_commit_is_counted_not_promoted(self):
        out = dt.promote_release(self.release)
        self.assertGreater(out["funnel"][dt.BUCKET_NOT_ANCESTOR], 0)
        self.assertEqual(out["promoted"], 3)

    # 4
    def test_absent_commit_is_routed_to_recovery(self):
        with mock.patch.object(dt, "_route_absent_commits_to_recovery") as route:
            out = dt.promote_release(self.release)
        self.assertEqual(out["funnel"][dt.BUCKET_COMMIT_ABSENT], 1)
        route.assert_called_once()
        self.assertEqual(len(route.call_args[0][1]), 1)

    # 5
    def test_two_consecutive_runs_promote_the_same_set(self):
        first = dt.promote_release(self.release)
        seen_first = list(self.updated)
        self.updated.clear()
        second = dt.promote_release(self.release)
        self.assertEqual(first["promoted"], second["promoted"])
        self.assertEqual(sorted(seen_first), sorted(self.updated))

    # 6
    def test_funnel_is_logged_even_when_nothing_promotes(self):
        with mock.patch.object(dt, "_classify_candidate",
                               side_effect=lambda *a: dt.BUCKET_NOT_ANCESTOR):
            with mock.patch("builtins.print") as pr:
                out = dt.promote_release(self.release)
        self.assertEqual(out["promoted"], 0)
        logged = " ".join(str(c) for c in pr.call_args_list)
        self.assertIn("promotion funnel", logged)
        self.assertIn("candidates=", logged)

    def test_the_fix_is_not_a_bigger_limit(self):
        # Guard the anti-pattern explicitly: pages must be requested with an offset.
        seen = []

        def _spy(table, params=None):
            seen.append(params or {})
            return _fake_select(self.rows)(table, params)

        with mock.patch.object(dt.db, "select", side_effect=_spy):
            dt.promote_release(self.release)
        task_q = [p for p in seen if p.get("state") == "eq.MERGED"]
        self.assertTrue(task_q, "expected a MERGED task query")
        self.assertTrue(any("offset" in p for p in task_q), "must paginate, not widen")
        self.assertTrue(all(p.get("order") for p in task_q), "must order deterministically")
        self.assertTrue(all(p.get("artifact_commit") == "not.is.null" for p in task_q),
                        "must filter for evidence server-side")


class ClassifyCandidateTest(unittest.TestCase):
    """The three non-promotable reasons must stay distinguishable."""

    def test_empty_commit_is_no_commit(self):
        self.assertEqual(dt._classify_candidate("/repo", "", RELEASE_SHA), dt.BUCKET_NO_COMMIT)
        self.assertEqual(dt._classify_candidate("/repo", None, RELEASE_SHA), dt.BUCKET_NO_COMMIT)

    def test_missing_object_is_commit_absent(self):
        with mock.patch.object(dt.os.path, "isdir", return_value=True), \
             mock.patch.object(dt, "_commit_exists", return_value=False):
            self.assertEqual(dt._classify_candidate("/repo", "deadbeef", RELEASE_SHA),
                             dt.BUCKET_COMMIT_ABSENT)

    def test_present_but_unrelated_is_not_ancestor(self):
        with mock.patch.object(dt.os.path, "isdir", return_value=True), \
             mock.patch.object(dt, "_commit_exists", return_value=True), \
             mock.patch.object(dt.subprocess, "run",
                               return_value=mock.Mock(returncode=1)):
            self.assertEqual(dt._classify_candidate("/repo", "deadbeef", RELEASE_SHA),
                             dt.BUCKET_NOT_ANCESTOR)

    def test_ancestor_is_promotable(self):
        with mock.patch.object(dt.os.path, "isdir", return_value=True), \
             mock.patch.object(dt, "_commit_exists", return_value=True), \
             mock.patch.object(dt.subprocess, "run",
                               return_value=mock.Mock(returncode=0)):
            self.assertEqual(dt._classify_candidate("/repo", "deadbeef", RELEASE_SHA),
                             dt.BUCKET_PROMOTABLE)

    def test_commit_in_release_stays_backward_compatible(self):
        with mock.patch.object(dt, "_classify_candidate", return_value=dt.BUCKET_PROMOTABLE):
            self.assertTrue(dt._commit_in_release("/repo", "x", RELEASE_SHA))
        with mock.patch.object(dt, "_classify_candidate", return_value=dt.BUCKET_NOT_ANCESTOR):
            self.assertFalse(dt._commit_in_release("/repo", "x", RELEASE_SHA))


class PaginationTest(unittest.TestCase):
    def test_pagination_reaches_every_row(self):
        rows = [{"id": f"t{i:05d}", "slug": f"s{i}", "state": "MERGED",
                 "artifact_commit": f"c{i}"} for i in range(1500)]
        with mock.patch.object(dt.db, "select", side_effect=_fake_select(rows)):
            out = dt._select_all_merged_with_commit("proj-1", None, page_size=500)
        self.assertEqual(len(out), 1500)
        self.assertEqual(len({r["id"] for r in out}), 1500, "no duplicates across pages")

    def test_pagination_survives_a_db_error_midway(self):
        calls = {"n": 0}

        def _flaky(table, params=None):
            calls["n"] += 1
            if calls["n"] > 1:
                raise RuntimeError("db down")
            return [{"id": f"t{i}", "slug": "s", "state": "MERGED",
                     "artifact_commit": "c"} for i in range(500)]

        with mock.patch.object(dt.db, "select", side_effect=_flaky):
            out = dt._select_all_merged_with_commit("proj-1", None, page_size=500)
        self.assertEqual(len(out), 500, "partial results beat raising mid-promotion")


if __name__ == "__main__":
    unittest.main()
