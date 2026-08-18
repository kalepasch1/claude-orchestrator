#!/usr/bin/env python3
"""Promotion to DEPLOYED_AND_VERIFIED had two stacked gates that nothing could pass.

MEASURED BEFORE THIS CHANGE
---------------------------
Nothing reached DEPLOYED_AND_VERIFIED after 2026-08-07 12:34Z. Merges continued at 14/24h.
beethoven shipped 21 green releases in 11 days, and 259 of its 263 MERGED task commits are
ancestors of the last green release sha. The work was shipping; the state machine had stopped
recording that it shipped.

GATE 1 — exact liveness.
  `sha_is_live` demanded byte-identity with the commit serving production. Promotion scans the
  25 most recent green releases, so at most one of them could ever satisfy that, and only until
  the next deploy. Release volume went ~5/day -> ~390/day, shrinking the exactly-live window
  from hours to minutes. Ancestor-of-live is STRICTER, not looser: it proves the commit shipped
  AND has not been rolled back out since.

GATE 2 — the journey gate had no key.
  `spec_for_task` reads `task["journey"]`. The `tasks` table has no such column and nothing
  populates one, so every task produced a MISSING receipt and every task was refused from the
  day the gate landed. ORCH_JOURNEY_ALLOW_MISSING (default OFF) covers only the never-declared
  case; FAIL and FLAKY still block regardless.

Hermetic: no Vercel, no database, no network. A real git repo is built in a tmpdir so ancestry
is answered by git itself rather than by a mock that would agree with whatever we assert.
"""
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import deployment_terminal as dt          # noqa: E402
import production_journey as pj           # noqa: E402


def _git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True)


class _Repo:
    """A three-commit line plus a divergent branch, so ancestry has something to be wrong about."""

    def __enter__(self):
        self.dir = tempfile.mkdtemp(prefix="promo-repo-")
        _git(self.dir, "init", "-q", "-b", "master")
        _git(self.dir, "config", "user.email", "t@example.com")
        _git(self.dir, "config", "user.name", "t")
        self.shas = []
        for i in range(3):
            with open(os.path.join(self.dir, f"f{i}.txt"), "w") as fh:
                fh.write(str(i))
            _git(self.dir, "add", "-A")
            _git(self.dir, "commit", "-q", "-m", f"c{i}")
            self.shas.append(_git(self.dir, "rev-parse", "HEAD").stdout.strip())
        _git(self.dir, "checkout", "-q", "-b", "side", self.shas[0])
        with open(os.path.join(self.dir, "side.txt"), "w") as fh:
            fh.write("side")
        _git(self.dir, "add", "-A")
        _git(self.dir, "commit", "-q", "-m", "side")
        self.side = _git(self.dir, "rev-parse", "HEAD").stdout.strip()
        _git(self.dir, "checkout", "-q", "master")
        return self

    def __exit__(self, *exc):
        import shutil
        shutil.rmtree(self.dir, ignore_errors=True)
        return False


class TestAncestryCountsAsDelivery(unittest.TestCase):

    def test_the_exactly_live_commit_is_delivered(self):
        with _Repo() as r:
            ok, why = dt.sha_reached_production("p", r.shas[2], repo=r.dir, live_sha=r.shas[2])
        self.assertTrue(ok)
        self.assertIn("live production build", why)

    def test_an_ancestor_of_the_live_commit_is_delivered(self):
        # THE FIX. This is the case that stalled: shipped two releases ago, still in production.
        with _Repo() as r:
            ok, why = dt.sha_reached_production("p", r.shas[0], repo=r.dir, live_sha=r.shas[2])
        self.assertTrue(ok)
        self.assertIn("ancestor", why)

    def test_a_commit_that_never_landed_is_not_delivered(self):
        with _Repo() as r:
            ok, why = dt.sha_reached_production("p", r.side, repo=r.dir, live_sha=r.shas[2])
        self.assertFalse(ok)
        self.assertIn("not an ancestor", why)

    def test_a_rolled_back_commit_stops_being_delivered(self):
        # Ancestry is strictly stronger than identity precisely here: roll production back to
        # c0 and the later commits correctly stop qualifying.
        with _Repo() as r:
            ok, _ = dt.sha_reached_production("p", r.shas[2], repo=r.dir, live_sha=r.shas[0])
        self.assertFalse(ok)

    def test_an_absent_commit_is_unprovable_not_delivered(self):
        with _Repo() as r:
            ok, why = dt.sha_reached_production("p", "0" * 40, repo=r.dir, live_sha=r.shas[2])
        self.assertFalse(ok)
        self.assertIn("absent", why)

    def test_no_repo_means_unproven_not_promoted(self):
        ok, why = dt.sha_reached_production("p", "a" * 40, repo="/nonexistent/xyz",
                                            live_sha="b" * 40)
        self.assertFalse(ok)
        self.assertIn("ancestry", why)

    def test_no_live_sha_means_not_delivered(self):
        ok, why = dt.sha_reached_production("p", "a" * 40, repo="", live_sha="")
        self.assertFalse(ok)


