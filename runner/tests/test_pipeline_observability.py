"""
test_pipeline_observability.py - verifies test pipeline metrics collection,
health query aggregation by task type, and merge train summary enrichment.

Acceptance: can query test pipeline health with per-task-type pass rates;
pipeline metrics match actual task transitions; merge train summary includes
test-pipeline impact.
"""
import contextlib
import os, subprocess, sys, tempfile, unittest
from unittest.mock import patch, MagicMock, ANY

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pipeline_metrics
import merge_train


# ── pipeline_metrics.record ───────────────────────────────────────────────────

class TestRecord(unittest.TestCase):

    def test_inserts_correct_row(self):
        mock_db = MagicMock()
        with patch.object(pipeline_metrics, "db", mock_db):
            pipeline_metrics.record("feat-x", "integrate", ok=True,
                                    duration_ms=1200, gate_decision="MERGED")
        mock_db.insert.assert_called_once()
        row = mock_db.insert.call_args.args[1]
        self.assertEqual(row["slug"], "feat-x")
        self.assertEqual(row["task_type"], "integrate")
        self.assertTrue(row["passed"])
        self.assertEqual(row["duration_ms"], 1200)
        self.assertEqual(row["gate_decision"], "MERGED")
        self.assertIn("recorded_at", row)

    def test_fails_soft_on_db_error(self):
        mock_db = MagicMock()
        mock_db.insert.side_effect = Exception("DB down")
        with patch.object(pipeline_metrics, "db", mock_db):
            # must not raise
            pipeline_metrics.record("feat-x", "integrate", ok=True,
                                    duration_ms=500, gate_decision="MERGED")

    def test_none_task_type_stored_as_unknown(self):
        mock_db = MagicMock()
        with patch.object(pipeline_metrics, "db", mock_db):
            pipeline_metrics.record("feat-x", None, ok=False,
                                    duration_ms=0, gate_decision="TESTFAIL")
        row = mock_db.insert.call_args.args[1]
        self.assertEqual(row["task_type"], "unknown")

    def test_gate_reason_truncated_to_500(self):
        mock_db = MagicMock()
        with patch.object(pipeline_metrics, "db", mock_db):
            pipeline_metrics.record("s", "t", ok=False, duration_ms=0,
                                    gate_decision="TESTFAIL", gate_reason="x" * 600)
        row = mock_db.insert.call_args.args[1]
        self.assertEqual(len(row["gate_reason"]), 500)


# ── pipeline_metrics.get_health ───────────────────────────────────────────────

class TestGetHealth(unittest.TestCase):

    def _rows(self, *entries):
        return [{"task_type": tt, "passed": p, "duration_ms": d, "gate_decision": gd,
                 "recorded_at": "2026-07-09T10:00:00"}
                for tt, p, d, gd in entries]

    def test_pass_rate_by_task_type(self):
        mock_db = MagicMock()
        mock_db.select.return_value = self._rows(
            ("integrate", True,  1000, "MERGED"),
            ("integrate", True,  1200, "MERGED"),
            ("integrate", False,  800, "TESTFAIL"),
            ("verify",    True,   500, "MERGED"),
        )
        with patch.object(pipeline_metrics, "db", mock_db):
            result = pipeline_metrics.get_health(lookback_minutes=60)
        by_type = result["by_task_type"]
        self.assertIn("integrate", by_type)
        self.assertIn("verify", by_type)
        self.assertEqual(by_type["integrate"]["total"], 3)
        self.assertEqual(by_type["integrate"]["passed"], 2)
        self.assertEqual(by_type["integrate"]["failed"], 1)
        self.assertAlmostEqual(by_type["integrate"]["pass_rate"], 0.667, places=2)
        self.assertEqual(by_type["verify"]["pass_rate"], 1.0)

    def test_avg_duration_computed_per_type(self):
        mock_db = MagicMock()
        mock_db.select.return_value = self._rows(
            ("integrate", True,  1000, "MERGED"),
            ("integrate", False, 2000, "TESTFAIL"),
        )
        with patch.object(pipeline_metrics, "db", mock_db):
            result = pipeline_metrics.get_health()
        self.assertEqual(result["by_task_type"]["integrate"]["avg_duration_ms"], 1500)

    def test_gate_decisions_counted(self):
        mock_db = MagicMock()
        mock_db.select.return_value = self._rows(
            ("integrate", True,  1000, "MERGED"),
            ("integrate", True,  1000, "MERGED"),
            ("integrate", False,  800, "TESTFAIL"),
        )
        with patch.object(pipeline_metrics, "db", mock_db):
            result = pipeline_metrics.get_health()
        gd = result["by_task_type"]["integrate"]["gate_decisions"]
        self.assertEqual(gd["MERGED"], 2)
        self.assertEqual(gd["TESTFAIL"], 1)

    def test_task_type_filter_passed_to_db(self):
        mock_db = MagicMock()
        mock_db.select.return_value = self._rows(("verify", True, 500, "MERGED"))
        with patch.object(pipeline_metrics, "db", mock_db):
            pipeline_metrics.get_health(lookback_minutes=30, task_type="verify")
        params = mock_db.select.call_args.args[1]
        self.assertEqual(params.get("task_type"), "eq.verify")

    def test_empty_db_returns_empty_by_task_type(self):
        mock_db = MagicMock()
        mock_db.select.return_value = []
        with patch.object(pipeline_metrics, "db", mock_db):
            result = pipeline_metrics.get_health()
        self.assertEqual(result["by_task_type"], {})
        self.assertEqual(result["lookback_minutes"], 60)

    def test_db_error_returns_empty(self):
        mock_db = MagicMock()
        mock_db.select.side_effect = Exception("DB unreachable")
        with patch.object(pipeline_metrics, "db", mock_db):
            result = pipeline_metrics.get_health()
        self.assertEqual(result["by_task_type"], {})


