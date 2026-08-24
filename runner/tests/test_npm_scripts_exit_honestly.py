"""Regression guard: verification scripts must not mask their own exit code.

Background (canary-codex-28): package.json's ``test`` script was
``pytest ... 2>&1 || true``. Every failing run exited 0, so every downstream
"the build is green" claim in this fleet was unfalsifiable — the canary tasks
that were supposed to verify behavior preservation could not fail.

A script may opt into tolerance explicitly by ending its name with ``:soft``.
Everything else must propagate a non-zero exit status.
"""

import json
import os

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PACKAGE_JSON = os.path.join(REPO_ROOT, "package.json")

# Shell constructs that swallow a non-zero exit status.
_MASKING_TOKENS = ("|| true", "|| :", "|| exit 0", "; true")


def _load_scripts():
    """Return package.json's scripts mapping; fail-soft to {} if unreadable."""
    try:
        with open(PACKAGE_JSON, "r", encoding="utf-8", errors="replace") as fh:
            return json.load(fh).get("scripts", {}) or {}
    except (OSError, ValueError):
        return {}


def test_package_json_is_readable():
    assert _load_scripts(), "package.json must define at least one script"


def test_no_verification_script_masks_its_exit_code():
    offenders = []
    for name, body in _load_scripts().items():
        if name.endswith(":soft"):
            continue  # explicitly opted into tolerance
        for token in _MASKING_TOKENS:
            if token in body:
                offenders.append("{0}: {1!r} contains {2!r}".format(name, body, token))
                break
    assert not offenders, (
        "npm scripts must propagate failure (suffix the name with ':soft' to opt "
        "out deliberately): " + "; ".join(offenders)
    )


def test_test_script_still_runs_pytest():
    """Guard against 'fixing' the mask by deleting the verification itself."""
    scripts = _load_scripts()
    assert "pytest" in scripts.get("test", ""), "npm test must still invoke pytest"