class TestIdentitySemanticsArePreserved(unittest.TestCase):
    """`sha_is_live` still answers 'which release is serving'. Collapsing the two questions
    into one function is how the gate got the wrong semantics in the first place."""

    def test_exact_match_is_live(self):
        ok, _ = dt.sha_is_live("p", "a" * 40, live_sha="a" * 40)
        self.assertTrue(ok)

    def test_an_ancestor_is_not_live(self):
        with _Repo() as r:
            ok, why = dt.sha_is_live("p", r.shas[0], live_sha=r.shas[2])
        self.assertFalse(ok)
        self.assertIn("!=", why)

    def test_short_sha_prefixes_still_match(self):
        ok, _ = dt.sha_is_live("p", ("a" * 40)[:12], live_sha="a" * 40)
        self.assertTrue(ok)


class TestJourneyAllowMissing(unittest.TestCase):

    def setUp(self):
        for k in ("ORCH_JOURNEY_ALLOW_MISSING", "ORCH_JOURNEY_ALLOW_FLAKY"):
            os.environ.pop(k, None)

    tearDown = setUp

    def _missing(self, **kw):
        return pj.receipt_missing(sha="a" * 40, base_url="https://x.test", **kw)

    def test_undeclared_blocks_by_default(self):
        ok, why = pj.gate(self._missing())
        self.assertFalse(ok)
        self.assertIn("not sufficient", why)

    def test_undeclared_passes_when_the_allowance_is_on(self):
        os.environ["ORCH_JOURNEY_ALLOW_MISSING"] = "1"
        ok, why = pj.gate(self._missing())
        self.assertTrue(ok)

    def test_the_allowance_states_that_behaviour_was_not_proven(self):
        os.environ["ORCH_JOURNEY_ALLOW_MISSING"] = "1"
        _, why = pj.gate(self._missing())
        self.assertIn("NOT PROVEN", why)
        self.assertIn("ORCH_JOURNEY_ALLOW_MISSING", why)

    def test_a_malformed_declaration_is_not_covered_by_the_allowance(self):
        # Somebody wrote a journey and it does not parse. That is a defect to fix, not an
        # absence to wave through, and one env var must not silently cover both.
        os.environ["ORCH_JOURNEY_ALLOW_MISSING"] = "1"
        ok, _ = pj.gate(self._missing(reason="invalid journey spec: boom",
                                      reason_code=pj.REASON_MALFORMED))
        self.assertFalse(ok)

    def test_a_failed_journey_still_blocks_with_the_allowance_on(self):
        os.environ["ORCH_JOURNEY_ALLOW_MISSING"] = "1"
        receipt = {"verdict": pj.FAIL, "required": True,
                   "failed_assertions": [{"step": "home", "assertion": "status",
                                          "expected": 200, "actual": 500}]}
        ok, why = pj.gate(receipt)
        self.assertFalse(ok)
        self.assertIn("journey failed", why)

    def test_a_flaky_journey_still_blocks_with_the_allowance_on(self):
        os.environ["ORCH_JOURNEY_ALLOW_MISSING"] = "1"
        ok, why = pj.gate({"verdict": pj.FLAKY, "required": True})
        self.assertFalse(ok)
        self.assertIn("flaky", why)

    def test_a_legacy_receipt_without_a_reason_code_is_read_as_undeclared(self):
        os.environ["ORCH_JOURNEY_ALLOW_MISSING"] = "1"
        legacy = {"verdict": pj.MISSING, "required": True, "note": "no journey declared"}
        ok, _ = pj.gate(legacy)
        self.assertTrue(ok)

    def test_a_legacy_receipt_with_an_unrecognised_note_is_not_waved_through(self):
        os.environ["ORCH_JOURNEY_ALLOW_MISSING"] = "1"
        legacy = {"verdict": pj.MISSING, "required": True, "note": "prover crashed"}
        ok, _ = pj.gate(legacy)
        self.assertFalse(ok)

    def test_the_gate_has_no_key_today(self):
        # The reason the gate refused everything: `tasks` has no `journey` column, so
        # spec_for_task returns None for every real row.
        self.assertIsNone(pj.spec_for_task({"slug": "s", "state": "MERGED"}))