# ── merge train + pipeline_metrics integration ────────────────────────────────

def _init_repo(path):
    """A REAL git repo with the base and one agent branch.

    merge_train's git helpers are stubbed here, but the collaborators it grew
    since these tests were written are not — regression_guard runs an actual
    `git diff orchestrator/dev..agent/<slug>` and reported REGRESSFAIL for every
    card when handed an empty directory. Six git commands buy back the fidelity
    that stubbing each new collaborator one at a time would keep costing.
    """
    def git(*args):
        subprocess.run(["git", "-C", path] + list(args),
                       capture_output=True, timeout=30, check=False)
    git("init", "-q", "-b", "orchestrator/dev")
    git("config", "user.email", "t@t")
    git("config", "user.name", "t")
    open(os.path.join(path, "README"), "w").write("base\n")
    git("add", "-A")
    git("commit", "-q", "-m", "base")
    # The agent branch must be genuinely AHEAD of the base. Branched at the same
    # commit, merge_train correctly reports "ALREADY (present in
    # orchestrator/dev; no ref advance)" and never reaches the merge it is being
    # asked to record a metric for.
    git("checkout", "-q", "-b", "agent/feat-x")
    open(os.path.join(path, "feature.txt"), "w").write("work\n")
    git("add", "-A")
    git("commit", "-q", "-m", "feat-x")
    git("checkout", "-q", "orchestrator/dev")


@contextlib.contextmanager
def _in_place_repo(repo_path, _owner, *a, **kw):
    """Stand-in for integration_runtime.isolated_repo: no worktree, same path."""
    yield repo_path


PROJECTS_DATA = [{"id": "p1", "name": "alpha", "repo_path": "/tmp/fake-repo",
                  "default_base": "main", "test_cmd": "true"}]


