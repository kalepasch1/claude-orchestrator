"""The no-deploy declaration moved out of the schema-validated vercel.json.

vercel.json is validated against a CLOSED schema. Any top-level key the schema does not
define makes `vercel deploy` abort before uploading anything:

    Error: Invalid vercel.json - should NOT have additional property `_comment`.

This repo's root vercel.json carried TWO such keys, `_comment` and
`_deploymentDisabledIntentionally`, and neither could simply be deleted: both are read by
runner/vercel_config_guard.py:_declares_intentional_no_deploy, which is what stops the
`deployment_disabled_everywhere` advisory re-filing itself as a backlog task on every
sweep. So they moved to a sibling `vercel.no-deploy.json`.

These tests pin all three halves of that: the shipped file is schema-clean, the sidecar
is still honoured, and the legacy in-config form has not regressed.
"""
import json
import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "runner"))

import vercel_config_guard as guard  # noqa: E402


def _write(root, name, payload):
    with open(os.path.join(root, name), "w", encoding="utf-8") as fh:
        json.dump(payload, fh)


class TestShippedRootConfig:
    def test_root_vercel_json_has_no_non_schema_keys(self):
        """The whole point: the CLI must be able to read this file."""
        with open(os.path.join(REPO, "vercel.json"), encoding="utf-8") as fh:
            cfg = json.load(fh)
        assert [k for k in cfg if k.startswith("_")] == []

    def test_root_vercel_json_still_disables_git_deployments(self):
        """Removing the keys must not weaken the guard the comment describes."""
        with open(os.path.join(REPO, "vercel.json"), encoding="utf-8") as fh:
            cfg = json.load(fh)
        assert cfg["git"]["deploymentEnabled"] is False

    def test_sidecar_still_declares_the_intent(self):
        assert guard._declares_intentional_no_deploy({}, REPO) is True


class TestSidecarLookup:
    def test_sidecar_flag_is_honoured(self, tmp_path):
        _write(str(tmp_path), guard.NO_DEPLOY_SIDECAR,
               {"deploymentDisabledIntentionally": True})
        assert guard._declares_intentional_no_deploy({}, str(tmp_path)) is True

    def test_sidecar_comment_phrase_is_honoured(self, tmp_path):
        _write(str(tmp_path), guard.NO_DEPLOY_SIDECAR,
               {"comment": "This repo deliberately disables git deployments."})
        assert guard._declares_intentional_no_deploy({}, str(tmp_path)) is True

    def test_sidecar_comment_may_be_a_list(self, tmp_path):
        _write(str(tmp_path), guard.NO_DEPLOY_SIDECAR,
               {"comment": ["first line", "do not deploy"]})
        assert guard._declares_intentional_no_deploy({}, str(tmp_path)) is True

    def test_unrelated_sidecar_does_not_declare_intent(self, tmp_path):
        _write(str(tmp_path), guard.NO_DEPLOY_SIDECAR, {"comment": "a note about caching"})
        assert guard._declares_intentional_no_deploy({}, str(tmp_path)) is False

    def test_missing_sidecar_is_not_an_intent(self, tmp_path):
        assert guard._declares_intentional_no_deploy({}, str(tmp_path)) is False

    @pytest.mark.parametrize("root", [None, "", "/nonexistent/path/xyz"])
    def test_unreadable_root_is_fail_soft(self, root):
        assert guard._declares_intentional_no_deploy({}, root) is False

    def test_malformed_sidecar_is_fail_soft(self, tmp_path):
        with open(os.path.join(str(tmp_path), guard.NO_DEPLOY_SIDECAR), "w") as fh:
            fh.write("{not json")
        assert guard._declares_intentional_no_deploy({}, str(tmp_path)) is False


class TestLegacyInConfigForm:
    """A project that has not migrated must not start re-filing the advisory."""

    def test_legacy_flag_still_honoured(self):
        assert guard._declares_intentional_no_deploy(
            {"_deploymentDisabledIntentionally": True}) is True

    def test_legacy_comment_still_honoured(self):
        assert guard._declares_intentional_no_deploy(
            {"_comment": "this file disables git deployments. Do not remove."}) is True

    def test_plain_config_declares_nothing(self):
        assert guard._declares_intentional_no_deploy({"git": {"deploymentEnabled": False}}) is False

    @pytest.mark.parametrize("cfg", [None, [], "text", 7])
    def test_non_dict_config_is_fail_soft(self, cfg):
        assert guard._declares_intentional_no_deploy(cfg) is False


class TestNonSchemaKeyDetection:
    def test_check_root_flags_a_non_schema_key(self, tmp_path):
        root = str(tmp_path)
        _write(root, "vercel.json", {"_comment": "hi", "git": {"deploymentEnabled": True}})
        codes = [v.get("code") for v in guard.check_root(root, root, "master")]
        assert "vercel_json_non_schema_key" in codes

    def test_check_root_is_quiet_on_a_clean_config(self, tmp_path):
        root = str(tmp_path)
        _write(root, "vercel.json", {"git": {"deploymentEnabled": True}})
        codes = [v.get("code") for v in guard.check_root(root, root, "master")]
        assert "vercel_json_non_schema_key" not in codes

    def test_the_non_schema_rule_is_advisory_not_blocking(self):
        """Git deploys are unaffected, so this must never quarantine a merge."""
        assert "vercel_json_non_schema_key" not in guard.BLOCKING