class TestPromotionRunsEndToEnd(unittest.TestCase):
    """The two fixes have to compose: ancestry admits the task, the allowance admits the
    journey, and the note that lands on the row has to admit what was not checked."""

    def setUp(self):
        os.environ["ORCH_JOURNEY_ALLOW_MISSING"] = "1"

    def tearDown(self):
        os.environ.pop("ORCH_JOURNEY_ALLOW_MISSING", None)

    def test_an_ancestor_task_is_promoted_and_the_note_admits_it_is_unproven(self):
        with _Repo() as r:
            verify = {"project": "beethoven", "sha": r.shas[2], "url": "https://x.test",
                      "http_status": 200, "http_ok": True, "sha_delivered": True,
                      "sha_identical": True, "sha_live": True, "ok": True,
                      "reason": "release healthy"}
            updates = []
            fake_db = mock.MagicMock()
            fake_db.select.side_effect = lambda table, params: (
                [{"id": "pid", "repo_path": r.dir}] if table == "projects"
                else [{"id": "t1", "slug": "s1", "state": "MERGED",
                       "artifact_commit": r.shas[0]}])
            fake_db.localize_repo_path.side_effect = lambda p: p
            fake_db.update.side_effect = lambda t, w, v: updates.append((w, v))
            with mock.patch.object(dt, "verify_release", return_value=verify), \
                    mock.patch.object(dt, "db", fake_db):
                out = dt.promote_release({"project": "beethoven", "to_sha": r.shas[2]})
        self.assertEqual(out["promoted"], 1)
        note = updates[0][1]["note"]
        self.assertIn("NOT PROVEN", note)

    def test_a_non_ancestor_task_is_still_refused(self):
        with _Repo() as r:
            verify = {"project": "beethoven", "sha": r.shas[2], "url": "https://x.test",
                      "http_status": 200, "http_ok": True, "sha_delivered": True,
                      "sha_identical": True, "sha_live": True, "ok": True,
                      "reason": "release healthy"}
            fake_db = mock.MagicMock()
            fake_db.select.side_effect = lambda table, params: (
                [{"id": "pid", "repo_path": r.dir}] if table == "projects"
                else [{"id": "t1", "slug": "s1", "state": "MERGED",
                       "artifact_commit": r.side}])
            fake_db.localize_repo_path.side_effect = lambda p: p
            with mock.patch.object(dt, "verify_release", return_value=verify), \
                    mock.patch.object(dt, "db", fake_db):
                out = dt.promote_release({"project": "beethoven", "to_sha": r.shas[2]})
        self.assertEqual(out["promoted"], 0)
        self.assertEqual(out["funnel"][dt.BUCKET_NOT_ANCESTOR], 1)


class _FakeDeployVerify:
    """Stands in for the real Vercel client. `deployments` is newest-first, as the API returns."""

    def __init__(self, deployments):
        self.deployments = deployments
        self.calls = []

    def _vercel_project(self, project, project_row=None, health=None):
        return project

    def _latest_deploy(self, vercel_project, sha=None, states=None):
        self.calls.append({"sha": sha, "states": states})
        deps = list(self.deployments)
        if states:
            deps = [d for d in deps if (d.get("state") or d.get("readyState")) in set(states)]
        if not deps:
            return None
        if sha:
            short = str(sha)[:12]
            for dep in deps:
                dsha = (dep.get("meta") or {}).get("githubCommitSha") or ""
                if dsha and (str(dsha) == str(sha) or str(dsha).startswith(short)):
                    return dep
        return deps[0]


def _dep(state, sha):
    return {"state": state, "meta": {"githubCommitSha": sha}}


class _StubbedDeployVerify:
    def __init__(self, fake):
        self.fake = fake

    def __enter__(self):
        self._prev = sys.modules.get("deploy_verify")
        sys.modules["deploy_verify"] = self.fake
        return self.fake

    def __exit__(self, *exc):
        if self._prev is None:
            sys.modules.pop("deploy_verify", None)
        else:
            sys.modules["deploy_verify"] = self._prev
        return False


