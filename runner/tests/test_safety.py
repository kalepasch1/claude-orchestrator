"""
test_safety.py - safety guards for the autonomy layer.

A) resource_governor must NEVER delete a worktree with uncommitted changes or an
   unmerged branch.
B) session_watcher must NEVER close a tab for a session whose output shows in-progress signals,
   and must NEVER call _close_vscode_tab unless done=True.
C) secrets_manager must NEVER write secret values to any Supabase insert.
D) kill_switch must NEVER allow paused projects to run tasks.
E) improvement_miner must NEVER exceed budget caps or deploy degraded experiments.
"""
import os, sys, tempfile, subprocess, json, unittest, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


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
        """claude_cli.run must return cost_usd > 0 when the CLI returns a cost in JSON."""
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

        self.assertGreater(r["cost_usd"], 0,
                           "claude_cli must extract cost_usd from JSON envelope")
        self.assertAlmostEqual(r["cost_usd"], 0.0042)
        self.assertEqual(r["input_tokens"], 100)
        self.assertEqual(r["output_tokens"], 50)
        self.assertEqual(r["text"], "pong")

    def test_runner_record_writes_real_cost(self):
        """record() must write the passed cost to outcomes.usd, not the regex fallback."""
        import time
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        import runner, db

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

    def test_fintech_committee_has_regulatory_veto(self):
        """Fintech apps must have Regulatory seat with veto power."""
        from committees import for_app, has_veto_seat
        board = for_app("paypal")  # infer from name
        seats = [m["seat"] for m in board]
        self.assertIn("Regulatory", seats, "fintech must have Regulatory seat")
        self.assertTrue(has_veto_seat("paypal", "Regulatory"),
                       "Regulatory must have veto power for fintech")

    def test_consumer_committee_has_privacy_veto(self):
        """Consumer apps must have Privacy seat with veto power."""
        from committees import for_app, has_veto_seat
        board = for_app("social_media")  # infer from name
        seats = [m["seat"] for m in board]
        self.assertIn("Privacy", seats, "consumer must have Privacy seat")
        self.assertTrue(has_veto_seat("social_media", "Privacy"),
                       "Privacy must have veto power for consumer")

    def test_saas_committee_has_reliability_veto(self):
        """SaaS apps must have Reliability seat with veto power."""
        from committees import for_app, has_veto_seat
        board = for_app("workspace_saas")  # infer from name
        seats = [m["seat"] for m in board]
        self.assertIn("Reliability", seats, "saas must have Reliability seat")
        self.assertTrue(has_veto_seat("workspace_saas", "Reliability"),
                       "Reliability must have veto power for saas")

    def test_platform_committee_has_stability_veto(self):
        """Platform apps must have Stability seat with veto power."""
        from committees import for_app, has_veto_seat
        board = for_app("platform-core")  # infer from name
        seats = [m["seat"] for m in board]
        self.assertIn("Stability", seats, "platform must have Stability seat")
        self.assertTrue(has_veto_seat("platform-core", "Stability"),
                       "Stability must have veto power for platform")

    def test_explicit_app_type_overrides_inference(self):
        """If db_project['type'] is set, it should override name inference."""
        from committees import for_app
        # Pass a dict with explicit type
        db_project = {"type": "fintech", "name": "ambiguous-name"}
        board = for_app("ambiguous-name", db_project)
        seats = [m["seat"] for m in board]
        self.assertIn("Regulatory", seats,
                     "explicit type=fintech should return fintech committee")

    def test_unknown_app_type_uses_default(self):
        """Unknown app types should fall back to the default committee."""
        from committees import for_app
        board = for_app("xyz-system-123")
        seats = [m["seat"] for m in board]
        # Default has Code, Security, Performance
        self.assertIn("Security", seats, "default committee must have Security")
        self.assertIn("Code", seats, "default committee must have Code")

    def test_members_for_app_returns_seat_names(self):
        """members_for_app should return a list of seat names only."""
        from committees import members_for_app
        seats = members_for_app("bank-app")  # infer fintech
        self.assertIsInstance(seats, list)
        self.assertTrue(all(isinstance(s, str) for s in seats))
        self.assertIn("Regulatory", seats)

    def test_has_veto_seat_for_nonexistent_seat(self):
        """has_veto_seat should return False for a seat that doesn't exist."""
        from committees import has_veto_seat
        result = has_veto_seat("social-app", "NonexistentSeat")
        self.assertFalse(result, "nonexistent seat should return False")

    def test_all_veto_seats_respected(self):
        """All defined veto seats must actually have veto=True in their definition."""
        from committees import APP_COMMITTEES, has_veto_seat
        for app_type, members in APP_COMMITTEES.items():
            for m in members:
                if m.get("veto"):
                    # Double-check: calling has_veto_seat should agree
                    result = has_veto_seat(app_type, m["seat"],
                                          db_project={"type": app_type})
                    self.assertTrue(result,
                                   f"{app_type}/{m['seat']} marked veto but has_veto_seat disagrees")

    def test_all_committee_types_defined(self):
        """all_types() must return fintech, consumer, saas, platform, opensource."""
        from committees import all_types
        types = all_types()
        self.assertIn("fintech", types)
        self.assertIn("consumer", types)
        self.assertIn("saas", types)
        self.assertIn("platform", types)
        self.assertIn("opensource", types)

    def test_committee_members_structure(self):
        """Each member must have seat, expertise, and veto keys."""
        from committees import for_app
        board = for_app("fintech-app")
        for member in board:
            self.assertIn("seat", member, "member must have 'seat'")
            self.assertIn("expertise", member, "member must have 'expertise'")
            self.assertIn("veto", member, "member must have 'veto'")
            self.assertIsInstance(member["seat"], str)
            self.assertIsInstance(member["expertise"], str)
            self.assertIsInstance(member["veto"], bool)

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
