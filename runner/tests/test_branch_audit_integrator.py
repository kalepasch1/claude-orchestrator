#!/usr/bin/env python3
"""Tests for branch_audit_integrator.py"""
import os, sys, unittest, tempfile, subprocess
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from branch_audit_integrator import (
    RiskConfig, BranchHealth, ReviewVerdict,
    BranchAuditResult, FleetHealthSummary,
    audit_branch, audit_fleet, format_report,
    _touches_sensitive, _compute_verdict,
)


class TestRiskConfig(unittest.TestCase):
    def test_defaults(self):
        cfg = RiskConfig()
        self.assertEqual(cfg.stale_days, 7)
        self.assertEqual(cfg.max_files, 20)
        self.assertEqual(cfg.max_lines, 500)
        self.assertIn("*/pricing*", cfg.sensitive_globs)

    def test_from_env(self):
        os.environ["ORCH_AUDIT_STALE_DAYS"] = "14"
        os.environ["ORCH_RISK_MAX_FILES"] = "10"
        try:
            cfg = RiskConfig.from_env()
            self.assertEqual(cfg.stale_days, 14)
            self.assertEqual(cfg.max_files, 10)
        finally:
            del os.environ["ORCH_AUDIT_STALE_DAYS"]
            del os.environ["ORCH_RISK_MAX_FILES"]

    def test_from_env_custom_globs(self):
        os.environ["ORCH_RISK_SENSITIVE_GLOB"] = "*.secret,config/*"
        try:
            cfg = RiskConfig.from_env()
            self.assertEqual(cfg.sensitive_globs, ["*.secret", "config/*"])
        finally:
            del os.environ["ORCH_RISK_SENSITIVE_GLOB"]


class TestTouchesSensitive(unittest.TestCase):
    def test_match(self):
        self.assertTrue(_touches_sensitive(
            ["server/pricing/rates.py"], ["*/pricing*"]
        ))

    def test_no_match(self):
        self.assertFalse(_touches_sensitive(
            ["server/utils/math.py"], ["*/pricing*", "*/auth*"]
        ))

    def test_empty(self):
        self.assertFalse(_touches_sensitive([], ["*/pricing*"]))
        self.assertFalse(_touches_sensitive(["foo.py"], []))


class TestComputeVerdict(unittest.TestCase):
    def _make(self, **kw):
        r = BranchAuditResult(name="test-branch")
        for k, v in kw.items():
            setattr(r, k, v)
        return r

    def test_conflicting_blocks(self):
        r = self._make(health=BranchHealth.CONFLICTING)
        v = _compute_verdict(r, RiskConfig())
        self.assertEqual(v, ReviewVerdict.BLOCK)

    def test_orphan_blocks(self):
        r = self._make(health=BranchHealth.ORPHAN)
        v = _compute_verdict(r, RiskConfig())
        self.assertEqual(v, ReviewVerdict.BLOCK)

    def test_sensitive_needs_human(self):
        r = self._make(health=BranchHealth.HEALTHY, touches_sensitive=True)
        v = _compute_verdict(r, RiskConfig())
        self.assertEqual(v, ReviewVerdict.HUMAN_REVIEW)

    def test_too_many_files_needs_human(self):
        r = self._make(health=BranchHealth.HEALTHY, files_changed=25)
        v = _compute_verdict(r, RiskConfig())
        self.assertEqual(v, ReviewVerdict.HUMAN_REVIEW)

    def test_too_many_lines_needs_human(self):
        r = self._make(health=BranchHealth.HEALTHY, lines_changed=600)
        v = _compute_verdict(r, RiskConfig())
        self.assertEqual(v, ReviewVerdict.HUMAN_REVIEW)

    def test_stale_needs_human(self):
        r = self._make(health=BranchHealth.STALE)
        v = _compute_verdict(r, RiskConfig())
        self.assertEqual(v, ReviewVerdict.HUMAN_REVIEW)

    def test_clean_auto_approves(self):
        r = self._make(
            health=BranchHealth.HEALTHY,
            files_changed=3, lines_changed=50,
            touches_sensitive=False,
        )
        v = _compute_verdict(r, RiskConfig())
        self.assertEqual(v, ReviewVerdict.AUTO_APPROVE)

    def test_custom_thresholds(self):
        cfg = RiskConfig(max_files=5, max_lines=100)
        r = self._make(health=BranchHealth.HEALTHY, files_changed=6)
        self.assertEqual(_compute_verdict(r, cfg), ReviewVerdict.HUMAN_REVIEW)
        r2 = self._make(health=BranchHealth.HEALTHY, files_changed=4, lines_changed=50)
        self.assertEqual(_compute_verdict(r2, cfg), ReviewVerdict.AUTO_APPROVE)


