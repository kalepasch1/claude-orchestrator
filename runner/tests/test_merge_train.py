"""
test_merge_train.py - safety + correctness for the serialized integration train.

Everything external is mocked: db (module-level patch), git plumbing helpers, and tests.
The train must:
  A) merge a clean approved card: task -> MERGED, card -> train:MERGED
  B) skip cards already handled by the train or the legacy merge-handler, and non-merge kinds
  C) on rebase conflict under the redo cap: delete branch, requeue task with transient_retries+1,
     card -> train:redo
  D) on rebase conflict past the cap: task -> CONFLICT, card -> train:conflict-exhausted
  E) on test failure: task -> TESTFAIL, card -> train:TESTFAIL, and NEVER fast-forward the base
  F) serialize per project, oldest approval first
  G) branch-missing approved cards remain live while the task is still being rebuilt
"""
import os, sys, tempfile, unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import merge_train
import subprocess


def _card(cid, slug, kind="integrate", decided_by=None, created_at="2026-01-01T00:00:00"):
    return {"id": cid, "slug": slug, "kind": kind, "status": "approved",
            "decided_by": decided_by, "created_at": created_at, "title": f"merge of {slug}"}


def _task(tid, slug, project_id="p1", state="BLOCKED", retries=0):
    return {"id": tid, "slug": slug, "project_id": project_id, "state": state,
            "transient_retries": retries, "base_branch": None}


PROJECTS = [{"id": "p1", "name": "alpha", "repo_path": "/tmp/fake-repo-alpha",
             "default_base": "main", "test_cmd": "true"},
            {"id": "p2", "name": "beta", "repo_path": "/tmp/fake-repo-beta",
             "default_base": "main", "test_cmd": "true"}]


class TrainCase(unittest.TestCase):
    """Shared harness: mock db + git helpers, capture db.update calls."""

    def setUp(self):
        self.updates = []          # (table, match, patch)
        self.cards = []
        self.tasks = []

        self.mock_db = MagicMock()
        self.mock_db.select.side_effect = self._select
        self.mock_db.update.side_effect = \
            lambda table, match, patch: self.updates.append((table, match, patch))
        # Default: behave like a machine where the stored repo_path is already correct
        # (identity passthrough), matching db.localize_repo_path()'s real no-op behavior
        # when os.path.isdir(repo_path) is true on this host. Tests that specifically
        # exercise cross-host localization override this per-test.
        self.mock_db.localize_repo_path.side_effect = lambda p: p

        patches = [
            patch.object(merge_train, "db", self.mock_db),
            patch.object(merge_train, "_branch_exists", return_value=True),
            patch.object(merge_train, "_refresh_base", return_value=None),
            patch.object(merge_train, "_already_integrated", return_value=False),
            patch.object(merge_train, "_rebase_onto_base", return_value=True),
            patch.object(merge_train, "_run_tests", return_value=(True, "green")),
            patch.object(merge_train, "_ff_base", return_value=True),
            patch.object(merge_train, "_push_base", return_value=""),
            patch.object(merge_train, "_delete_branch", return_value=None),
            patch.object(merge_train.approval_merge, "_free_branch", return_value=None),
            patch.object(merge_train, "_paused", return_value=False),
            patch.object(merge_train.os.path, "isdir", return_value=True),
        ]
        self.mocks = {}
        for p in patches:
            m = p.start()
            self.addCleanup(p.stop)
            name = getattr(p, "attribute", None)
            if name:
                self.mocks[name] = m

    def _select(self, table, params=None):
        if table == "approvals":
            return list(self.cards)
        if table == "projects":
            return list(PROJECTS)
        if table == "tasks":
            raw = (params or {}).get("slug", "eq.")
            if raw.startswith("in.("):
                slugs = raw[len("in.("):-1].split(",")
                return [t for t in self.tasks if t["slug"] in slugs]
            slug = raw.split("eq.", 1)[1]
            return [t for t in self.tasks if t["slug"] == slug]
        if table == "controls":
            return []
        return []

    def task_updates(self, tid):
        return [p for (tbl, m, p) in self.updates if tbl == "tasks" and m.get("id") == tid]

    def card_updates(self, cid):
        return [p for (tbl, m, p) in self.updates if tbl == "approvals" and m.get("id") == cid]


