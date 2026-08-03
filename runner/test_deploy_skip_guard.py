"""Regression tests for the silent-deploy-skip and inert-config detectors.

Incident (illuminati): vercel.json carried an ignoreCommand testing
`$VERCEL_GIT_COMMIT_REF != "main"` on a repository whose default branch is `master`. On
every production push the comparison was true, the command exited 0, and Vercel SKIPPED the
build. A skipped build is recorded as a SUCCESS, so there was no failed deployment, no red
check and no alert — production silently stopped updating for a day.

Second incident: `git.deploymentEnabled: {"*": false}` was written to stop agent branches
deploying. Under minimatch `*` does not cross `/`, so it never matched `agent/foo`. A rule
that matches nothing emits nothing, so the author had no way to learn it was inert.

The clean controls are the point of this file: a deploy gate that cries wolf gets deleted,
so the identical config on a repo whose default branch really IS `main` must stay silent.
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.modules.setdefault("db", type(sys)("db"))
import vercel_config_guard as vcg  # noqa: E402

ILLUMINATI = {"ignoreCommand": 'bash -c \'[ "$VERCEL_GIT_COMMIT_REF" != "main" ]\''}


def _codes(findings):
    return {f["code"] for f in findings}


def git(repo, *args):
    return subprocess.run(["git"] + list(args), cwd=repo, capture_output=True,
                          text=True, timeout=60)


# ------------------------------------------------------------------ minimatch semantics

def test_star_does_not_cross_path_separator():
    """The exact bug: `*` matched `main` but never `agent/foo`."""
    assert vcg.glob_matches("*", "main") is True
    assert vcg.glob_matches("*", "master") is True
    assert vcg.glob_matches("*", "agent/foo") is False
    assert vcg.glob_matches("**", "agent/foo") is True
    assert vcg.glob_matches("agent/*", "agent/foo") is True
    assert vcg.glob_matches("agent/*", "agent/foo/bar") is False


# ------------------------------------------------------------------ ignoreCommand skips

def test_illuminati_ignore_command_blocks_on_master_repo():
    findings = vcg.check_deploy_skip(".", ".", ILLUMINATI, "master")
    assert "ignore_command_skips_default_branch" in _codes(findings)
    f = findings[0]
    assert f["severity"] == "block"
    assert "master" in f["detail"]
    assert "exit 0" in f["detail"], "the finding must explain that exit 0 means SKIP"
    assert "SUCCESS" in f["detail"], "and that a skip is recorded as a success"


def test_every_ignore_command_dialect_is_recognised():
    for cmd in ('bash -c \'[ "$VERCEL_GIT_COMMIT_REF" != "main" ]\'',
                'if [ "$VERCEL_GIT_COMMIT_REF" == "main" ]; then exit 1; fi; exit 0',
                '[ "${VERCEL_GIT_COMMIT_REF}" != "production" ]',
                '[ "main" != "$VERCEL_GIT_COMMIT_REF" ]',
                'test "$VERCEL_GIT_COMMIT_REF" = "release"'):
        findings = vcg.check_deploy_skip(".", ".", {"ignoreCommand": cmd}, "master")
        assert "ignore_command_skips_default_branch" in _codes(findings), cmd


def test_clean_control_same_config_where_default_is_main():
    """THE false-positive control: identical config, correct default branch."""
    assert vcg.check_deploy_skip(".", ".", ILLUMINATI, "main") == []


def test_clean_control_ignore_command_names_the_real_default():
    cfg = {"ignoreCommand": '[ "$VERCEL_GIT_COMMIT_REF" != "master" ]'}
    assert vcg.check_deploy_skip(".", ".", cfg, "master") == []


def test_clean_control_glob_covering_default_branch():
    cfg = {"ignoreCommand": '[ "$VERCEL_GIT_COMMIT_REF" != "mast*" ]'}
    assert vcg.check_deploy_skip(".", ".", cfg, "master") == []


def test_clean_control_non_branch_ignore_command():
    """A path-based ignoreCommand says nothing about branches and must be left alone."""
    cfg = {"ignoreCommand": "git diff --quiet HEAD^ HEAD ./docs"}
    assert vcg.check_deploy_skip(".", ".", cfg, "master") == []


def test_clean_control_no_ignore_command():
    assert vcg.check_deploy_skip(".", ".", {}, "master") == []


# ------------------------------------------------------------- deploymentEnabled disables

def test_inconsistent_map_disabling_default_branch_blocks():
    """The accidental shape: other branches deploy, the default one silently does not."""
    cfg = {"git": {"deploymentEnabled": {"master": False, "staging": True}}}
    findings = vcg.check_deploy_skip(".", ".", cfg, "master")
    assert "deployment_disabled_for_default_branch" in _codes(findings)
    assert [f for f in findings if f["severity"] == "block"]


def test_disabled_via_matching_glob_while_others_enabled_blocks():
    cfg = {"git": {"deploymentEnabled": {"*": False, "release/**": True}}}
    findings = vcg.check_deploy_skip(".", ".", cfg, "master")
    assert "deployment_disabled_for_default_branch" in _codes(findings), \
        "`*` DOES match a top-level branch name like master"


def test_blanket_disable_is_advisory_not_blocking():
    """A repo that deliberately never deploys must not have its merges quarantined.

    The orchestrator's own vercel.json says exactly this. Blocking it would stop the merge
    train on a correctly configured project — a guard doing more damage than the bug.
    """
    for cfg in ({"git": {"deploymentEnabled": False}},
                {"git": {"deploymentEnabled": {"*": False}}}):
        findings = vcg.check_deploy_skip(".", ".", cfg, "master")
        assert "deployment_disabled_everywhere" in _codes(findings)
        assert not [f for f in findings if f["severity"] == "block"], \
            "a deliberate global opt-out must stay advisory"


def test_clean_control_deployment_enabled_true():
    cfg = {"git": {"deploymentEnabled": {"master": True, "agent/**": False}}}
    assert vcg.check_deploy_skip(".", ".", cfg, "master") == []


def test_clean_control_agent_glob_does_not_touch_default():
    cfg = {"git": {"deploymentEnabled": {"agent/**": False}}}
    assert vcg.check_deploy_skip(".", ".", cfg, "master") == []


# ----------------------------------------------------------------- inert config rules

def _repo_with_branches(tmp_path, branches):
    repo = tmp_path / "r"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "master")
    git(repo, "config", "user.email", "t@t.t")
    git(repo, "config", "user.name", "t")
    (repo / "f.txt").write_text("x\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "base")
    for b in branches:
        git(repo, "branch", b)
    return repo


def test_star_rule_that_matches_no_agent_branch_is_reported(tmp_path):
    """The author believed `{"*": false}` disabled agent/*; it matched none of them."""
    repo = _repo_with_branches(tmp_path, ["agent/foo", "agent/bar"])
    # Leave ONLY slash-bearing branches, so `*` provably matches nothing. master has to be
    # checked out of first — git refuses to delete the branch HEAD points at.
    git(repo, "checkout", "-q", "agent/foo")
    git(repo, "branch", "-D", "master")
    assert "master" not in vcg._branch_names(str(repo))
    cfg = {"git": {"deploymentEnabled": {"*": False}}}
    findings = vcg.check_config_noop(str(repo), str(repo), cfg)
    assert "config_rule_matches_nothing" in _codes(findings)
    detail = findings[0]["detail"]
    assert "minimatch" in detail, "the finding must explain WHY the rule is inert"
    assert "**" in findings[0]["fix"], "and suggest the pattern that would work"


def test_clean_control_rule_that_matches_real_branches(tmp_path):
    repo = _repo_with_branches(tmp_path, ["agent/foo"])
    cfg = {"git": {"deploymentEnabled": {"agent/**": False, "master": True}}}
    assert vcg.check_config_noop(str(repo), str(repo), cfg) == []


def test_clean_control_no_deployment_enabled_key(tmp_path):
    repo = _repo_with_branches(tmp_path, [])
    assert vcg.check_config_noop(str(repo), str(repo), {}) == []


def test_default_branch_detection(tmp_path):
    repo = _repo_with_branches(tmp_path, [])
    assert vcg._default_branch(str(repo)) == "master"


def test_deploy_silence_honours_a_deliberate_opt_out(tmp_path):
    """A repo configured never to deploy must not be alerted about forever.

    An alert that is always on is the same as no alert — which is the failure mode this
    whole class is about.
    """
    import deploy_silence_detector as dsd
    repo = tmp_path / "r"
    repo.mkdir()
    (repo / "vercel.json").write_text('{"git": {"deploymentEnabled": false}}')
    assert dsd.deployment_intentionally_disabled(str(repo)) is True
    assert dsd.evaluate({"repo_path": str(repo), "name": "x", "prod_branch": "master"}) is None

    (repo / "vercel.json").write_text('{"git": {"deploymentEnabled": {"master": true}}}')
    assert dsd.deployment_intentionally_disabled(str(repo)) is False

    (repo / "vercel.json").write_text('{"buildCommand": "npm run build"}')
    assert dsd.deployment_intentionally_disabled(str(repo)) is False


def test_blocking_codes_are_registered():
    """A detector that is not in BLOCKING is advisory and will be merged past."""
    assert "ignore_command_skips_default_branch" in vcg.BLOCKING
    assert "deployment_disabled_for_default_branch" in vcg.BLOCKING
    assert "config_rule_matches_nothing" not in vcg.BLOCKING, \
        "a rule for a not-yet-created branch is legitimate; this stays advisory"
