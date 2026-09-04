"""deploy_silence_detector.deployment_intentionally_disabled — subroot awareness.

The false negative under test: a repo whose ROOT vercel.json disables git deploys
purely as a duplicate-project guard, while the REAL Vercel project lives in a
subdirectory that enables the default branch. Reading only the root, the detector
concluded "this repo does not deploy" and permanently suppressed deploy-silence
alerts for the project actually serving production.

This repository is the canonical example: root vercel.json is the guard, web/
vercel.json carries {"*": false, "master": true}.
"""
from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runner"))

import deploy_silence_detector as dsd  # noqa: E402


def _write(tmp_path, relpath, cfg):
    path = tmp_path / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg), encoding="utf-8")
    return path


# -- the regression: root guard must not mask a subdirectory project -------


def test_root_guard_does_not_suppress_real_subdir_project(tmp_path):
    """The exact shape of this repository. Must NOT be treated as no-deploy."""
    _write(tmp_path, "vercel.json", {
        "_comment": "GUARD: the ONLY Vercel project is 'web'. Do not remove.",
        "_deploymentDisabledIntentionally": True,
        "git": {"deploymentEnabled": False},
    })
    _write(tmp_path, "web/vercel.json", {
        "git": {"deploymentEnabled": {"*": False, "master": True}},
    })
    assert dsd.deployment_intentionally_disabled(str(tmp_path)) is False


def test_root_only_disable_is_still_suppressed(tmp_path):
    """A genuinely non-deploying repo (no subdir project) stays suppressed —
    an alert that is always on is the same as no alert."""
    _write(tmp_path, "vercel.json", {"git": {"deploymentEnabled": False}})
    assert dsd.deployment_intentionally_disabled(str(tmp_path)) is True


def test_subdir_that_also_disables_does_not_unsuppress(tmp_path):
    _write(tmp_path, "vercel.json", {"git": {"deploymentEnabled": False}})
    _write(tmp_path, "web/vercel.json", {
        "git": {"deploymentEnabled": {"*": False}},
    })
    assert dsd.deployment_intentionally_disabled(str(tmp_path)) is True


def test_subdir_with_blanket_true_unsuppresses(tmp_path):
    _write(tmp_path, "vercel.json", {"git": {"deploymentEnabled": False}})
    _write(tmp_path, "app/vercel.json", {"git": {"deploymentEnabled": True}})
    assert dsd.deployment_intentionally_disabled(str(tmp_path)) is False


def test_subdir_without_deploymentEnabled_key_unsuppresses(tmp_path):
    """No `git.deploymentEnabled` key is Vercel's default: deploys ARE on."""
    _write(tmp_path, "vercel.json", {"git": {"deploymentEnabled": False}})
    _write(tmp_path, "site/vercel.json", {"git": {}})
    assert dsd.deployment_intentionally_disabled(str(tmp_path)) is False


@pytest.mark.parametrize("sub", ["web", "app", "site", "frontend", "www", "client", "apps"])
def test_every_default_subroot_is_scanned(tmp_path, sub):
    _write(tmp_path, "vercel.json", {"git": {"deploymentEnabled": False}})
    _write(tmp_path, "%s/vercel.json" % sub,
           {"git": {"deploymentEnabled": {"master": True}}})
    assert dsd.deployment_intentionally_disabled(str(tmp_path)) is False


def test_unlisted_subroot_is_not_scanned(tmp_path):
    """Scan stays cheap and predictable: only the configured names."""
    _write(tmp_path, "vercel.json", {"git": {"deploymentEnabled": False}})
    _write(tmp_path, "some-other-dir/vercel.json",
           {"git": {"deploymentEnabled": {"master": True}}})
    assert dsd.deployment_intentionally_disabled(str(tmp_path)) is True


# -- preserved behaviour ---------------------------------------------------


def test_no_vercel_json_at_all_is_not_intentional(tmp_path):
    assert dsd.deployment_intentionally_disabled(str(tmp_path)) is False


def test_root_enabling_default_branch_is_not_intentional(tmp_path):
    _write(tmp_path, "vercel.json", {
        "git": {"deploymentEnabled": {"*": False, "master": True}},
    })
    assert dsd.deployment_intentionally_disabled(str(tmp_path)) is False


def test_empty_deploymentEnabled_map_is_not_intentional(tmp_path):
    """An empty map disables nothing; it must not read as no-deploy."""
    _write(tmp_path, "vercel.json", {"git": {"deploymentEnabled": {}}})
    assert dsd.deployment_intentionally_disabled(str(tmp_path)) is False


# -- fail-soft (bad input never wedges the sweep) --------------------------


def test_malformed_root_json_is_not_intentional(tmp_path):
    (tmp_path / "vercel.json").write_text("{not json", encoding="utf-8")
    assert dsd.deployment_intentionally_disabled(str(tmp_path)) is False


def test_malformed_subdir_json_does_not_raise(tmp_path):
    _write(tmp_path, "vercel.json", {"git": {"deploymentEnabled": False}})
    (tmp_path / "web").mkdir()
    (tmp_path / "web" / "vercel.json").write_text("{not json", encoding="utf-8")
    # Unreadable subdir config proves nothing, so the root verdict stands.
    assert dsd.deployment_intentionally_disabled(str(tmp_path)) is True


def test_missing_repo_path_does_not_raise(tmp_path):
    assert dsd.deployment_intentionally_disabled(
        str(tmp_path / "definitely-absent")) is False


@pytest.mark.parametrize("junk", ["", None, 12345])
def test_junk_repo_argument_does_not_raise(junk):
    assert dsd.deployment_intentionally_disabled(junk) is False


def test_root_vercel_json_holding_a_list_does_not_raise(tmp_path):
    (tmp_path / "vercel.json").write_text("[1, 2, 3]", encoding="utf-8")
    assert dsd.deployment_intentionally_disabled(str(tmp_path)) is False


def test_helpers_tolerate_non_dict_configs():
    for junk in (None, [], "x", 3):
        assert dsd._config_declares_no_deploy(junk) is False
        assert dsd._config_enables_any_branch(junk) is False


def test_read_vercel_json_returns_empty_dict_on_missing(tmp_path):
    assert dsd._read_vercel_json(str(tmp_path / "nope.json")) == {}


def test_subroots_are_configurable_and_non_empty():
    assert dsd.ORCH_DEPLOY_SILENCE_SUBROOTS
    assert "web" in dsd.ORCH_DEPLOY_SILENCE_SUBROOTS
    assert all(s and not s.startswith(" ") for s in dsd.ORCH_DEPLOY_SILENCE_SUBROOTS)


# -- against this repository's own real config -----------------------------


def test_this_repo_is_not_treated_as_no_deploy():
    """Integration guard. Root vercel.json here disables deploys as a
    duplicate-project guard while web/vercel.json enables master. If this ever
    returns True again, deploy silence on the `web` project is invisible."""
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    root = json.loads((open(os.path.join(repo, "vercel.json"), encoding="utf-8")).read())
    assert root["git"]["deploymentEnabled"] is False  # the guard is still in place
    web = json.loads(
        (open(os.path.join(repo, "web", "vercel.json"), encoding="utf-8")).read())
    assert web["git"]["deploymentEnabled"]["master"] is True
    assert dsd.deployment_intentionally_disabled(repo) is False