# ── repo_path localization (2026-07-11) ─────────────────────────────────────
# projects.repo_path is one shared absolute path stored fleet-wide (e.g.
# /Users/kpasch/Documents/foo). On a second machine with a different home directory
# that path doesn't exist, so merge_train crashed with FileNotFoundError on every
# single cycle there -- 676+ consecutive tracebacks in production, zero successful
# merges for hours. db.localize_repo_path() rewrites the /Users/<user>/ prefix to
# the current host's home when a local clone actually exists there. These tests
# prove merge_train routes every repo_path read through it instead of using the
# raw stored value.

class TestRepoPathLocalization(TrainCase):

    def test_integrate_card_localizes_repo_path_before_use(self):
        self.cards = [_card("c1", "feat-x")]
        self.tasks = [_task("t1", "feat-x")]
        localized = "/Users/mandypasch/Documents/alpha"
        self.mock_db.localize_repo_path.side_effect = None
        self.mock_db.localize_repo_path.return_value = localized

        merge_train.train_run()

        self.mock_db.localize_repo_path.assert_any_call("/tmp/fake-repo-alpha")
        # os.path.isdir is patched fleet-wide in setUp; confirm it was actually asked
        # about the LOCALIZED path, not the raw stored one, proving the localized
        # value is what flows into the no-repo/skip guard.
        isdir_calls = [c.args[0] for c in self.mocks["isdir"].call_args_list]
        self.assertIn(localized, isdir_calls)
        self.assertNotIn("/tmp/fake-repo-alpha", isdir_calls)

    def test_record_pressure_localizes_repo_path_before_use(self):
        self.cards = [_card("c1", "feat-x", created_at="2026-01-01T00:00:00")]
        self.tasks = [_task("t1", "feat-x", state="BLOCKED")]
        localized = "/Users/mandypasch/Documents/alpha"
        self.mock_db.localize_repo_path.side_effect = None
        self.mock_db.localize_repo_path.return_value = localized

        with patch.object(merge_train, "_materialize_branch", return_value=True) as mb:
            merge_train.train_run()

        # _record_pressure calls _materialize_branch(repo, f"agent/{slug}") for every
        # waiting card -- confirm it received the LOCALIZED repo, not the raw stored one.
        self.assertTrue(any(call.args[0] == localized for call in mb.call_args_list))
        self.assertFalse(any(call.args[0] == "/tmp/fake-repo-alpha" for call in mb.call_args_list))


# ── A: clean merge ────────────────────────────────────────────────────────────

class TestCleanMerge(TrainCase):

    def test_approved_card_merges(self):
        self.cards = [_card("c1", "feat-x")]
        self.tasks = [_task("t1", "feat-x")]
        summary = merge_train.train_run()
        self.assertEqual(summary["merged"], 1)
        tps = self.task_updates("t1")
        self.assertEqual(tps[0]["state"], merge_train.MERGING_STATE)
        self.assertEqual(tps[-1]["state"], "MERGED")
        cps = self.card_updates("c1")
        self.assertEqual(cps[-1]["decided_by"], "train:MERGED")
        self.assertTrue(any(tbl == "outcomes" and m.get("slug") == "feat-x" and p.get("integrated") is True
                            for tbl, m, p in self.updates))

    def test_already_integrated_card_does_not_count_as_new_merge(self):
        self.cards = [_card("c1", "feat-x")]
        self.tasks = [_task("t1", "feat-x")]
        self.mocks["_already_integrated"].return_value = True
        summary = merge_train.train_run()
        self.assertEqual(summary["merged"], 0)
        self.assertEqual(summary["already_integrated"], 1)
        self.mocks["_run_tests"].assert_not_called()
        self.mocks["_ff_base"].assert_not_called()
        self.assertEqual(self.task_updates("t1")[-1]["state"], "MERGED")
        self.assertEqual(self.card_updates("c1")[-1]["decided_by"],
                         "train:ALREADY_INTEGRATED")

    def test_merge_never_forced_when_tests_green_but_ff_and_rebase_used(self):
        """The train's git surface is rebase + ff only — verify both were invoked."""
        self.cards = [_card("c1", "feat-x")]
        self.tasks = [_task("t1", "feat-x")]
        merge_train.train_run()
        self.mocks["_rebase_onto_base"].assert_called_once()
        self.mocks["_ff_base"].assert_called_once()


