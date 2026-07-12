#!/usr/bin/env python3
"""
source_config_test_validator.py - validates that source config entries
(project test_cmd, build_cmd, repo_path) are consistent and functional.

Checks:
  1. repo_path is resolvable on this host
  2. test_cmd executable exists in the expected location
  3. build_cmd executable exists in the expected location
  4. npm/node available if test_cmd or build_cmd uses npm

Env vars:
    ORCH_SOURCE_CONFIG_VALIDATOR  "true" (default) to enable
"""
import os, sys, shutil, subprocess

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import log as _log_mod
_log = _log_mod.get("source_config_test_validator")
import db


ENABLED = os.environ.get("ORCH_SOURCE_CONFIG_VALIDATOR", "true").lower() in ("1", "true", "yes", "on")


def validate_project(project):
    """Validate a single project's source config. Returns list of {field, issue} dicts."""
    issues = []
    if not project:
        return [{"field": "project", "issue": "project is None"}]

    pid = project.get("id", "?")
    repo = db.localize_repo_path(project.get("repo_path", ""))

    # 1. repo_path
    if not repo or not os.path.isdir(repo):
        issues.append({"field": "repo_path", "issue": f"not resolvable on this host: {repo}"})
    else:
        git_dir = os.path.join(repo, ".git")
        if not os.path.exists(git_dir):
            issues.append({"field": "repo_path", "issue": f"exists but not a git repo: {repo}"})

    # 2. test_cmd
    test_cmd = project.get("test_cmd", "")
    if test_cmd:
        _validate_cmd(test_cmd, repo, "test_cmd", issues)
    else:
        issues.append({"field": "test_cmd", "issue": "empty or missing"})

    # 3. build_cmd
    build_cmd = project.get("build_cmd", "")
    if build_cmd:
        _validate_cmd(build_cmd, repo, "build_cmd", issues)

    return issues


def _validate_cmd(cmd, repo, field, issues):
    """Check that the first token of cmd is an available executable."""
    parts = cmd.strip().split()
    if not parts:
        issues.append({"field": field, "issue": "empty command"})
        return

    exe = parts[0]
    if not shutil.which(exe):
        issues.append({"field": field, "issue": f"executable '{exe}' not found in PATH"})

    # npm --prefix <dir> check
    if exe == "npm" and "--prefix" in parts:
        idx = parts.index("--prefix")
        if idx + 1 < len(parts) and repo and os.path.isdir(repo):
            prefix_dir = os.path.join(repo, parts[idx + 1])
            pkg_json = os.path.join(prefix_dir, "package.json")
            if not os.path.isfile(pkg_json):
                issues.append({"field": field, "issue": f"package.json missing at {prefix_dir}"})


def validate_all():
    """Validate all projects. Returns {project_id: [issues]}."""
    if not ENABLED:
        _log.info("source config validator disabled")
        return {}

    projects = db.select("projects", {"select": "*"}) or []
    results = {}
    for p in projects:
        issues = validate_project(p)
        if issues:
            results[p["id"]] = issues
            _log.warning("project %s (%s): %d config issues", p.get("name"), p["id"], len(issues))
            for iss in issues:
                _log.warning("  %s: %s", iss["field"], iss["issue"])
        else:
            _log.info("project %s (%s): config OK", p.get("name"), p["id"])
    return results


# --- Tests ---
def test_validate_project_happy_path():
    """Valid project with resolvable repo returns no issues."""
    import tempfile, json
    with tempfile.TemporaryDirectory() as td:
        os.makedirs(os.path.join(td, ".git"))
        os.makedirs(os.path.join(td, "web"))
        with open(os.path.join(td, "web", "package.json"), "w") as f:
            json.dump({"name": "test"}, f)
        proj = {"id": "test-1", "repo_path": td, "test_cmd": "echo ok", "build_cmd": "echo ok"}
        # Monkey-patch localize to identity
        orig = db.localize_repo_path
        db.localize_repo_path = lambda p: p
        try:
            issues = validate_project(proj)
            assert issues == [], f"Expected no issues, got {issues}"
        finally:
            db.localize_repo_path = orig


def test_validate_project_missing_repo():
    """Missing repo_path is flagged."""
    proj = {"id": "test-2", "repo_path": "/nonexistent/path/xyz", "test_cmd": "echo ok"}
    orig = db.localize_repo_path
    db.localize_repo_path = lambda p: p
    try:
        issues = validate_project(proj)
        assert any(i["field"] == "repo_path" for i in issues), f"Expected repo_path issue, got {issues}"
    finally:
        db.localize_repo_path = orig


def test_validate_project_empty_test_cmd():
    """Empty test_cmd is flagged."""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        os.makedirs(os.path.join(td, ".git"))
        proj = {"id": "test-3", "repo_path": td, "test_cmd": ""}
        orig = db.localize_repo_path
        db.localize_repo_path = lambda p: p
        try:
            issues = validate_project(proj)
            assert any(i["field"] == "test_cmd" for i in issues)
        finally:
            db.localize_repo_path = orig


def test_validate_project_none():
    """None project returns an issue."""
    issues = validate_project(None)
    assert len(issues) == 1 and issues[0]["field"] == "project"


if __name__ == "__main__":
    # Run inline tests
    test_validate_project_happy_path()
    test_validate_project_missing_repo()
    test_validate_project_empty_test_cmd()
    test_validate_project_none()
    print("All source_config_test_validator tests passed")
    # Then run the real validation
    results = validate_all()
    if results:
        print(f"\n{len(results)} project(s) with config issues")
    else:
        print("\nAll projects config OK")
