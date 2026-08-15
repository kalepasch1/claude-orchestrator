#!/usr/bin/env python3
"""An advisory nobody can answer becomes a backlog generator.

`deployment_disabled_everywhere` is advisory because it cannot tell a broken config from a
correct one — its own message asks a human to "confirm it is intended". Nothing ever
recorded the confirmation, so every sweep re-filed it, and each filing became a task. Four
of the five intents collapsed into backlog-batch-beethoven-59654f8 are that one advisory
re-filed under different names.

Worse, acting on it here would have been destructive: this repo's ROOT vercel.json
disables git deployments deliberately, to stop a duplicate Vercel project (once
auto-created by importing the repo root) from ever silently building. The comment ends
"Do not remove."

So the confirmation now lives in the config. These tests pin two things in tension: the
opt-out silences the advisory, and it does NOT silence the blocking case where some
branches deploy and the default branch does not — the shape that actually stops production
by accident.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import vercel_config_guard as guard


class TestIntentDetection(unittest.TestCase):
    def test_explicit_flag(self):
        self.assertTrue(guard._declares_intentional_no_deploy(
            {"_deploymentDisabledIntentionally": True}))

    def test_comment_prose_is_accepted(self):
        self.assertTrue(guard._declares_intentional_no_deploy(
            {"_comment": "this repo does not deploy; the only project is web/"}))

    def test_the_real_root_config_is_recognised(self):
        repo = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        cfg = guard._load_json(os.path.join(repo, "vercel.json"))
        if not cfg:
            self.skipTest("root vercel.json not present")
        self.assertTrue(guard._declares_intentional_no_deploy(cfg),
                        "the documented 'Do not remove' guard must read as intentional")

    def test_absent_or_unrelated_comment_is_not_intent(self):
        for cfg in ({}, {"git": {}}, {"_comment": "build settings for the web app"},
                    {"_deploymentDisabledIntentionally": False},
                    {"_deploymentDisabledIntentionally": "yes"}, None, "text"):
            with self.subTest(cfg=cfg):
                self.assertFalse(guard._declares_intentional_no_deploy(cfg))

    def test_list_comments_are_joined(self):
        self.assertTrue(guard._declares_intentional_no_deploy(
            {"_comment": ["guard:", "this file disables git deployments"]}))


class TestAdvisorySuppression(unittest.TestCase):
    """check_root is exercised through its violation list, on a temp root."""

    def _check(self, cfg):
        """Build a real one-commit git repo so the guard resolves a real default branch.

        A bare temp dir makes `_default_branch` guess, and then no `deploymentEnabled`
        key matches — the rules under test never run and every assertion passes vacuously.
        """
        import json
        import subprocess
        import tempfile
        root = tempfile.mkdtemp()
        run = lambda *a: subprocess.run(["git", *a], cwd=root, capture_output=True, text=True)
        run("init", "-b", "master")
        with open(os.path.join(root, "vercel.json"), "w", encoding="utf-8") as fh:
            json.dump(cfg, fh)
        run("add", "-A")
        run("-c", "user.name=T", "-c", "user.email=t@t.t", "commit", "-m", "cfg")
        branch = guard._default_branch(root, "master")
        self.assertEqual(branch, "master", "fixture must resolve the branch the config keys on")
        return [v["code"] for v in guard.check_root(root, root, branch)]

    def test_blanket_false_without_intent_still_warns(self):
        codes = self._check({"git": {"deploymentEnabled": False}})
        self.assertIn("deployment_disabled_everywhere", codes)

    def test_blanket_false_with_intent_is_silent(self):
        codes = self._check({"_deploymentDisabledIntentionally": True,
                             "git": {"deploymentEnabled": False}})
        self.assertNotIn("deployment_disabled_everywhere", codes)

    def test_map_disabling_everything_with_intent_is_silent(self):
        codes = self._check({"_deploymentDisabledIntentionally": True,
                             "git": {"deploymentEnabled": {"*": False}}})
        self.assertNotIn("deployment_disabled_everywhere", codes)

    def test_intent_does_NOT_silence_the_blocking_inconsistent_case(self):
        """The dangerous shape: other branches deploy, the default branch does not.

        That is never intended and is what silently stops production, so an opt-out must
        not be able to hide it — otherwise the flag becomes a way to disable the one rule
        worth blocking on.
        """
        codes = self._check({"_deploymentDisabledIntentionally": True,
                             "git": {"deploymentEnabled": {"*": False, "preview": True}}})
        self.assertIn("deployment_disabled_for_default_branch", codes)

    def test_correctly_enabled_default_branch_is_clean(self):
        codes = self._check({"git": {"deploymentEnabled": {"*": False, "master": True}}})
        self.assertNotIn("deployment_disabled_everywhere", codes)
        self.assertNotIn("deployment_disabled_for_default_branch", codes)


class TestRepoIsQuietNow(unittest.TestCase):
    def test_this_repo_reports_no_deployment_advisories(self):
        repo = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        if not os.path.isfile(os.path.join(repo, "vercel.json")):
            self.skipTest("root vercel.json not present")
        result = guard.check_repo(repo, "master", "beethoven")
        codes = [v["code"] for v in result["violations"]]
        self.assertNotIn("deployment_disabled_everywhere", codes,
                         "the documented intentional guard must stop re-filing")
        self.assertTrue(result["ok"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