# ── B: idempotency + filtering ────────────────────────────────────────────────

class TestSkipsHandledCards(TrainCase):

    def test_train_handled_card_skipped(self):
        self.cards = [_card("c1", "feat-x", decided_by="train:MERGED")]
        self.tasks = [_task("t1", "feat-x")]
        summary = merge_train.train_run()
        self.assertEqual(summary["merged"], 0)
        self.assertEqual(self.updates, [], "already-handled card must be untouched")

    def test_merge_handler_card_skipped(self):
        self.cards = [_card("c1", "feat-x", decided_by="merge-handler:MERGED")]
        self.tasks = [_task("t1", "feat-x")]
        summary = merge_train.train_run()
        self.assertEqual(summary["merged"], 0)
        self.assertEqual(self.updates, [])

    def test_non_merge_kind_ignored(self):
        self.cards = [_card("c1", "feat-x", kind="proposal")]
        self.tasks = [_task("t1", "feat-x")]
        summary = merge_train.train_run()
        self.assertEqual(summary["merged"], 0)
        self.assertEqual(self.updates, [])

    def test_card_without_code_merge_slug_ignored(self):
        self.cards = [{"id": "c1", "kind": "integrate", "status": "approved",
                       "decided_by": None, "title": "no slug here", "created_at": "x"}]
        summary = merge_train.train_run()
        self.assertEqual(summary["merged"], 0)
        self.assertEqual(self.card_updates("c1"), [])

    def test_freshly_attributed_card_is_still_processed(self):
        """Regression guard (2026-07-10): ensure_integration_card() stamps every fresh card's
        decided_by with an ATTRIBUTION prefix ("canonical-train:sweeper" / "canonical-train:runner")
        at creation time -- this is who queued it, not a verdict. A prior same-day fix (#6)
        treated any non-empty decided_by as "already handled", which meant _pick_cards() could
        never see a freshly-created card again: zero cards picked, forever. Cards decided by
        "canonical-train:*" must still be picked up and merged."""
        for source in ("canonical-train:sweeper", "canonical-train:runner"):
            with self.subTest(source=source):
                self.updates = []
                self.cards = [_card("c1", "feat-x", decided_by=source)]
                self.tasks = [_task("t1", "feat-x")]
                summary = merge_train.train_run()
                self.assertEqual(summary["merged"], 1)
                self.assertEqual(self.card_updates("c1")[-1]["decided_by"], "train:MERGED")

    def test_resolve_tasks_batched_into_single_query(self):
        """_resolve_task's old per-card db.select("tasks", {"slug": "eq.<slug>"}) call was one
        network round-trip per card; with thousands of eligible cards per cycle that stalled
        every train invocation. Verify train_run() now issues one batched tasks query
        (slug=in.(...)) covering every candidate card instead of N separate eq. queries."""
        self.cards = [_card("c1", "feat-x"), _card("c2", "feat-y")]
        self.tasks = [_task("t1", "feat-x"), _task("t2", "feat-y", project_id="p2")]
        tasks_selects = []
        real_select = self._select

        def counting_select(table, params=None):
            if table == "tasks":
                tasks_selects.append(params)
            return real_select(table, params)

        self.mock_db.select.side_effect = counting_select
        summary = merge_train.train_run()
        self.assertEqual(summary["merged"], 2)
        self.assertEqual(len(tasks_selects), 1, "expected exactly one batched tasks query, not one per card")
        self.assertTrue(tasks_selects[0]["slug"].startswith("in.("))


# ── G: branch-missing recovery ───────────────────────────────────────────────

class TestBranchMissing(TrainCase):

    def test_running_task_waits_without_consuming_approved_card(self):
        self.cards = [_card("c1", "feat-x")]
        self.tasks = [_task("t1", "feat-x", state="RUNNING")]
        self.mocks["_branch_exists"].return_value = False
        summary = merge_train.train_run()
        self.assertEqual(summary["skipped"], 1)
        self.assertEqual(self.task_updates("t1"), [])
        self.assertEqual(self.card_updates("c1"), [])
        self.mocks["_rebase_onto_base"].assert_not_called()

    def test_blocked_task_with_missing_branch_requeues_without_consuming_card(self):
        self.cards = [_card("c1", "feat-x")]
        self.tasks = [_task("t1", "feat-x", state="BLOCKED", retries=0)]
        self.mocks["_branch_exists"].return_value = False
        with patch.dict(os.environ, {"MERGE_BRANCH_MISSING_REDO_CAP": "2"}):
            summary = merge_train.train_run()
        self.assertEqual(summary["redo"], 1)
        tp = self.task_updates("t1")[-1]
        self.assertEqual(tp["state"], "QUEUED")
        self.assertEqual(tp["transient_retries"], 1)
        self.assertEqual(self.card_updates("c1"), [])
        self.mocks["_rebase_onto_base"].assert_not_called()


