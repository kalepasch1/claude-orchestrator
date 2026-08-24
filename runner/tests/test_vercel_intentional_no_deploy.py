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
import json
import shutil
import tempfile

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
        # Now declared in the sidecar rather than in vercel.json, so the root has
        # to be passed. The declaration moved because vercel.json is
        # schema-validated and the `_comment` carrying it made `vercel deploy`
        # fail outright — see test_vercel_json_stays_schema_valid below.
        self.assertTrue(guard._declares_intentional_no_deploy(cfg, repo),
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


class TestSchemaValidity(unittest.TestCase):
    """vercel.json is schema-validated; an unknown top-level key is a deploy blocker.

    Every `vercel deploy` from the repo root failed before uploading anything:

        Error: Invalid vercel.json - should NOT have additional property `_comment`.
        Please remove it.

    The keys were there for a good reason — they recorded that this repo's
    no-deploy state is deliberate, which is what stopped
    `deployment_disabled_everywhere` re-filing itself as a backlog task on every
    sweep. But documenting a guard by breaking the deploy tool is not a trade
    worth making, so the declaration moved to `.vercel-no-deploy.json`, which
    nothing validates against a schema.

    Scope, established while fixing it: this was a LOCAL TOOLING BLOCKER, not an
    outage. Production deploys through the `web` project, whose `web/vercel.json`
    carries only schema keys; the root config exists solely to disable git
    deployments for anything pointed at the repo root, and those are disabled by
    design — so the invalid key never blocked a deploy that would otherwise have
    happened. It blocked `vercel deploy` run by a human from the repo root.
    """

    REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    def _configs(self):
        for rel in ("vercel.json", os.path.join("web", "vercel.json")):
            path = os.path.join(self.REPO, rel)
            if os.path.isfile(path):
                yield rel, guard._load_json(path)

    def test_no_vercel_json_carries_a_non_schema_key(self):
        found = []
        for rel, cfg in self._configs():
            found += ["%s: %s" % (rel, k) for k in cfg if k.startswith("_")]
        self.assertEqual(found, [], "underscore-prefixed keys make `vercel deploy` refuse: %s" % found)

    def test_the_root_config_still_disables_git_deployments(self):
        # The whole point of the file. Removing the comment must not remove the guard.
        cfg = guard._load_json(os.path.join(self.REPO, "vercel.json"))
        self.assertIs(cfg.get("git", {}).get("deploymentEnabled"), False)

    def test_the_sidecar_records_the_intent_and_the_reason(self):
        data = guard._load_json(os.path.join(self.REPO, guard.NO_DEPLOY_SIDECAR))
        self.assertIs(data.get("intentional"), True)
        why = data.get("why")
        text = " ".join(why) if isinstance(why, list) else str(why or "")
        self.assertIn("web", text, "the sidecar must say WHICH project deploys instead")
        self.assertGreater(len(text), 80, "a bare flag loses the reason the guard exists")


class TestSidecarDetection(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _write(self, payload):
        with open(os.path.join(self.dir, guard.NO_DEPLOY_SIDECAR), "w") as fh:
            fh.write(payload if isinstance(payload, str) else json.dumps(payload))

    def test_sidecar_alone_declares_intent(self):
        self._write({"intentional": True})
        self.assertTrue(guard._declares_intentional_no_deploy({}, self.dir))

    def test_missing_sidecar_is_not_intent(self):
        # Fail in the safe direction: no declaration means the advisory keeps
        # firing, which is noisy. The reverse would silence a real misconfiguration.
        self.assertFalse(guard._declares_intentional_no_deploy({}, self.dir))

    def test_malformed_sidecar_is_not_intent_and_does_not_raise(self):
        self._write("{not json")
        self.assertFalse(guard._declares_intentional_no_deploy({}, self.dir))

    def test_only_a_true_boolean_counts(self):
        for value in ("true", 1, "yes", None, False, {}):
            with self.subTest(value=value):
                self._write({"intentional": value})
                self.assertFalse(guard._declares_intentional_no_deploy({}, self.dir))

    def test_in_config_declarations_still_work_for_other_repos(self):
        # This guard sweeps EVERY project. Another repo may still record the
        # decision in its vercel.json; dropping that path would resume re-filing
        # an advisory those repos had already answered.
        self.assertTrue(guard._declares_intentional_no_deploy(
            {"_deploymentDisabledIntentionally": True}, self.dir))
        self.assertTrue(guard._declares_intentional_no_deploy(
            {"_comment": "this repo does not deploy"}, self.dir))

    def test_root_is_optional_so_existing_callers_keep_working(self):
        self.assertTrue(guard._declares_intentional_no_deploy(
            {"_deploymentDisabledIntentionally": True}))
        self.assertFalse(guard._declares_intentional_no_deploy({}))

    def test_the_advisory_is_silenced_by_the_sidecar_alone(self):
        # End to end: a vercel.json with no underscore keys at all, plus the
        # sidecar, must produce no deployment_disabled_everywhere violation.
        with open(os.path.join(self.dir, "vercel.json"), "w") as fh:
            json.dump({"git": {"deploymentEnabled": False}}, fh)
        self._write({"intentional": True})
        codes = [v["code"] for v in guard.check_deploy_skip(
            self.dir, self.dir, guard._load_json(os.path.join(self.dir, "vercel.json")), "master")]
        self.assertNotIn("deployment_disabled_everywhere", codes)

    def test_without_the_sidecar_the_advisory_still_fires(self):
        with open(os.path.join(self.dir, "vercel.json"), "w") as fh:
            json.dump({"git": {"deploymentEnabled": False}}, fh)
        codes = [v["code"] for v in guard.check_deploy_skip(
            self.dir, self.dir, guard._load_json(os.path.join(self.dir, "vercel.json")), "master")]
        self.assertIn("deployment_disabled_everywhere", codes)

    def test_the_advice_no_longer_recommends_the_key_that_breaks_the_cli(self):
        # The guard used to tell operators to add `_deploymentDisabledIntentionally`
        # to vercel.json — the exact key that makes `vercel deploy` refuse. Advice
        # that creates the next bug is worse than no advice.
        with open(os.path.join(self.dir, "vercel.json"), "w") as fh:
            json.dump({"git": {"deploymentEnabled": False}}, fh)
        [violation] = [v for v in guard.check_deploy_skip(
            self.dir, self.dir, guard._load_json(os.path.join(self.dir, "vercel.json")), "master")
            if v["code"] == "deployment_disabled_everywhere"]
        self.assertIn(".vercel-no-deploy.json", violation["fix"])
        self.assertNotIn('"_deploymentDisabledIntentionally": true` (or', violation["fix"])