class MergeTrainMetricsCase(unittest.TestCase):
    """Shared harness: mocked db + git helpers, real merge_train logic."""

    def setUp(self):
        self.updates = []
        self.cards = []
        self.tasks = []
        # A REAL directory. The pass touches the repo path on disk before any of
        # the git helpers below are reached, so a nonexistent "/tmp/fake-repo"
        # raised FileNotFoundError and every card was skipped as
        # "worktree-vanished: transient" — a pass that reported 0 merged for a
        # reason that had nothing to do with what these tests assert.
        self._repo = tempfile.TemporaryDirectory()
        self.addCleanup(self._repo.cleanup)
        self.repo_path = self._repo.name
        _init_repo(self.repo_path)

        self.mock_db = MagicMock()
        self.mock_db.select.side_effect = self._select
        # select_all() must be a real function too. As a bare MagicMock it returned
        # a MagicMock, merge_train saw "not a list", printed "paged approval scan
        # unavailable ... degrading to a bounded dual-order window" and took its
        # FALLBACK path — so these tests were measuring the degraded scan, not the
        # one the train actually uses.
        self.mock_db.select_all.side_effect = \
            lambda table, params=None, **kw: self._select(table, params)
        self.mock_db.update.side_effect = \
            lambda table, match, patch: self.updates.append((table, match, patch))
        # A MagicMock here becomes a path segment: the real function returns the
        # repo path, localized to this machine's home when it needs to be.
        self.mock_db.localize_repo_path.side_effect = lambda p: p

        # The production build gate is fail-CLOSED by design: with no build_cmd
        # it returns "no production build command could be determined for this
        # repo" rather than skipping, so every card in a fixture repo is
        # BUILDFAIL. Use the gate's own documented opt-out rather than patching
        # an internal — what is under test here is the metric recording.
        patches = [
            patch.dict(os.environ, {"ORCH_MERGE_BUILD_GATE": "false"}, clear=False),
            patch.object(merge_train, "db", self.mock_db),
            patch.object(merge_train, "_branch_exists", return_value=True),
            patch.object(merge_train, "_refresh_base", return_value=None),
            # (ok, conflict_detail), not a bool: _rebase_onto_base returns the
            # newline-separated conflicting filenames alongside the verdict so a
            # repair directive can name them. Stubbed as a bare True, the caller's
            # unpack raised "cannot unpack non-iterable bool object", merge_train
            # counted a PROJECT-ERROR, and all five tests saw 0 merged.
            patch.object(merge_train, "_rebase_onto_base", return_value=(True, "")),
            patch.object(merge_train, "_run_tests", return_value=(True, "green")),
            patch.object(merge_train, "_ff_base", return_value=True),
            patch.object(merge_train, "_push_base", return_value=""),
            # _push_base is stubbed, so nothing reaches an origin — and _verify_push
            # then compares local `base` against `origin/base` and reports
            # PUSH-VERIFY-FAILED. That guard exists because a push returning 0 while
            # origin did not move desynced the DB from GitHub; it is real, and it is
            # not what these tests measure. "" is its success value.
            patch.object(merge_train, "_verify_push", return_value=""),
            patch.object(merge_train, "_delete_branch", return_value=None),
            patch.object(merge_train.approval_merge, "_free_branch", return_value=None),
            patch.object(merge_train, "_paused", return_value=False),
            patch.object(merge_train.os.path, "isdir", return_value=True),
            # merge_train runs each card inside an integration_runtime worktree
            # now. Unstubbed, isolated_repo() built a real path out of the
            # MagicMock db — ".../MagicMock/mock.localize_repo_path()/4449048272"
            # — which does not exist, so every card was skipped as
            # "worktree-vanished: transient" and the pass reported 0 merged. The
            # worktree is not what these tests are about; yield the repo in place.
            patch.object(merge_train.integration_runtime, "isolated_repo",
                         _in_place_repo),
        ]
        self.mocks = {}
        for p in patches:
            m = p.start()
            self.addCleanup(p.stop)
            name = getattr(p, "attribute", None)
            if name:
                self.mocks[name] = m

    @staticmethod
    def _slugs_in(params):
        """Slugs named by a PostgREST filter, for `eq.` and `in.(...)` alike.

        This used to be `params.get("slug", "eq.").split("eq.", 1)[1]`, which
        assumes the filter is always an equality. merge_train batches its task
        lookup — `slug=in.(feat-x)` — so the split found no "eq." and raised
        IndexError, and all five metric tests died inside the fake rather than in
        the code under test. A fake that only understands one operator fails the
        moment the caller reasonably uses another.
        """
        raw = str((params or {}).get("slug") or "")
        if raw.startswith("in.("):
            return [p.strip().strip('"') for p in raw[4:].rstrip(")").split(",") if p.strip()]
        if raw.startswith("eq."):
            return [raw[3:]]
        return []

    def _select(self, table, params=None):
        if table == "approvals":
            return list(self.cards)
        if table == "projects":
            return [dict(p, repo_path=self.repo_path) for p in PROJECTS_DATA]
        if table == "tasks":
            wanted = self._slugs_in(params)
            if not wanted:
                return list(self.tasks)
            return [t for t in self.tasks if t["slug"] in wanted]
        if table == "controls":
            return []
        return []

    def _card(self, cid, slug, kind="integrate"):
        return {"id": cid, "slug": slug, "kind": kind, "status": "approved",
                "decided_by": None, "created_at": "2026-01-01T00:00:00",
                "title": f"merge of {slug}"}

    def _task(self, tid, slug, kind="integrate"):
        return {"id": tid, "slug": slug, "project_id": "p1", "state": "BLOCKED",
                "transient_retries": 0, "base_branch": None, "kind": kind}