# ── C/D: rebase-conflict redo pattern ─────────────────────────────────────────

class TestConflictRedo(TrainCase):

    def test_conflict_under_cap_requeues(self):
        self.cards = [_card("c1", "feat-x")]
        self.tasks = [_task("t1", "feat-x", retries=0)]
        self.mocks["_rebase_onto_base"].return_value = False
        with patch.dict(os.environ, {"MERGE_CONFLICT_REDO_CAP": "2"}):
            summary = merge_train.train_run()
        self.assertEqual(summary["redo"], 1)
        tp = self.task_updates("t1")[-1]
        self.assertEqual(tp["state"], "QUEUED")
        self.assertEqual(tp["transient_retries"], 1)
        self.assertEqual(self.card_updates("c1")[-1]["decided_by"], "train:redo")
        self.mocks["_delete_branch"].assert_called_once()
        self.mocks["_ff_base"].assert_not_called()

    def test_conflict_past_cap_marks_conflict(self):
        self.cards = [_card("c1", "feat-x")]
        self.tasks = [_task("t1", "feat-x", retries=2)]
        self.mocks["_rebase_onto_base"].return_value = False
        with patch.dict(os.environ, {"MERGE_CONFLICT_REDO_CAP": "2"}):
            summary = merge_train.train_run()
        self.assertEqual(summary["conflict"], 1)
        self.assertEqual(self.task_updates("t1")[-1]["state"], "CONFLICT")
        self.assertEqual(self.card_updates("c1")[-1]["decided_by"], "train:conflict-exhausted")
        self.mocks["_delete_branch"].assert_not_called()


# ── E: test failures never merge ──────────────────────────────────────────────

class TestTestGate(TrainCase):

    def test_testfail_never_merges(self):
        self.cards = [_card("c1", "feat-x")]
        self.tasks = [_task("t1", "feat-x")]
        self.mocks["_run_tests"].return_value = (False, "1 test failed")
        summary = merge_train.train_run()
        self.assertEqual(summary["testfail"], 1)
        self.assertEqual(summary["merged"], 0)
        self.assertEqual(self.task_updates("t1")[-1]["state"], "TESTFAIL")
        self.assertEqual(self.card_updates("c1")[-1]["decided_by"], "train:TESTFAIL")
        self.mocks["_ff_base"].assert_not_called()
        self.mocks["_push_base"].assert_not_called()


# ── F: serialization order ────────────────────────────────────────────────────

class TestSerialization(TrainCase):

    def test_oldest_first_within_project(self):
        self.cards = [_card("c2", "feat-b", created_at="2026-01-02T00:00:00"),
                      _card("c1", "feat-a", created_at="2026-01-01T00:00:00")]
        self.tasks = [_task("t1", "feat-a"), _task("t2", "feat-b")]
        order = []
        self.mocks["_rebase_onto_base"].side_effect = \
            lambda repo, branch, base: order.append(branch) or True
        summary = merge_train.train_run()
        self.assertEqual(summary["merged"], 2)
        self.assertEqual(order, ["agent/feat-a", "agent/feat-b"],
                         "train must process oldest approval first")

    def test_low_risk_batches_before_sensitive(self):
        self.cards = [_card("c1", "pricing-auth-change", kind="material", created_at="2026-01-01T00:00:00"),
                      _card("c2", "docs-cleanup", created_at="2026-01-02T00:00:00")]
        self.tasks = [_task("t1", "pricing-auth-change"),
                      {**_task("t2", "docs-cleanup"), "kind": "docs"}]
        order = []
        self.mocks["_rebase_onto_base"].side_effect = \
            lambda repo, branch, base: order.append(branch) or True
        summary = merge_train.train_run()
        self.assertEqual(summary["merged"], 2)
        self.assertEqual(order, ["agent/docs-cleanup", "agent/pricing-auth-change"])
        self.assertEqual(summary["risk"]["low"], 1)
        self.assertEqual(summary["risk"]["sensitive"], 1)

    def test_one_project_failure_does_not_block_other_project(self):
        self.cards = [_card("c1", "feat-a", created_at="2026-01-01T00:00:00"),
                      _card("c2", "feat-b", created_at="2026-01-02T00:00:00")]
        self.tasks = [_task("t1", "feat-a", project_id="p1"),
                      _task("t2", "feat-b", project_id="p2")]
        # p1's branch conflicts; p2's merges
        self.mocks["_rebase_onto_base"].side_effect = \
            lambda repo, branch, base: branch != "agent/feat-a"
        summary = merge_train.train_run()
        self.assertEqual(summary["redo"], 1)
        self.assertEqual(summary["merged"], 1)
        self.assertEqual(self.task_updates("t2")[-1]["state"], "MERGED")


