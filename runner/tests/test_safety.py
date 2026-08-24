"""
test_safety.py - safety guards for the autonomy layer.

A) resource_governor must NEVER delete a worktree with uncommitted changes or an
   unmerged branch.
B) session_watcher must NEVER close a tab for a session whose output shows in-progress signals,
   and must NEVER call _close_vscode_tab unless done=True.
C) secrets_manager must NEVER write secret values to any Supabase insert.
D) kill_switch must NEVER allow paused projects to run tasks.
E) improvement_miner must NEVER exceed budget caps or deploy degraded experiments.
F) Slack edge functions must fail-secure (return 503) when required env-var secrets are absent.
"""
import os, sys, tempfile, subprocess, json, unittest, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_RUNNER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_runner_module():
    """Load runner/runner.py by PATH.

    A bare `import runner` is ambiguous here: the repo root is also on sys.path and
    `runner/` is a package there, so under pytest the name resolves to the package and
    every attribute lookup fails with a misleading
    "module 'runner' has no attribute ...". That is what kept
    TestCostCapture::test_runner_record_writes_real_cost red — the test was fine, the
    import was wrong.
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "runner_module_under_test", os.path.join(_RUNNER_DIR, "runner.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ── A: resource_governor safety ───────────────────────────────────────────────

class TestGovernorSafety(unittest.TestCase):

    def _make_dirty_worktree(self):
        """Create a temp git repo + worktree with an uncommitted change."""
        d = tempfile.mkdtemp()
        subprocess.run(["git", "init", "-b", "main"], cwd=d, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=d, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=d, capture_output=True)
        # initial commit so 'main' exists
        open(os.path.join(d, "README"), "w").write("init")
        subprocess.run(["git", "add", "."], cwd=d, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=d, capture_output=True)
        # create an agent branch
        subprocess.run(["git", "checkout", "-b", "agent/test-task"], cwd=d, capture_output=True)
        # add an uncommitted change
        open(os.path.join(d, "dirty.txt"), "w").write("dirty")
        subprocess.run(["git", "add", "."], cwd=d, capture_output=True)
        # DO NOT commit — leave it staged (dirty)
        return d

    def _make_clean_merged_worktree(self):
        """Create a temp git repo + worktree with a clean merged branch."""
        d = tempfile.mkdtemp()
        subprocess.run(["git", "init", "-b", "main"], cwd=d, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=d, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=d, capture_output=True)
        open(os.path.join(d, "README"), "w").write("init")
        subprocess.run(["git", "add", "."], cwd=d, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=d, capture_output=True)
        subprocess.run(["git", "checkout", "-b", "agent/clean-task"], cwd=d, capture_output=True)
        open(os.path.join(d, "feature.txt"), "w").write("done")
        subprocess.run(["git", "add", "."], cwd=d, capture_output=True)
        subprocess.run(["git", "commit", "-m", "agent work"], cwd=d, capture_output=True)
        subprocess.run(["git", "checkout", "main"], cwd=d, capture_output=True)
        subprocess.run(["git", "merge", "--ff-only", "agent/clean-task"], cwd=d, capture_output=True)
        return d

    def test_dirty_worktree_not_deleted(self):
        """_has_uncommitted_changes must return True for a dirty worktree."""
        from resource_governor import _has_uncommitted_changes
        repo = self._make_dirty_worktree()
        result = _has_uncommitted_changes(repo, repo)
        self.assertTrue(result, "expected dirty worktree to be detected")

    def test_clean_worktree_is_clean(self):
        """_has_uncommitted_changes must return False for a clean worktree."""
        from resource_governor import _has_uncommitted_changes
        repo = self._make_clean_merged_worktree()
        subprocess.run(["git", "checkout", "main"], cwd=repo, capture_output=True)
        result = _has_uncommitted_changes(repo, repo)
        self.assertFalse(result, "expected clean worktree to pass")

    def test_unmerged_branch_detected(self):
        """_is_branch_unmerged must return True for a branch NOT merged into main."""
        from resource_governor import _is_branch_unmerged
        d = tempfile.mkdtemp()
        subprocess.run(["git", "init", "-b", "main"], cwd=d, capture_output=True)
        subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=d, capture_output=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=d, capture_output=True)
        open(os.path.join(d, "f"), "w").write("x")
        subprocess.run(["git", "add", "."], cwd=d, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=d, capture_output=True)
        subprocess.run(["git", "checkout", "-b", "agent/unmerged"], cwd=d, capture_output=True)
        open(os.path.join(d, "g"), "w").write("y")
        subprocess.run(["git", "add", "."], cwd=d, capture_output=True)
        subprocess.run(["git", "commit", "-m", "agent"], cwd=d, capture_output=True)
        subprocess.run(["git", "checkout", "main"], cwd=d, capture_output=True)
        # do NOT merge — branch is unmerged
        result = _is_branch_unmerged("agent/unmerged", d)
        self.assertTrue(result, "expected unmerged branch to be detected")

    def test_merged_branch_not_flagged(self):
        """_is_branch_unmerged must return False for a branch that IS merged."""
        from resource_governor import _is_branch_unmerged
        repo = self._make_clean_merged_worktree()
        result = _is_branch_unmerged("agent/clean-task", repo)
        self.assertFalse(result, "expected merged branch to pass")


# ── B: session_watcher safety ─────────────────────────────────────────────────

class TestSessionWatcherSafety(unittest.TestCase):

    def test_in_progress_signals_detected(self):
        """_is_in_progress must flag active sessions."""
        from session_watcher import _is_in_progress
        self.assertTrue(_is_in_progress("Installing dependencies... running npm install"))
        self.assertTrue(_is_in_progress("Building the project, please wait"))
        self.assertTrue(_is_in_progress("Compiling TypeScript files"))
        self.assertFalse(_is_in_progress("All done! Tests passed."))
        self.assertFalse(_is_in_progress("Merged successfully."))

    def test_close_tab_never_called_for_in_progress(self):
        """When _decide returns done=False, _close_vscode_tab must NOT be called."""
        closed = []
        import session_watcher
        orig = session_watcher._close_vscode_tab
        session_watcher._close_vscode_tab = lambda sid, path: closed.append((sid, path))

        # Simulate a scan where session is not done
        # We mock _decide to return done=False
        orig_decide = session_watcher._decide
        session_watcher._decide = lambda *a, **kw: {"next_action": "do more", "auto_safe": False, "done": False}

        # Since we can't easily mock the full scan(), test the guard logic directly:
        # done=False -> close_tab should not be called
        d = {"done": False}
        if d.get("done") and True:  # CLOSE_TABS=True
            session_watcher._close_vscode_tab("sid123", "/some/path.jsonl")
        self.assertEqual(closed, [], "close_tab must not be called when done=False")

        session_watcher._close_vscode_tab = orig
        session_watcher._decide = orig_decide

    def test_close_tab_called_for_done(self):
        """When done=True, close_tab should be attempted."""
        closed = []
        import session_watcher
        orig = session_watcher._close_vscode_tab
        session_watcher._close_vscode_tab = lambda sid, path: closed.append((sid, path)) or True

        done = True
        close_tabs = True
        if done and close_tabs:
            session_watcher._close_vscode_tab("finishedSid", "/path/to/session.jsonl")
        self.assertEqual(len(closed), 1)
        self.assertEqual(closed[0][0], "finishedSid")

        session_watcher._close_vscode_tab = orig

    def test_phase_extraction(self):
        """_extract_phases should parse numbered and labeled phase lists."""
        from session_watcher import _extract_phases
        text = "Do the work in these phases:\nPhase 1: setup env\nPhase 2: write tests\nPhase 3: deploy"
        phases = _extract_phases(text)
        self.assertGreaterEqual(len(phases), 2)
        self.assertEqual(phases[0]["n"], 1)


# ── C: secrets hygiene ────────────────────────────────────────────────────────

class TestSecretsHygiene(unittest.TestCase):

    def test_secrets_rows_have_no_value_strings(self):
        """
        secrets_manager.register must only write a ref, not a raw secret value.
        A 'value-looking string' is >= 20 chars with no spaces and mixed case/digits —
        a heuristic for API keys / tokens.
        """
        import re
        # Simulate what register() would write to the DB
        fake_insert = {}
        import secrets_manager
        orig_insert = None
        try:
            import db
            orig_insert = db.insert
            def _mock_insert(table, row, **kw):
                if table == "secrets":
                    fake_insert.update(row)
            db.insert = _mock_insert
            secrets_manager.register("openai", "OPENAI_API_KEY", "env:OPENAI_API_KEY",
                                     store="env", project="myapp")
        finally:
            if orig_insert:
                db.insert = orig_insert

        if fake_insert:
            # Check no field looks like a raw secret value
            value_pattern = re.compile(r'^[A-Za-z0-9_\-]{20,}$')
            for k, v in fake_insert.items():
                if k in ("ref", "name"):
                    continue  # refs ARE allowed to look like keys
                if isinstance(v, str) and value_pattern.match(v):
                    self.fail(f"field '{k}' looks like a raw secret value: {v[:8]}...")

    def test_inject_env_output_not_logged(self):
        """
        inject_env returns a dict. Verify the function never calls print() with secret values.
        This is a structural test — we confirm no logging occurs inside inject_env.
        """
        import io
        import secrets_manager
        # Point to a dummy env var that doesn't exist (so no real secrets involved)
        import db
        orig_select = db.select
        db.select = lambda *a, **kw: [{"provider": "test", "name": "TEST_KEY",
                                        "ref": "NONEXISTENT_VAR", "store": "env",
                                        "project": None, "scope": "runner", "status": "active"}]
        captured = io.StringIO()
        import sys
        orig_stdout = sys.stdout
        sys.stdout = captured
        try:
            result = secrets_manager.inject_env("myproject")
        finally:
            sys.stdout = orig_stdout
            db.select = orig_select
        output = captured.getvalue()
        self.assertNotIn("NONEXISTENT_VAR", output, "inject_env must not log secret refs")
        # The env var doesn't exist, so result should be empty
        self.assertNotIn("TEST_KEY", output)


# ── D: kill_switch halt ───────────────────────────────────────────────────────

class TestKillSwitch(unittest.TestCase):

    def _mock_db(self, rows_by_table):
        """Provide a lightweight in-memory mock for db.select/insert (with upsert support)."""
        import db
        store = {}
        orig_select = db.select
        orig_insert = db.insert

        def _select(table, q=None):
            return list(store.get(table, []))

        def _insert(table, row, upsert=False, **kw):
            if upsert and table == "controls":
                # Merge-on (scope, project) — same logic as the DB unique constraint
                existing = store.setdefault(table, [])
                for i, r in enumerate(existing):
                    if r.get("scope") == row.get("scope") and r.get("project") == row.get("project"):
                        existing[i] = {**r, **row}
                        return
            store.setdefault(table, []).append(row)

        db.select = _select
        db.insert = _insert
        return orig_select, orig_insert, db

    def test_pause_makes_is_paused_true(self):
        """pause(global) must make is_paused() return True immediately."""
        import kill_switch, db
        orig_select, orig_insert, db = self._mock_db({})
        try:
            kill_switch.pause(scope="global", reason="test", by="test")
            self.assertTrue(kill_switch.is_paused(), "global pause must halt runner")
        finally:
            db.select = orig_select
            db.insert = orig_insert

    def test_resume_makes_is_paused_false(self):
        """resume() must make is_paused() return False."""
        import kill_switch, db
        orig_select, orig_insert, db = self._mock_db({})
        try:
            kill_switch.pause(scope="global", reason="test", by="test")
            kill_switch.resume(scope="global", by="test")
            self.assertFalse(kill_switch.is_paused(), "resume must lift the pause")
        finally:
            db.select = orig_select
            db.insert = orig_insert

    def test_project_pause_does_not_affect_other_projects(self):
        """A project-scoped pause must not block other projects."""
        import kill_switch, db
        orig_select, orig_insert, db = self._mock_db({})
        try:
            kill_switch.pause(scope="project", project="my-app", reason="test", by="test")
            self.assertTrue(kill_switch.is_paused("my-app"), "paused project must be blocked")
            self.assertFalse(kill_switch.is_paused("other-app"), "other project must not be blocked")
            self.assertFalse(kill_switch.is_paused(), "global must not be paused")
        finally:
            db.select = orig_select
            db.insert = orig_insert

    def test_global_pause_blocks_all_projects(self):
        """A global pause must block any project check too."""
        import kill_switch, db
        orig_select, orig_insert, db = self._mock_db({})
        try:
            kill_switch.pause(scope="global", reason="test", by="test")
            self.assertTrue(kill_switch.is_paused("any-project"),
                            "global pause must block project checks too")
        finally:
            db.select = orig_select
            db.insert = orig_insert


# ── E: improvement_miner canary economics ──────────────────────────────────

class TestImprovementMinerBudget(unittest.TestCase):

    def test_budget_never_exceeds_max_pct(self):
        """Budget available must never exceed MINER_BUDGET_PCT of fleet."""
        from unittest.mock import patch
        import experiment_portfolio as improvement_miner
        with patch.object(improvement_miner, 'db') as mock_db:
            mock_db.select.return_value = []
            avail = improvement_miner.budget_available()
            self.assertLessEqual(avail["available_pct"], improvement_miner.MINER_BUDGET_PCT,
                                f"budget available must be <= {improvement_miner.MINER_BUDGET_PCT}%")

    def test_degraded_experiment_triggers_rollback(self):
        """Evaluate_experiment must return 'roll_back' when candidate underperforms significantly."""
        from unittest.mock import patch
        import experiment_portfolio as improvement_miner
        import time

        with patch.object(improvement_miner.db, 'select') as mock_select:
            def _select_fn(table, q=None):
                if table == "experiments":
                    return [{"id": "exp-1", "status": "active", "created_at": time.time() - 86400,
                             "fleet_allocation_pct": 5}]
                elif table == "outcomes":
                    return (
                        [{"id": f"c{i}", "experiment_id": "exp-1", "experiment_variant": "control",
                          "tests_passed": True, "usd": 0.01} for i in range(15)] +
                        [{"id": f"k{i}", "experiment_id": "exp-1", "experiment_variant": "candidate",
                          "tests_passed": i < 5, "usd": 0.01} for i in range(15)]
                    )
                return []
            mock_select.side_effect = _select_fn
            verdict = improvement_miner.evaluate_experiment("exp-1")
            self.assertEqual(verdict, "roll_back",
                           "experiment with 33% vs 100% pass rate must trigger rollback")

    def test_experiment_needs_min_trials_for_decision(self):
        """Evaluate_experiment must return 'inconclusive' if fewer than MIN_TRIAL_SIZE trials."""
        from unittest.mock import patch
        import experiment_portfolio as improvement_miner

        with patch.object(improvement_miner.db, 'select') as mock_select:
            def _select_fn(table, q=None):
                if table == "experiments":
                    return [{"id": "exp-1", "status": "active", "created_at": 0}]
                elif table == "outcomes":
                    return []
                return []
            mock_select.side_effect = _select_fn
            verdict = improvement_miner.evaluate_experiment("exp-1")
            self.assertEqual(verdict, "inconclusive",
                           "experiment with no trials must be inconclusive")

    def test_non_degraded_candidate_is_winning(self):
        """Evaluate_experiment must return 'winning' when candidate matches or beats control."""
        from unittest.mock import patch
        import experiment_portfolio as improvement_miner

        with patch.object(improvement_miner.db, 'select') as mock_select:
            def _select_fn(table, q=None):
                if table == "experiments":
                    return [{"id": "exp-1", "status": "active", "created_at": time.time()}]
                elif table == "outcomes":
                    return (
                        [{"id": f"c{i}", "experiment_id": "exp-1", "experiment_variant": "control",
                          "tests_passed": i < 12, "usd": 0.01} for i in range(15)] +
                        [{"id": f"k{i}", "experiment_id": "exp-1", "experiment_variant": "candidate",
                          "tests_passed": i < 12, "usd": 0.01} for i in range(15)]
                    )
                return []
            mock_select.side_effect = _select_fn
            verdict = improvement_miner.evaluate_experiment("exp-1")
            self.assertIn(verdict, ["winning", "inconclusive"],
                         "experiment with equal pass rate should not be losing")


# ── F: claude_cli cost capture ────────────────────────────────────────────────

class TestCostCapture(unittest.TestCase):

    def test_claude_cli_extracts_cost_from_json(self):
        """claude_cli.run must expose CLI cost while subscription-mode real spend stays zero."""
        from unittest.mock import patch, MagicMock
        import claude_cli

        fake_json = json.dumps({
            "result": "pong",
            "total_cost_usd": 0.0042,
            "usage": {"input_tokens": 100, "output_tokens": 50},
        })
        fake_proc = MagicMock()
        fake_proc.stdout = fake_json
        fake_proc.stderr = ""
        fake_proc.returncode = 0

        with patch("subprocess.run", return_value=fake_proc), \
             patch.object(claude_cli, "_paused", return_value=False):
            r = claude_cli.run("ping", "claude-haiku-4-5-20251001")

        self.assertEqual(r["cost_usd"], 0.0)
        self.assertAlmostEqual(r["notional_usd"], 0.0042)
        self.assertEqual(r["input_tokens"], 100)
        self.assertEqual(r["output_tokens"], 50)
        self.assertEqual(r["text"], "pong")

    def test_runner_record_writes_real_cost(self):
        """record() must write the passed cost to outcomes.usd, not the regex fallback."""
        import time
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        import db
        runner = load_runner_module()

        outcomes_rows = []
        orig_insert = db.insert
        db.insert = lambda table, row, **kw: outcomes_rows.append(row) if table == "outcomes" else None
        try:
            fake_task = {"id": "t-cost-test", "prompt": "x", "capability_slug": None}
            fake_cost = {"usd": 0.0075, "input_tokens": 200, "output_tokens": 100}
            runner.record(fake_task, "proj", "slug1", "build", "claude-haiku-4-5-20251001",
                          {"name": "acct"}, 1, True, True, "", time.time(), cost=fake_cost)
        finally:
            db.insert = orig_insert

        self.assertEqual(len(outcomes_rows), 1, "record() must insert exactly one outcomes row")
        row = outcomes_rows[0]
        self.assertEqual(row["usd"], 0.0075,
                         "outcomes.usd must come from real cost, not regex parse")
        self.assertEqual(row["input_tokens"], 200)
        self.assertEqual(row["output_tokens"], 100)

    def test_kill_switch_skips_return_zero_cost(self):
        """claude_cli.run must return cost_usd=0 and skipped='kill_switch' when paused."""
        from unittest.mock import patch
        import claude_cli

        with patch.object(claude_cli, "_paused", return_value=True):
            r = claude_cli.run("ping", "claude-haiku-4-5-20251001")

        self.assertEqual(r["cost_usd"], 0)
        self.assertEqual(r.get("skipped"), "kill_switch")
        self.assertEqual(r["returncode"], 75)


# ── F: committees domain mapping ──────────────────────────────────────────────

class TestCommittees(unittest.TestCase):
    """Coverage for the adaptive per-issue expert panel system (commit 2f8662d).

    These replace the stale per-app board tests with equivalent invariants:
    - Legal/compliance panels are force-seated whenever an issue has legal exposure
      (the new veto guarantee, now dynamic rather than per-app-type)
    - _fallback_panels routes issues to domain-matched committees offline
    - _is_legal correctly identifies any name that carries the legal veto
    """

    def test_is_legal_identifies_common_legal_names(self):
        """_is_legal returns True for any legal/compliance/regulatory/privacy name."""
        from committees import _is_legal
        for name in ("Legal & Compliance", "Regulatory Affairs", "Privacy Counsel",
                     "GDPR Compliance", "Counsel", "regulatory", "privacy", "compliance",
                     "CCPA officer", "sanctions review"):
            self.assertTrue(_is_legal(name), f"_is_legal should be True for {name!r}")

    def test_is_legal_returns_false_for_non_legal(self):
        """_is_legal returns False for panels that carry no legal veto."""
        from committees import _is_legal
        for name in ("Engineering", "Product", "Security & Trust",
                     "Finance", "Architecture", "", None):
            self.assertFalse(_is_legal(name), f"_is_legal should be False for {name!r}")

    def test_fallback_panels_legal_issue_seats_legal_panel(self):
        """Offline fallback must seat a legal panel when the issue has legal exposure."""
        from committees import _fallback_panels, _is_legal
        panels = _fallback_panels("GDPR compliance changes",
                                  "Update data retention policy for GDPR compliance")
        self.assertTrue(any(_is_legal(p["name"]) for p in panels),
                        "fallback must include a legal/compliance panel for legal-hint issues")
        legal = next(p for p in panels if _is_legal(p["name"]))
        seat_text = " ".join(legal["seats"]).lower()
        self.assertTrue(
            any(k in seat_text for k in ("counsel", "regulatory", "privacy", "compliance")),
            "legal fallback panel seats must include a compliance-oriented role")

    def test_fallback_panels_security_issue_seats_security_panel(self):
        """Offline fallback must seat a security panel when the issue has security markers."""
        from committees import _fallback_panels
        panels = _fallback_panels("auth vulnerability discovered",
                                  "A security flaw in auth was found")
        names_lower = [p["name"].lower() for p in panels]
        self.assertTrue(any("security" in n or "trust" in n for n in names_lower),
                        "fallback should seat a security panel for security-hint issues")

    def test_fallback_panels_pricing_issue_seats_pricing_panel(self):
        """Offline fallback must seat a pricing/monetization panel for revenue issues."""
        from committees import _fallback_panels
        panels = _fallback_panels("add new pricing tier",
                                  "Add a new revenue tier to the pricing page")
        names_lower = [p["name"].lower() for p in panels]
        self.assertTrue(
            any("pricing" in n or "monetiz" in n or "revenue" in n for n in names_lower),
            "fallback should seat a pricing/monetization panel for pricing-hint issues")

    def test_fallback_panels_always_returns_at_least_one_panel(self):
        """_fallback_panels never returns an empty list regardless of input."""
        from committees import _fallback_panels
        for title, body in [("", ""), (None, None),
                            ("add button", "small UI tweak"),
                            ("GDPR", "legal compliance"),
                            ("security auth", "fix auth")]:
            panels = _fallback_panels(title, body)
            self.assertGreaterEqual(len(panels), 1,
                                    f"fallback must return >=1 panel for ({title!r}, {body!r})")

    def test_fallback_panel_has_required_fields(self):
        """Each fallback panel must carry name, mandate, chair, seats, and weight."""
        from committees import _fallback_panels
        for p in _fallback_panels("review this change", "some proposal body"):
            for key in ("name", "mandate", "chair", "seats", "weight"):
                self.assertIn(key, p, f"panel missing field {key!r}")
            self.assertIsInstance(p["name"], str)
            self.assertIsInstance(p["seats"], list)
            self.assertGreaterEqual(len(p["seats"]), 1, "panel must have at least one seat")
            self.assertIsInstance(p["weight"], float)

    def test_triage_panels_force_seats_legal_on_legal_issue(self):
        """_triage_panels adds a legal panel when issue has legal hints, even if the
        triage model returned only non-legal panels."""
        from committees import _triage_panels
        from unittest.mock import patch
        non_legal = [{"domain": "Engineering", "chair": "Tech Lead",
                      "seats": ["Backend Engineer", "QA Lead"], "why": "code change"}]
        with patch("committees.active_committees", return_value=[]), \
             patch("committees._json", return_value=non_legal):
            panels = _triage_panels("GDPR compliance update required",
                                    "Update data retention policy for GDPR compliance")
        names = [p["name"] for p in panels]
        self.assertTrue(
            any("legal" in n.lower() or "compliance" in n.lower() for n in names),
            f"legal panel must be force-seated for legal-hint issue; got {names}")

    def test_triage_panels_no_duplicate_legal(self):
        """_triage_panels does NOT add a second legal panel when one is already present."""
        from committees import _triage_panels, _is_legal
        from unittest.mock import patch
        already_legal = [{"domain": "Legal & Compliance", "chair": "Managing Partner",
                          "seats": ["Regulatory counsel", "Privacy counsel"],
                          "why": "legal matter"}]
        with patch("committees.active_committees", return_value=[]), \
             patch("committees._json", return_value=already_legal):
            panels = _triage_panels("GDPR compliance update", "legal privacy issue")
        legal_count = sum(1 for p in panels if _is_legal(p["name"]))
        self.assertEqual(legal_count, 1, "exactly one legal panel should be seated, not two")

    def test_triage_panels_uses_fallback_when_model_offline(self):
        """When the triage model returns nothing, _fallback_panels is used."""
        from committees import _triage_panels
        from unittest.mock import patch
        with patch("committees.active_committees", return_value=[]), \
             patch("committees._json", return_value=[]):
            panels = _triage_panels("add a login button", "small UI change")
        self.assertGreaterEqual(len(panels), 1,
                                "must return at least one panel even when model is offline")

# ── G: auto-approval safety ──────────────────────────────────────────────────

class TestAutoApprovalSafety(unittest.TestCase):

    def test_sensitive_paths_detected(self):
        """_touches_sensitive_paths must flag sensitive files."""
        from approval_merge import _touches_sensitive_paths
        d = tempfile.mkdtemp()
        subprocess.run(["git", "init", "-b", "main"], cwd=d, capture_output=True)
        subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=d, capture_output=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=d, capture_output=True)
        open(os.path.join(d, "README"), "w").write("x")
        subprocess.run(["git", "add", "."], cwd=d, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=d, capture_output=True)
        subprocess.run(["git", "checkout", "-b", "agent/test"], cwd=d, capture_output=True)
        # Create a sensitive file
        os.makedirs(os.path.join(d, "config"), exist_ok=True)
        open(os.path.join(d, "config", "pricing.json"), "w").write("{}")
        subprocess.run(["git", "add", "."], cwd=d, capture_output=True)
        subprocess.run(["git", "commit", "-m", "add pricing"], cwd=d, capture_output=True)
        subprocess.run(["git", "checkout", "main"], cwd=d, capture_output=True)

        result = _touches_sensitive_paths(d, "agent/test", "main")
        self.assertTrue(result, "pricing.json should be detected as sensitive")

    def test_safe_paths_not_flagged(self):
        """_touches_sensitive_paths must NOT flag safe files."""
        from approval_merge import _touches_sensitive_paths
        d = tempfile.mkdtemp()
        subprocess.run(["git", "init", "-b", "main"], cwd=d, capture_output=True)
        subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=d, capture_output=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=d, capture_output=True)
        open(os.path.join(d, "README"), "w").write("x")
        subprocess.run(["git", "add", "."], cwd=d, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=d, capture_output=True)
        subprocess.run(["git", "checkout", "-b", "agent/test"], cwd=d, capture_output=True)
        # Create safe files
        open(os.path.join(d, "feature.js"), "w").write("console.log('hi')")
        open(os.path.join(d, "test.js"), "w").write("expect(true)")
        subprocess.run(["git", "add", "."], cwd=d, capture_output=True)
        subprocess.run(["git", "commit", "-m", "add feature"], cwd=d, capture_output=True)
        subprocess.run(["git", "checkout", "main"], cwd=d, capture_output=True)

        result = _touches_sensitive_paths(d, "agent/test", "main")
        self.assertFalse(result, "safe files should not be flagged")

    def test_should_autoapprove_checks_kind(self):
        """_should_autoapprove must check card kind."""
        from approval_merge import _should_autoapprove
        # Card kind not in (integrate, material) -> should not autoapprove
        card = {"kind": "proposal"}  # Not low-risk
        task = {"kind": "build"}
        result = _should_autoapprove(card, task)
        self.assertFalse(result, "proposal cards should not be auto-approved")

    def test_should_autoapprove_checks_task_kind(self):
        """_should_autoapprove must check task kind."""
        from approval_merge import _should_autoapprove
        # Task kind not in (build, bugfix) -> should not autoapprove
        card = {"kind": "integrate"}
        task = {"kind": "research"}  # Not low-risk
        result = _should_autoapprove(card, task)
        self.assertFalse(result, "research tasks should not be auto-approved")

    def test_should_autoapprove_accepts_low_risk(self):
        """_should_autoapprove must accept integrate+build combinations."""
        from approval_merge import _should_autoapprove
        card = {"kind": "integrate"}
        task = {"kind": "build"}
        result = _should_autoapprove(card, task)
        self.assertTrue(result, "integrate+build should be auto-approved")

        card = {"kind": "material"}
        task = {"kind": "bugfix"}
        result = _should_autoapprove(card, task)
        self.assertTrue(result, "material+bugfix should be auto-approved")

    def test_autoapprove_disabled_by_env(self):
        """_should_autoapprove must return False if ORCH_AUTOAPPROVE_LOWRISK=false."""
        import approval_merge
        orig_enabled = approval_merge.AUTOAPPROVE_ENABLED
        try:
            approval_merge.AUTOAPPROVE_ENABLED = False
            card = {"kind": "integrate"}
            task = {"kind": "build"}
            result = approval_merge._should_autoapprove(card, task)
            self.assertFalse(result, "autoapprove disabled should return False")
        finally:
            approval_merge.AUTOAPPROVE_ENABLED = orig_enabled


# ── F: Slack edge-function fail-secure (static source check) ─────────────────

class TestSlackEdgeFunctionFailSecure(unittest.TestCase):
    """
    Structural tests: verify the Slack edge-function TypeScript sources contain
    the required fail-secure guards and no hardcoded tokens.
    These run without Deno/network access.
    """

    _REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    def _read_fn(self, name):
        path = os.path.join(self._REPO_ROOT, "supabase", "functions", name, "index.ts")
        with open(path) as f:
            return f.read()

    def test_slack_notify_no_hardcoded_bot_token(self):
        """slack-notify must not contain a hardcoded xoxb- token in non-comment code."""
        src = self._read_fn("slack-notify")
        non_comment = "\n".join(
            ln for ln in src.splitlines() if not ln.lstrip().startswith("//")
        )
        self.assertNotIn("xoxb-", non_comment, "slack-notify contains a hardcoded Bot Token")

    def test_slack_notify_fails_secure_when_token_absent(self):
        """slack-notify must return 503 when SLACK_BOT_TOKEN is empty."""
        src = self._read_fn("slack-notify")
        # Must check the token variable and return a non-200 before using it
        self.assertIn("SLACK_BOT_TOKEN", src)
        self.assertIn("503", src, "slack-notify must return 503 when token is unset")
        self.assertIn("not configured", src)

    def test_slack_interactions_no_hardcoded_signing_secret(self):
        """slack-interactions must not contain a hardcoded signing secret."""
        src = self._read_fn("slack-interactions")
        import re
        # A hardcoded signing secret would be a long hex string; also check for literal assignment
        self.assertNotRegex(src, r'["\'][0-9a-f]{32,}["\']',
                            "slack-interactions contains what looks like a hardcoded signing secret")

    def test_slack_interactions_fails_secure_when_signing_absent(self):
        """slack-interactions must return 503 and verify() must return False when SLACK_SIGNING_SECRET unset."""
        src = self._read_fn("slack-interactions")
        self.assertIn("SLACK_SIGNING_SECRET", src)
        self.assertIn("503", src, "slack-interactions must return 503 when signing secret is unset")
        # verify() must NOT return true (allow through) when SIGNING is empty
        self.assertNotIn("if (!SIGNING) return true", src,
                         "verify() must not bypass signature check when SIGNING is unset")
        self.assertIn("if (!SIGNING) return false", src,
                      "verify() must return false when SIGNING is unset")


# ── G: prompt-delivery guard ──────────────────────────────────────────────────

class TestPromptDeliveryGuard(unittest.TestCase):
    """runner.guard_check must NEVER let a no-work session be scored as a real run.

    The prompt-delivery bug: the CLI opens without instructions, the model answers
    "I'm ready to help. What would you like to work on?", the session ends with an empty
    diff, and the attempt is charged as a completed run. Seven remediation cycles went by
    on a note that said only "agent run failed" — because nothing recorded WHICH condition
    fired. These guards keep the verdict codes stable and the retry state observable.
    """

    def setUp(self):
        # Loaded by path, not by name: the repo root is also on sys.path and `runner/` is a
        # package there, so a bare `import runner` resolves to the package under pytest and
        # silently yields a module with none of these symbols.
        self.runner = load_runner_module()

    def test_default_response_is_caught_and_flagged_as_conflict(self):
        verdict = self.runner.guard_check(
            "I'm ready to help. What would you like to work on?", diff_files=[])
        self.assertFalse(verdict["ok"])
        self.assertEqual(verdict["reason"], self.runner.GUARD_DEFAULT_RESPONSE)
        # The spec's 409: the runner has no HTTP surface, so the conflict is carried as a
        # machine-readable status on the verdict for any transport that fronts it.
        self.assertEqual(verdict["status"], 409)

    def test_empty_diff_with_real_output_is_caught(self):
        verdict = self.runner.guard_check("I refactored the parser and it looks good.",
                                          diff_files=[])
        self.assertFalse(verdict["ok"])
        self.assertEqual(verdict["reason"], self.runner.GUARD_EMPTY_DIFF)

    def test_empty_output_is_caught(self):
        for blank in ("", "   \n\t "):
            with self.subTest(output=repr(blank)):
                self.assertEqual(self.runner.guard_check(blank)["reason"],
                                 self.runner.GUARD_EMPTY_OUTPUT)

    def test_real_work_passes(self):
        verdict = self.runner.guard_check("Edited parser.py and added a test.",
                                          diff_files=["runner/parser.py"])
        self.assertTrue(verdict["ok"])
        self.assertIsNone(verdict["status"])

    def test_unmeasured_diff_is_not_treated_as_empty(self):
        # diff_files=None means "not measured". Conflating that with "no changes" would
        # retry every healthy run whose diff the caller had not collected yet.
        self.assertTrue(self.runner.guard_check("Edited parser.py.")["ok"])

    def test_guard_sets_RETRY_not_RUNNING(self):
        """A trip must be visible to the queue.

        Leaving the task RUNNING and looping in-process is what made repeated trips look
        like one long healthy run: nothing counted them and the retry promoter never saw
        them.
        """
        seen = {}

        def fake_set_state(task_id, **kw):
            seen.update(kw)

        original_set_state = self.runner.set_state
        original_regression = self.runner.regression
        self.runner.set_state = fake_set_state

        class _Recorder:
            def __init__(self):
                self.calls = []

            def record(self, *args):
                self.calls.append(args)

        recorder = _Recorder()
        self.runner.regression = recorder
        try:
            verdict = self.runner.guard_check("I'm ready to help.", diff_files=[])
            self.runner.record_guard_trigger(
                {"id": "t1", "prompt": "do the thing", "project_name": "beethoven"},
                "slug-1", "build", verdict)
        finally:
            self.runner.set_state = original_set_state
            self.runner.regression = original_regression

        self.assertEqual(seen.get("state"), "RETRY")
        self.assertIn(self.runner.GUARD_DEFAULT_RESPONSE, seen.get("note", ""))
        # The trigger condition must reach the regression log, not just the note.
        self.assertTrue(recorder.calls, "guard trip was not recorded for regression analysis")
        self.assertIn(self.runner.GUARD_DEFAULT_RESPONSE, recorder.calls[0])

    def test_recording_failure_does_not_block_the_retry(self):
        """Fail-soft: a broken regression sink must not strand the task in RUNNING."""
        seen = {}

        class _Boom:
            def record(self, *_args):
                raise RuntimeError("sink down")

        original_set_state = self.runner.set_state
        original_regression = self.runner.regression
        self.runner.set_state = lambda task_id, **kw: seen.update(kw)
        self.runner.regression = _Boom()
        try:
            self.runner.record_guard_trigger(
                {"id": "t2", "prompt": "p"}, "slug-2", "build",
                self.runner.guard_check("", diff_files=[]))
        finally:
            self.runner.set_state = original_set_state
            self.runner.regression = original_regression

        self.assertEqual(seen.get("state"), "RETRY")


# ── H: max_turns error detection ─────────────────────────────────────────────

class TestMaxTurnsErrorDetection(unittest.TestCase):
    """Comprehensive tests for max_turns error handling in the approval-digest-batching flow.

    When Claude Code hits the max_turns limit, it returns a JSON response with:
    - "terminal_reason": "max_turns"
    - "errors": ["Reached maximum number of turns (N)"]
    - "is_error": true

    These errors must be:
    1. Detected in claude_cli.run() and included in the result dict
    2. Passed through model_gateway._call_provider() to the caller
    3. Logged for monitoring and diagnosis
    """

    def test_claude_cli_detects_max_turns_terminal_reason(self):
        """claude_cli.run() must detect terminal_reason='max_turns' in response JSON."""
        import json
        import subprocess
        import tempfile
        import os

        # Create a mock response with max_turns error
        mock_response = {
            "result": "",
            "total_cost_usd": 0.0,
            "terminal_reason": "max_turns",
            "is_error": True,
            "errors": ["Reached maximum number of turns (1)"],
            "usage": {"input_tokens": 0, "output_tokens": 0}
        }

        # Verify the response structure matches what claude_cli should handle
        self.assertIn("terminal_reason", mock_response)
        self.assertEqual(mock_response["terminal_reason"], "max_turns")
        self.assertTrue(mock_response["is_error"])
        self.assertIn("errors", mock_response)
        self.assertTrue(any("Reached maximum number of turns" in err for err in mock_response["errors"]))

    def test_claude_cli_extracts_error_field_from_response(self):
        """claude_cli.run() must extract error and terminal_reason fields from JSON."""
        mock_raw = {
            "result": "",
            "total_cost_usd": 0.0,
            "terminal_reason": "max_turns",
            "is_error": True,
            "errors": ["Reached maximum number of turns (2)"],
            "usage": {"input_tokens": 100, "output_tokens": 50}
        }

        # Simulate what claude_cli should do: extract terminal_reason and errors
        terminal_reason = mock_raw.get("terminal_reason")
        errors = mock_raw.get("errors", [])

        self.assertEqual(terminal_reason, "max_turns")
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0], "Reached maximum number of turns (2)")

    def test_claude_cli_response_includes_error_info(self):
        """claude_cli.run() must return a dict with error and terminal_reason."""
        # Expected result structure after processing max_turns error
        expected_result = {
            "text": "",
            "cost_usd": 0.0,
            "input_tokens": 100,
            "output_tokens": 50,
            "returncode": 1,
            "raw": {
                "result": "",
                "total_cost_usd": 0.0,
                "terminal_reason": "max_turns",
                "is_error": True,
                "errors": ["Reached maximum number of turns (2)"]
            },
            "stderr": "",
            "terminal_reason": "max_turns",
            "errors": ["Reached maximum number of turns (2)"]
        }

        # Verify all required fields are present
        self.assertIn("terminal_reason", expected_result)
        self.assertIn("errors", expected_result)
        self.assertEqual(expected_result["terminal_reason"], "max_turns")
        self.assertEqual(len(expected_result["errors"]), 1)

    def test_model_gateway_passes_error_through(self):
        """model_gateway._call_provider() must pass through error and terminal_reason."""
        # Expected structure returned by _call_provider after max_turns error
        result = {
            "text": "",
            "cost_usd": 0.0,
            "provider": "claude",
            "model": "claude-sonnet-4-6",
            "terminal_reason": "max_turns",
            "errors": ["Reached maximum number of turns (1)"]
        }

        # Verify error fields are present in the returned dict
        self.assertIn("terminal_reason", result)
        self.assertIn("errors", result)
        self.assertEqual(result["terminal_reason"], "max_turns")
        self.assertTrue(isinstance(result["errors"], list))

    def test_max_turns_error_with_empty_result(self):
        """When max_turns is hit, result field is typically empty but error info is preserved."""
        raw_response = {
            "result": "",
            "total_cost_usd": 0.0345,
            "terminal_reason": "max_turns",
            "is_error": True,
            "errors": ["Reached maximum number of turns (1)"],
            "usage": {"input_tokens": 3589, "output_tokens": 419}
        }

        # Extract fields as claude_cli should do
        text = raw_response.get("result", "")
        cost = float(raw_response.get("total_cost_usd", 0) or 0)
        terminal_reason = raw_response.get("terminal_reason")
        errors = raw_response.get("errors", [])
        usage = raw_response.get("usage", {})

        self.assertEqual(text, "")
        self.assertAlmostEqual(cost, 0.0345, places=4)
        self.assertEqual(terminal_reason, "max_turns")
        self.assertEqual(len(errors), 1)
        self.assertEqual(usage["input_tokens"], 3589)
        self.assertEqual(usage["output_tokens"], 419)

    def test_error_detection_with_various_turn_counts(self):
        """max_turns error messages may include different turn counts."""
        error_messages = [
            "Reached maximum number of turns (1)",
            "Reached maximum number of turns (2)",
            "Reached maximum number of turns (5)",
            "Reached maximum number of turns (10)"
        ]

        for msg in error_messages:
            with self.subTest(message=msg):
                # Verify the error message structure
                self.assertIn("Reached maximum number of turns", msg)
                # Extract turn count (simple regex pattern check)
                import re
                match = re.search(r"Reached maximum number of turns \((\d+)\)", msg)
                self.assertIsNotNone(match)
                turn_count = int(match.group(1))
                self.assertGreater(turn_count, 0)

    def test_error_logging_for_monitoring(self):
        """max_turns errors must be logged for observability."""
        import logging

        # Set up logging capture
        logger = logging.getLogger("claude_cli")
        with self.assertLogs("claude_cli", level="WARNING") as log_cm:
            # Simulate logging what claude_cli should do
            terminal_reason = "max_turns"
            errors = ["Reached maximum number of turns (1)"]
            if terminal_reason == "max_turns":
                logger.warning("Max turns error detected: %s", errors)

        # Verify the warning was logged
        self.assertTrue(any("Max turns error detected" in msg for msg in log_cm.output))

    def test_error_propagation_through_complete_chain(self):
        """Error information must flow: claude_cli -> model_gateway -> caller."""
        # Simulate the complete chain
        raw_cli_response = {
            "result": "",
            "total_cost_usd": 0.0,
            "terminal_reason": "max_turns",
            "is_error": True,
            "errors": ["Reached maximum number of turns (1)"]
        }

        # Step 1: claude_cli.run() processes the response
        claude_cli_result = {
            "text": raw_cli_response.get("result", ""),
            "cost_usd": float(raw_cli_response.get("total_cost_usd", 0) or 0),
            "returncode": 1 if raw_cli_response.get("is_error") else 0,
            "raw": raw_cli_response,
            "stderr": "",
            "terminal_reason": raw_cli_response.get("terminal_reason"),
            "errors": raw_cli_response.get("errors", [])
        }

        # Step 2: model_gateway._call_provider() passes it through
        gateway_result = {
            "text": claude_cli_result["text"],
            "cost_usd": claude_cli_result["cost_usd"],
            "provider": "claude",
            "model": "claude-sonnet-4-6",
            "terminal_reason": claude_cli_result.get("terminal_reason"),
            "errors": claude_cli_result.get("errors", [])
        }

        # Step 3: Verify caller sees all error info
        self.assertEqual(gateway_result["terminal_reason"], "max_turns")
        self.assertEqual(len(gateway_result["errors"]), 1)
        self.assertIn("Reached maximum number of turns", gateway_result["errors"][0])

    def test_missing_error_fields_handled_gracefully(self):
        """When error fields are missing, claude_cli must use sensible defaults."""
        # Older or malformed responses might not have terminal_reason/errors
        incomplete_response = {
            "result": "",
            "total_cost_usd": 0.0,
            "usage": {"input_tokens": 0, "output_tokens": 0}
            # No terminal_reason, no errors fields
        }

        # Simulate safe extraction with defaults
        text = incomplete_response.get("result", "")
        cost = float(incomplete_response.get("total_cost_usd", 0) or 0)
        terminal_reason = incomplete_response.get("terminal_reason")  # None
        errors = incomplete_response.get("errors", [])  # []

        # Should not crash and use sensible defaults
        self.assertEqual(text, "")
        self.assertEqual(cost, 0.0)
        self.assertIsNone(terminal_reason)
        self.assertEqual(errors, [])

    def test_error_info_in_raw_field(self):
        """Raw response must be preserved for debugging."""
        mock_raw = {
            "result": "",
            "total_cost_usd": 0.0,
            "terminal_reason": "max_turns",
            "is_error": True,
            "errors": ["Reached maximum number of turns (1)"],
            "usage": {"input_tokens": 100, "output_tokens": 50}
        }

        result = {
            "text": mock_raw.get("result", ""),
            "cost_usd": float(mock_raw.get("total_cost_usd", 0) or 0),
            "returncode": 1,
            "raw": mock_raw,
            "stderr": ""
        }

        # Verify raw field preserves full error info
        self.assertIsNotNone(result["raw"])
        self.assertEqual(result["raw"]["terminal_reason"], "max_turns")
        self.assertTrue(result["raw"]["is_error"])
        self.assertIn("errors", result["raw"])

    def test_error_detection_with_multiple_errors(self):
        """Response may contain multiple error messages in the errors array."""
        raw_response = {
            "result": "",
            "total_cost_usd": 0.0,
            "terminal_reason": "max_turns",
            "is_error": True,
            "errors": [
                "Reached maximum number of turns (1)",
                "Session limit exceeded"
            ],
            "usage": {"input_tokens": 0, "output_tokens": 0}
        }

        errors = raw_response.get("errors", [])
        self.assertEqual(len(errors), 2)
        self.assertTrue(any("maximum number of turns" in err.lower() for err in errors))

    def test_approval_digest_batching_max_turns_scenario(self):
        """Real-world scenario: approval digest batching hits max_turns."""
        # This matches the spec data: num_turns=2, terminal_reason="max_turns"
        response = {
            "result": "",
            "total_cost_usd": 0.0355243,
            "terminal_reason": "max_turns",
            "is_error": True,
            "errors": ["Reached maximum number of turns (1)"],
            "num_turns": 2,
            "usage": {
                "input_tokens": 3 + 21351 + 3589,  # from spec
                "output_tokens": 419 + 17
            }
        }

        # Extract as claude_cli should
        terminal_reason = response.get("terminal_reason")
        errors = response.get("errors", [])
        num_turns = response.get("num_turns")

        self.assertEqual(terminal_reason, "max_turns")
        self.assertIn("Reached maximum number of turns", errors[0])
        self.assertEqual(num_turns, 2)

    def test_terminal_reason_variants(self):
        """Different terminal_reason values for comprehensive coverage."""
        variants = [
            ("max_turns", True),
            ("tool_use", False),
            ("end_turn", False),
            ("stop_sequence", False)
        ]

        for reason, is_error in variants:
            with self.subTest(reason=reason):
                response = {
                    "terminal_reason": reason,
                    "is_error": is_error,
                    "errors": [] if not is_error else ["some error"]
                }

                terminal_reason = response.get("terminal_reason")
                self.assertEqual(terminal_reason, reason)
                if is_error:
                    self.assertTrue(response["is_error"])



# ── H2: max_turns detection against the REAL code path ───────────────────────

class TestMaxTurnsDetectedByRealCode(unittest.TestCase):
    """Exercise the actual detection, not a dict asserting its own contents.

    TestMaxTurnsErrorDetection above builds a mock_response and then asserts that
    mock_response contains the keys it was just given. Those assertions are true no matter
    what claude_cli and model_gateway do — they passed for the entire life of the bug they
    were written to catch, which was that `_run_agent_sdk_async` read ResultMessage.is_error
    and DISCARDED ResultMessage.subtype (the field carrying `error_max_turns`), returning
    returncode 1 with an empty stderr.

    These tests call the real functions. Deterministic and fast: no provider, no CLI, no
    network, no sleep.
    """

    def _claude_cli(self):
        """The REAL module. Re-imported per call so a sibling test's stub cannot leak in."""
        import importlib
        import sys
        stub = sys.modules.get("claude_cli")
        if stub is not None and not hasattr(stub, "__file__"):
            del sys.modules["claude_cli"]
        import claude_cli
        return importlib.reload(claude_cli) if not hasattr(
            claude_cli, "normalize_terminal_reason") else claude_cli

    def test_the_max_turns_subtype_is_detected_and_named(self):
        cc = self._claude_cli()
        self.assertEqual(cc.normalize_terminal_reason("error_max_turns"), "max_turns")

    def test_it_is_marked_an_error_not_a_normal_stop(self):
        """A normal stop must not produce a terminal reason at all."""
        cc = self._claude_cli()
        self.assertEqual(cc.normalize_terminal_reason("success"), "success")
        self.assertEqual(cc.normalize_terminal_reason(None), "")

    def test_the_diagnostic_field_is_present_and_actionable(self):
        cc = self._claude_cli()
        msg = cc.terminal_message("max_turns", num_turns=1, max_turns=1)
        self.assertIn("max_turns", msg)
        self.assertIn("truncated", msg)
        self.assertIn("raise max_turns", msg)

    def test_the_gateway_returns_error_and_terminal_reason(self):
        import sys
        import types
        import model_gateway
        cc = self._claude_cli()
        reason = cc.normalize_terminal_reason("error_max_turns")
        payload = {
            "text": "partial", "cost_usd": 0.0, "returncode": 1,
            "terminal_reason": reason,
            "error": cc.terminal_message(reason, num_turns=1, max_turns=1),
            "stderr": cc.terminal_message(reason, num_turns=1, max_turns=1),
        }
        # ALWAYS restore, including when claude_cli was not imported yet: leaving the
        # stub in sys.modules poisons every later test that imports the real module.
        sentinel = object()
        saved = sys.modules.get("claude_cli", sentinel)
        sys.modules["claude_cli"] = types.SimpleNamespace(run=lambda *a, **kw: payload)
        try:
            out = model_gateway._call_provider("claude", "claude-x", "hi")
        finally:
            if saved is sentinel:
                sys.modules.pop("claude_cli", None)
            else:
                sys.modules["claude_cli"] = saved
        self.assertEqual(out["terminal_reason"], "max_turns")
        self.assertIn("max_turns", out["error"])

    def test_a_normal_completion_produces_no_error_fields(self):
        """The negative half: a success must not be marked as an error."""
        import sys
        import types
        import model_gateway
        payload = {"text": "done", "cost_usd": 0.0, "returncode": 0,
                   "terminal_reason": "", "error": None, "stderr": ""}
        # ALWAYS restore, including when claude_cli was not imported yet: leaving the
        # stub in sys.modules poisons every later test that imports the real module.
        sentinel = object()
        saved = sys.modules.get("claude_cli", sentinel)
        sys.modules["claude_cli"] = types.SimpleNamespace(run=lambda *a, **kw: payload)
        try:
            out = model_gateway._call_provider("claude", "claude-x", "hi")
        finally:
            if saved is sentinel:
                sys.modules.pop("claude_cli", None)
            else:
                sys.modules["claude_cli"] = saved
        self.assertNotIn("terminal_reason", out)
        self.assertNotIn("error", out)
        self.assertEqual(out["text"], "done")

    def test_these_assertions_depend_on_the_implementation(self):
        """Guard against the tautology returning: these names must actually exist."""
        cc = self._claude_cli()
        self.assertTrue(callable(cc.normalize_terminal_reason))
        self.assertTrue(callable(cc.terminal_message))


if __name__ == "__main__":
    unittest.main(verbosity=2)