class TestLiveShaIgnoresNonReadyDeployments(unittest.TestCase):
    """REGRESSION. `_latest_deploy(vproj)` returns the newest production deployment in ANY
    state. At ~390 releases/day there is nearly always a QUEUED or BUILDING one in front of
    the build actually serving traffic, and an ERROR build sits there indefinitely. Reading
    state off that row and bailing made `live_production_sha` return "" for a healthy project,
    which fails the delivery gate and promotes nothing — the exact stall being fixed."""

    def test_a_building_deployment_in_front_does_not_blind_the_gate(self):
        fake = _FakeDeployVerify([_dep("BUILDING", "b" * 40), _dep("READY", "a" * 40)])
        with _StubbedDeployVerify(fake):
            sha, why = dt.live_production_sha("beethoven")
        self.assertEqual(sha, "a" * 40)
        self.assertEqual(fake.calls[0]["states"], ("READY",))

    def test_an_error_build_in_front_does_not_blind_the_gate(self):
        fake = _FakeDeployVerify([_dep("ERROR", "c" * 40), _dep("READY", "a" * 40)])
        with _StubbedDeployVerify(fake):
            sha, _ = dt.live_production_sha("beethoven")
        self.assertEqual(sha, "a" * 40)

    def test_the_newest_ready_one_wins_not_an_older_ready_one(self):
        fake = _FakeDeployVerify([_dep("QUEUED", "d" * 40), _dep("READY", "a" * 40),
                                  _dep("READY", "e" * 40)])
        with _StubbedDeployVerify(fake):
            sha, _ = dt.live_production_sha("beethoven")
        self.assertEqual(sha, "a" * 40)

    def test_no_ready_deployment_at_all_is_still_reported_as_such(self):
        fake = _FakeDeployVerify([_dep("BUILDING", "b" * 40)])
        with _StubbedDeployVerify(fake):
            sha, why = dt.live_production_sha("beethoven")
        self.assertEqual(sha, "")
        self.assertIn("READY", why)

    def test_delivery_is_still_refused_when_vercel_shows_nothing(self):
        fake = _FakeDeployVerify([])
        with _StubbedDeployVerify(fake):
            ok, _ = dt.sha_reached_production("beethoven", "a" * 40)
        self.assertFalse(ok)


class TestRevertedCommitsAreNotDelivered(unittest.TestCase):
    """ANCESTRY IS NOT PRESENCE. `git revert` writes a new commit and leaves the original an
    ancestor of HEAD, so an ancestry check alone calls a reverted change "delivered". This
    fleet reverts for real — rollback_chain.py and improvement_verify.py both use git revert."""

    def test_a_reverted_commit_is_refused(self):
        with _Repo() as r:
            target = r.shas[1]
            _git(r.dir, "revert", "--no-edit", target)
            live = _git(r.dir, "rev-parse", "HEAD").stdout.strip()
            self.assertEqual(subprocess.run(
                ["git", "merge-base", "--is-ancestor", target, live],
                cwd=r.dir, capture_output=True).returncode, 0,
                "precondition: the reverted commit is still an ancestor")
            ok, why = dt.sha_reached_production("p", target, repo=r.dir, live_sha=live)
        self.assertFalse(ok)
        self.assertIn("REVERTED", why)

    def test_an_unrelated_revert_does_not_block_a_good_commit(self):
        with _Repo() as r:
            _git(r.dir, "revert", "--no-edit", r.shas[1])
            live = _git(r.dir, "rev-parse", "HEAD").stdout.strip()
            ok, why = dt.sha_reached_production("p", r.shas[0], repo=r.dir, live_sha=live)
        self.assertTrue(ok, why)

    def test_the_claim_no_longer_overstates_what_was_checked(self):
        with _Repo() as r:
            _, why = dt.sha_reached_production("p", r.shas[0], repo=r.dir, live_sha=r.shas[2])
        self.assertIn("no revert of it appears", why)
        self.assertNotIn("has not been rolled back", why)


class TestNoReceiptIsNotAnUndeclaredJourney(unittest.TestCase):
    """The allowance covers "a receipt that says nobody declared a journey". It must NOT cover
    "no receipt at all" — a caller that produced None or {} failed to produce evidence, which
    is not the same as evidence of absence. `deploy_verify` passes None on provider-skipped
    builds, and `verify_release(..., journey={})` reaches the same branch."""

    def setUp(self):
        os.environ["ORCH_JOURNEY_ALLOW_MISSING"] = "1"

    def tearDown(self):
        os.environ.pop("ORCH_JOURNEY_ALLOW_MISSING", None)

    def test_none_still_blocks(self):
        ok, why = pj.gate(None)
        self.assertFalse(ok)
        self.assertIn("not sufficient", why)

    def test_empty_dict_still_blocks(self):
        ok, _ = pj.gate({})
        self.assertFalse(ok)

    def test_a_real_undeclared_receipt_still_passes(self):
        # The boundary has to admit the case it was built for, or the fix is just a revert.
        ok, _ = pj.gate(pj.receipt_missing(sha="a" * 40, base_url="https://x.test"))
        self.assertTrue(ok)

    def test_not_required_still_short_circuits(self):
        ok, why = pj.gate(None, required=False)
        self.assertTrue(ok)
        self.assertIn("no journey required", why)


if __name__ == "__main__":
    unittest.main()