# ── push gating ───────────────────────────────────────────────────────────────

class TestPushGate(unittest.TestCase):

    def test_push_disabled_by_default(self):
        with patch.dict(os.environ, {}, clear=False), \
             patch.object(merge_train, "_git") as mock_git:
            os.environ.pop("ORCH_PUSH_ON_MERGE", None)
            err = merge_train._push_base("/repo", "main")
        self.assertEqual(err, "")
        mock_git.assert_not_called()

    def test_dev_push_runs_by_default(self):
        with patch.dict(os.environ, {}, clear=False), \
             patch.object(merge_train, "_git") as mock_git:
            os.environ.pop("ORCH_PUSH_ON_DEV_MERGE", None)
            mock_git.return_value = MagicMock(returncode=0, stderr="")
            err = merge_train._push_base("/repo", "orchestrator/dev")
        self.assertEqual(err, "")
        mock_git.assert_called_once()

    def test_direct_prod_push_requires_explicit_override(self):
        with patch.dict(os.environ, {"ORCH_PUSH_ON_MERGE": "true",
                                     "ORCH_ALLOW_DIRECT_PROD_MERGE": "true"}), \
             patch.object(merge_train, "_git") as mock_git:
            mock_git.return_value = MagicMock(returncode=0, stderr="")
            err = merge_train._push_base("/repo", "main")
        self.assertEqual(err, "")
        mock_git.assert_called_once()


class TestEnsureIntegrationCard(unittest.TestCase):

    def test_creates_approved_card_once(self):
        fake = MagicMock()
        fake.select.return_value = []
        with patch.object(merge_train, "db", fake):
            created = merge_train.ensure_integration_card("alpha", "feat-x")
        self.assertTrue(created)
        fake.insert.assert_called_once()
        row = fake.insert.call_args.args[1]
        self.assertEqual(row["status"], "approved")
        self.assertEqual(row["slug"], "feat-x")
        self.assertEqual(row["title"], "merge of feat-x")

    def test_existing_live_card_is_not_duplicated(self):
        fake = MagicMock()
        fake.select.return_value = [_card("c1", "feat-x", decided_by=None)]
        with patch.object(merge_train, "db", fake):
            created = merge_train.ensure_integration_card("alpha", "feat-x")
        self.assertFalse(created)
        fake.insert.assert_not_called()

    def test_pending_existing_card_is_promoted_to_approved(self):
        fake = MagicMock()
        card = _card("c1", "feat-x", decided_by=None)
        card["status"] = "pending"
        fake.select.return_value = [card]
        with patch.object(merge_train, "db", fake):
            created = merge_train.ensure_integration_card("alpha", "feat-x")
        self.assertFalse(created)
        fake.update.assert_called_once()
        self.assertEqual(fake.update.call_args.args[2]["status"], "approved")