class TestAuditBranchWithRealGit(unittest.TestCase):
    """Integration tests using a real temporary git repo."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        subprocess.run(["git", "init"], cwd=self.tmpdir, capture_output=True)
        subprocess.run(["git", "checkout", "-b", "master"], cwd=self.tmpdir, capture_output=True)
        # Initial commit
        with open(os.path.join(self.tmpdir, "README.md"), "w") as f:
            f.write("# test\n")
        subprocess.run(["git", "add", "."], cwd=self.tmpdir, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=self.tmpdir, capture_output=True)
        # Create agent branch
        subprocess.run(["git", "checkout", "-b", "agent/test-task"], cwd=self.tmpdir, capture_output=True)
        with open(os.path.join(self.tmpdir, "feature.py"), "w") as f:
            f.write("print('hello')\n")
        subprocess.run(["git", "add", "."], cwd=self.tmpdir, capture_output=True)
        subprocess.run(["git", "commit", "-m", "add feature"], cwd=self.tmpdir, capture_output=True)
        subprocess.run(["git", "checkout", "master"], cwd=self.tmpdir, capture_output=True)

    def test_healthy_branch(self):
        r = audit_branch(
            self.tmpdir, "agent/test-task",
            task_slugs={"test-task"}, base="master",
        )
        self.assertEqual(r.name, "agent/test-task")
        self.assertEqual(r.health, BranchHealth.HEALTHY)
        self.assertTrue(r.has_task)
        self.assertEqual(r.files_changed, 1)
        self.assertEqual(r.review_verdict, ReviewVerdict.AUTO_APPROVE)

    def test_orphan_detection(self):
        r = audit_branch(
            self.tmpdir, "agent/test-task",
            task_slugs={"other-task"}, base="master",
        )
        self.assertEqual(r.health, BranchHealth.ORPHAN)
        self.assertFalse(r.has_task)
        self.assertEqual(r.review_verdict, ReviewVerdict.BLOCK)

    def test_merged_branch(self):
        subprocess.run(["git", "merge", "agent/test-task"], cwd=self.tmpdir, capture_output=True)
        r = audit_branch(self.tmpdir, "agent/test-task", base="master")
        self.assertEqual(r.health, BranchHealth.MERGED)
        self.assertEqual(r.review_verdict, ReviewVerdict.AUTO_APPROVE)

    def test_sensitive_path_detection(self):
        subprocess.run(["git", "checkout", "agent/test-task"], cwd=self.tmpdir, capture_output=True)
        os.makedirs(os.path.join(self.tmpdir, "server"), exist_ok=True)
        with open(os.path.join(self.tmpdir, "server", "pricing_rates.py"), "w") as f:
            f.write("RATE = 0.05\n")
        subprocess.run(["git", "add", "."], cwd=self.tmpdir, capture_output=True)
        subprocess.run(["git", "commit", "-m", "add pricing"], cwd=self.tmpdir, capture_output=True)
        subprocess.run(["git", "checkout", "master"], cwd=self.tmpdir, capture_output=True)
        r = audit_branch(self.tmpdir, "agent/test-task", base="master")
        self.assertTrue(r.touches_sensitive)
        self.assertEqual(r.review_verdict, ReviewVerdict.HUMAN_REVIEW)


class TestFleetAudit(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        subprocess.run(["git", "init"], cwd=self.tmpdir, capture_output=True)
        subprocess.run(["git", "checkout", "-b", "master"], cwd=self.tmpdir, capture_output=True)
        with open(os.path.join(self.tmpdir, "README.md"), "w") as f:
            f.write("# test\n")
        subprocess.run(["git", "add", "."], cwd=self.tmpdir, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=self.tmpdir, capture_output=True)
        # Create two agent branches
        for name in ("agent/task-a", "agent/task-b"):
            subprocess.run(["git", "checkout", "-b", name], cwd=self.tmpdir, capture_output=True)
            with open(os.path.join(self.tmpdir, f"{name.split('/')[-1]}.py"), "w") as f:
                f.write(f"# {name}\n")
            subprocess.run(["git", "add", "."], cwd=self.tmpdir, capture_output=True)
            subprocess.run(["git", "commit", "-m", f"add {name}"], cwd=self.tmpdir, capture_output=True)
            subprocess.run(["git", "checkout", "master"], cwd=self.tmpdir, capture_output=True)

    def test_fleet_counts(self):
        results, summary = audit_fleet(
            self.tmpdir, task_slugs={"task-a", "task-b"}, base="master",
        )
        self.assertEqual(summary.total, 2)
        self.assertEqual(summary.healthy, 2)
        self.assertEqual(summary.auto_approvable, 2)

    def test_fleet_with_orphan(self):
        results, summary = audit_fleet(
            self.tmpdir, task_slugs={"task-a"}, base="master",
        )
        self.assertEqual(summary.total, 2)
        self.assertEqual(summary.orphan, 1)
        self.assertEqual(summary.blocked, 1)


class TestFormatReport(unittest.TestCase):
    def test_format_nonempty(self):
        results = [
            BranchAuditResult(
                name="agent/foo", health=BranchHealth.HEALTHY,
                age_days=1, files_changed=2, lines_changed=30,
                review_verdict=ReviewVerdict.AUTO_APPROVE, reasons=["clean"],
            ),
            BranchAuditResult(
                name="agent/bar", health=BranchHealth.STALE,
                age_days=14, files_changed=5, lines_changed=100,
                review_verdict=ReviewVerdict.HUMAN_REVIEW, reasons=["stale"],
            ),
        ]
        summary = FleetHealthSummary(
            total=2, healthy=1, stale=1,
            auto_approvable=1, needs_human=1,
            timestamp="2026-07-15T00:00:00+00:00",
        )
        report = format_report(results, summary)
        self.assertIn("Total: 2", report)
        self.assertIn("agent/foo", report)
        self.assertIn("agent/bar", report)
        self.assertIn("HUMAN_REVIEW", report)
        self.assertIn("AUTO_APPROVE", report)


if __name__ == "__main__":
    unittest.main()
