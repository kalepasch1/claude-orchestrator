#!/usr/bin/env python3
"""The auto-approval deny-list must cover files at the repo root.

THE DEFECT
----------
Every pattern in SENSITIVE_PATHS is written `*/something*`, and fnmatch's `*/` requires
a directory component. A file at the REPO ROOT therefore matched nothing:

    src/auth.py  -> sensitive
    auth.py      -> NOT sensitive     <-- eligible for auto-approve and auto-merge
    app/.env     -> sensitive
    .env         -> NOT sensitive

Verified against the shipped list before the fix: `.env`, `auth.py`, `secrets.py`,
`security.py`, `migration.sql` and `token.py` at the repo root all returned False. This
repo has root-level modules — CI compiles `*.py` there — so a change to a root-level
auth or secrets file could be auto-approved and merged without a human seeing it.

Widening a deny-list can only move a file from "auto-approve" to "ask a human", which
is the direction this gate should err.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import approval_merge as am  # noqa: E402


# ── the regression: root-level files ────────────────────────────────────────

@pytest.mark.parametrize("path", [
    ".env",
    ".env.local",
    ".env.production",
    "auth.py",
    "login.py",
    "password.py",
    "token.py",
    "oauth.py",
    "secrets.py",
    "security.py",
    "policy.py",
    "permission.py",
    "migration.sql",
    "schema.sql",
    "compliance.md",
    "legal.md",
    "privacy.md",
    "gdpr.md",
    "pricing.py",
    "rls.sql",
])
def test_a_sensitive_file_at_the_repo_root_is_caught(path):
    assert am._path_is_sensitive(path) is True, path


@pytest.mark.parametrize("path", [
    "src/auth.py", "app/.env", "server/api/token.ts", "db/migrations/001.sql",
    "packages/x/src/security/rls.ts",
])
def test_nested_sensitive_files_are_still_caught(path):
    """The behaviour that already worked must not regress."""
    assert am._path_is_sensitive(path) is True, path


def test_a_leading_dot_slash_does_not_hide_a_dotfile():
    """`lstrip('./')` strips a character SET — it turned '.env' into 'env'."""
    assert am._path_is_sensitive("./.env") is True
    assert am._path_is_sensitive(".env") is True


def test_matching_is_case_insensitive():
    for path in ("Schema.SQL", "AUTH.PY", "src/Security.ts", ".ENV"):
        assert am._path_is_sensitive(path) is True, path


# ── ordinary files still pass ───────────────────────────────────────────────

@pytest.mark.parametrize("path", [
    "README.md",
    "package.json",
    "runner/db.py",
    "docs/guide.md",
    "src/index.ts",
    "tests/test_math.py",
    "app/components/Button.vue",
])
def test_an_ordinary_file_is_not_sensitive(path):
    """A deny-list that matches everything is the same as no auto-approval at all."""
    assert am._path_is_sensitive(path) is False, path


# ── fail-safe on bad input ──────────────────────────────────────────────────

@pytest.mark.parametrize("value", [None, "", "   ", 42, [], "./"])
def test_an_unreadable_entry_is_treated_as_sensitive(value):
    """Matches how the callers already handle uncertainty: err toward a human."""
    assert am._path_is_sensitive(value) is True


# ── through the caller ──────────────────────────────────────────────────────

def test_touches_sensitive_paths_flags_a_root_level_env(monkeypatch):
    class Result:
        returncode = 0
        stdout = ".env\nREADME.md\n"

    monkeypatch.setattr(am.subprocess, "run", lambda *a, **k: Result())
    assert am._touches_sensitive_paths("/repo", "agent/x", "master") is True


def test_touches_sensitive_paths_passes_an_ordinary_diff(monkeypatch):
    class Result:
        returncode = 0
        stdout = "README.md\nrunner/db.py\n"

    monkeypatch.setattr(am.subprocess, "run", lambda *a, **k: Result())
    assert am._touches_sensitive_paths("/repo", "agent/x", "master") is False


def test_an_empty_diff_is_not_sensitive(monkeypatch):
    class Result:
        returncode = 0
        stdout = ""

    monkeypatch.setattr(am.subprocess, "run", lambda *a, **k: Result())
    assert am._touches_sensitive_paths("/repo", "agent/x", "master") is False


def test_a_failed_git_call_errs_toward_sensitive(monkeypatch):
    class Result:
        returncode = 1
        stdout = ""

    monkeypatch.setattr(am.subprocess, "run", lambda *a, **k: Result())
    assert am._touches_sensitive_paths("/repo", "agent/x", "master") is True


def test_an_exception_errs_toward_sensitive(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("git exploded")

    monkeypatch.setattr(am.subprocess, "run", boom)
    assert am._touches_sensitive_paths("/repo", "agent/x", "master") is True