class TestEnsureNodeDepsCumulativeBudget(unittest.TestCase):
    """2026-07-10: a single merge_train.py process sat idle for 74+ minutes holding a repo's
    exclusive lock (blocking every other project's merges in that run) because
    _ensure_node_deps gave EVERY nested package.json its own fresh MERGE_TRAIN_NPM_TIMEOUT
    (default 600s) budget instead of one cumulative budget for the whole call."""

    def _make_repo(self, tmp, n_packages):
        repo = os.path.join(tmp, "repo")
        for i in range(n_packages):
            pkg_dir = os.path.join(repo, f"pkg{i}")
            os.makedirs(pkg_dir)
            with open(os.path.join(pkg_dir, "package.json"), "w") as f:
                f.write("{}")
        return repo

    def test_stops_installing_once_cumulative_budget_exhausted(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._make_repo(tmp, n_packages=5)
            calls = []

            def fake_run(*args, **kwargs):
                calls.append(kwargs.get("cwd"))
                return MagicMock(returncode=0)

            # Simulate time passing: first call starts the clock, budget exhausts after 2 calls.
            clock = {"t": 0.0}

            def fake_monotonic():
                clock["t"] += 250  # each check advances the clock by 250s
                return clock["t"]

            with patch.object(merge_train.subprocess, "run", side_effect=fake_run), \
                 patch.object(merge_train.time, "monotonic", side_effect=fake_monotonic), \
                 patch.dict(os.environ, {"MERGE_TRAIN_NPM_TOTAL_TIMEOUT": "900",
                                          "MERGE_TRAIN_NPM_TIMEOUT": "600"}, clear=False):
                merge_train._ensure_node_deps(repo)

            # deadline = t0 + 900 where t0 is the first monotonic() call (250); budget runs out
            # partway through the 5 packages, so not all 5 should have been installed.
            self.assertLess(len(calls), 5)
            self.assertGreater(len(calls), 0)

    def test_a_single_hung_install_does_not_block_remaining_packages_forever(self):
        """One nested package's install can still individually time out; the loop must move
        on to the next package rather than treating that as fatal."""
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._make_repo(tmp, n_packages=2)
            calls = []

            def fake_run(*args, **kwargs):
                calls.append(kwargs.get("cwd"))
                if len(calls) == 1:
                    raise subprocess.TimeoutExpired(cmd="npm install", timeout=600)
                return MagicMock(returncode=0)

            with patch.object(merge_train.subprocess, "run", side_effect=fake_run), \
                 patch.dict(os.environ, {"MERGE_TRAIN_NPM_TOTAL_TIMEOUT": "900",
                                          "MERGE_TRAIN_NPM_TIMEOUT": "600"}, clear=False):
                merge_train._ensure_node_deps(repo)

            self.assertEqual(len(calls), 2)

    def test_single_package_repo_still_gets_installed(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._make_repo(tmp, n_packages=1)
            calls = []

            def fake_run(*args, **kwargs):
                calls.append(kwargs.get("cwd"))
                return MagicMock(returncode=0)

            with patch.object(merge_train.subprocess, "run", side_effect=fake_run):
                merge_train._ensure_node_deps(repo)

            self.assertEqual(len(calls), 1)


class TestMergeRiskClassification(unittest.TestCase):
    def test_injected_security_boilerplate_does_not_make_normal_task_sensitive(self):
        task = _task("t1", "ordinary-dashboard")
        task["prompt"] = "Fleet rules: never commit secrets; auth must fail closed; comply with privacy rules. Build dashboard."
        task["note"] = "tests mention oauth dependency"
        self.assertEqual(merge_train._risk_level(_card("c1", task["slug"]), task), "standard")

    def test_task_identity_and_material_flag_remain_fail_closed(self):
        task = _task("t1", "stripe-payment-auth")
        self.assertEqual(merge_train._risk_level(_card("c1", task["slug"]), task), "sensitive")
        ordinary = _task("t2", "ordinary-dashboard")
        ordinary["material"] = True
        self.assertEqual(merge_train._risk_level(_card("c2", ordinary["slug"]), ordinary), "sensitive")


class TestBranchExactQA(unittest.TestCase):
    def test_integrate_tests_rebased_branch_not_primary_checkout(self):
        source = open(merge_train.__file__, encoding="utf-8").read()
        self.assertIn("_verified_or_run(repo, candidate_sha, test_cmd)", source)
        self.assertIn("_run_tests(repo, test_cmd, base)", source)

    def test_exact_commit_verification_is_reused(self):
        proof = MagicMock(); proof.reusable_verification.return_value = {"success": True}
        with patch.dict("sys.modules", {"proof_graph": proof}), patch.object(merge_train, "_run_tests") as run:
            ok, note = merge_train._verified_or_run("/repo", "a" * 40, "npm test")
        self.assertTrue(ok); self.assertIn("reused exact", note); run.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