class TestMergeTrainRecordsMetrics(MergeTrainMetricsCase):

    def test_records_merged_metric_on_clean_merge(self):
        mock_pm = MagicMock()
        self.cards = [self._card("c1", "feat-x")]
        self.tasks = [self._task("t1", "feat-x", kind="integrate")]
        with patch.object(merge_train, "_pm", mock_pm):
            summary = merge_train.train_run()
        self.assertEqual(summary["merged"], 1)
        mock_pm.record.assert_called_once_with(
            "feat-x", "integrate",
            ok=True, duration_ms=ANY, gate_decision="MERGED"
        )

    def test_records_testfail_metric_on_test_failure(self):
        self.mocks["_run_tests"].return_value = (False, "3 tests failed")
        mock_pm = MagicMock()
        self.cards = [self._card("c1", "feat-x")]
        self.tasks = [self._task("t1", "feat-x", kind="verify")]
        with patch.object(merge_train, "_pm", mock_pm):
            summary = merge_train.train_run()
        self.assertEqual(summary["testfail"], 1)
        mock_pm.record.assert_called_once_with(
            "feat-x", "verify",
            ok=False, duration_ms=ANY, gate_decision="TESTFAIL", gate_reason=ANY
        )

    def test_no_metric_on_rebase_conflict(self):
        """Conflict before tests run must not record a test metric."""
        self.mocks["_rebase_onto_base"].return_value = (False, "src/app.ts")
        mock_pm = MagicMock()
        self.cards = [self._card("c1", "feat-x")]
        self.tasks = [self._task("t1", "feat-x")]
        with patch.dict(os.environ, {"MERGE_CONFLICT_REDO_CAP": "2"}), \
             patch.object(merge_train, "_pm", mock_pm):
            summary = merge_train.train_run()
        self.assertEqual(summary["redo"], 1)
        mock_pm.record.assert_not_called()

    def test_task_type_in_metric_matches_task_kind(self):
        mock_pm = MagicMock()
        self.cards = [self._card("c1", "docs-cleanup")]
        self.tasks = [self._task("t1", "docs-cleanup", kind="docs")]
        with patch.object(merge_train, "_pm", mock_pm):
            merge_train.train_run()
        self.assertEqual(mock_pm.record.call_args.args[1], "docs")

    def test_summary_includes_test_pipeline_health(self):
        health_data = {"lookback_minutes": 60, "by_task_type": {
            "integrate": {"total": 1, "passed": 1, "failed": 0, "pass_rate": 1.0,
                          "avg_duration_ms": 500, "gate_decisions": {"MERGED": 1}}
        }}
        mock_pm = MagicMock()
        mock_pm.get_health.return_value = health_data
        self.cards = [self._card("c1", "feat-x")]
        self.tasks = [self._task("t1", "feat-x")]
        with patch.object(merge_train, "_pm", mock_pm):
            summary = merge_train.train_run()
        self.assertIn("test_pipeline", summary)
        self.assertEqual(
            summary["test_pipeline"]["by_task_type"]["integrate"]["pass_rate"], 1.0
        )


# ── acceptance: query health with task type breakdown ─────────────────────────

class TestQueryPipelineHealthWithTaskTypeBreakdown(unittest.TestCase):
    """Simulate multiple pipeline runs, verify per-task-type aggregation."""

    def test_per_task_type_pass_rates_and_durations(self):
        mock_db = MagicMock()
        mock_db.select.return_value = [
            {"task_type": "unit",        "passed": True,  "duration_ms": 800,
             "gate_decision": "MERGED",   "recorded_at": "2026-07-09T10:00:00"},
            {"task_type": "unit",        "passed": True,  "duration_ms": 900,
             "gate_decision": "MERGED",   "recorded_at": "2026-07-09T10:01:00"},
            {"task_type": "unit",        "passed": False, "duration_ms": 600,
             "gate_decision": "TESTFAIL", "recorded_at": "2026-07-09T10:02:00"},
            {"task_type": "integration", "passed": True,  "duration_ms": 2000,
             "gate_decision": "MERGED",   "recorded_at": "2026-07-09T10:03:00"},
            {"task_type": "integration", "passed": False, "duration_ms": 1800,
             "gate_decision": "TESTFAIL", "recorded_at": "2026-07-09T10:04:00"},
        ]
        with patch.object(pipeline_metrics, "db", mock_db):
            result = pipeline_metrics.get_health(lookback_minutes=60)

        self.assertIn("unit", result["by_task_type"])
        self.assertIn("integration", result["by_task_type"])

        unit = result["by_task_type"]["unit"]
        self.assertEqual(unit["total"], 3)
        self.assertEqual(unit["passed"], 2)
        self.assertEqual(unit["failed"], 1)
        self.assertAlmostEqual(unit["pass_rate"], 0.667, places=2)
        self.assertEqual(unit["avg_duration_ms"], round((800 + 900 + 600) / 3))

        integration = result["by_task_type"]["integration"]
        self.assertEqual(integration["total"], 2)
        self.assertEqual(integration["pass_rate"], 0.5)
        self.assertEqual(integration["avg_duration_ms"], 1900)

    def test_merge_train_impact_reflects_test_pipeline_metrics(self):
        """Merge train summary's test_pipeline field reflects what get_health returns."""
        mock_db = MagicMock()
        mock_db.select.return_value = [
            {"task_type": "integrate", "passed": False, "duration_ms": 1200,
             "gate_decision": "TESTFAIL", "recorded_at": "2026-07-09T10:00:00"},
        ]
        with patch.object(pipeline_metrics, "db", mock_db):
            health = pipeline_metrics.get_health(lookback_minutes=60)

        self.assertEqual(health["by_task_type"]["integrate"]["pass_rate"], 0.0)
        self.assertEqual(health["by_task_type"]["integrate"]["gate_decisions"]["TESTFAIL"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
