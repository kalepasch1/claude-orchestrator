#!/usr/bin/env python3
"""The dependency manifest must be honest in BOTH directions.

`scripts/verify_deps.py` only checks declared -> importable. Nothing checked
imported -> declared, so four third-party packages that `runner/` imports behind
`try/except ImportError` guards were named nowhere in the repo: an operator who
wanted the redis queue or the websocket config transport had to trigger the
ImportError to find out what to install.

requirements-optional.txt is that missing declaration. These tests pin it to the
actual guarded imports so the two cannot drift apart again.
"""
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Guarded third-party import -> (module that imports it, distribution name).
GUARDED_OPTIONAL_IMPORTS = {
    "redis": ("runner/task_queue_interface.py", "redis"),
    "websocket": ("runner/ws_config_transport.py", "websocket-client"),
    "claude_agent_sdk": ("runner/claude_cli.py", "claude-agent-sdk"),
    "git": ("scripts/delete_remote_branches.py", "gitpython"),
}


def _declared(manifest_name):
    """Distribution names declared in a requirements file, lowercased."""
    path = REPO_ROOT / manifest_name
    if not path.is_file():
        return set()
    names = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        names.add(re.split(r"[><=~\[]", line, 1)[0].strip().lower())
    return names


def test_optional_manifest_exists():
    assert (REPO_ROOT / "requirements-optional.txt").is_file()


def test_every_guarded_import_is_declared_optional():
    declared = _declared("requirements-optional.txt")
    for module, (_owner, dist) in GUARDED_OPTIONAL_IMPORTS.items():
        assert dist.lower() in declared, (
            f"{module} is imported by {_owner} but not declared in "
            f"requirements-optional.txt")


def test_guarded_imports_still_live_where_we_claim():
    """If a module moves, this test fails instead of the manifest going stale."""
    for module, (owner, _dist) in GUARDED_OPTIONAL_IMPORTS.items():
        path = REPO_ROOT / owner
        assert path.is_file(), f"{owner} no longer exists; update the manifest"
        assert module in path.read_text(encoding="utf-8"), \
            f"{owner} no longer imports {module}; update requirements-optional.txt"


def test_optional_deps_are_not_also_required():
    """Optional means optional — a package here must not be in requirements.txt."""
    required = _declared("requirements.txt")
    for dist in _declared("requirements-optional.txt"):
        assert dist not in required, \
            f"{dist} is declared both required and optional"


def test_pytz_is_declared_for_the_test_that_imports_it():
    assert "pytz" in _declared("requirements-dev.txt")


def test_existing_required_pins_are_untouched():
    """This change adds declarations only; the runtime manifest must not move."""
    required = _declared("requirements.txt")
    for dist in ("requests", "python-dotenv", "prometheus-client", "pyyaml",
                 "python-dateutil", "psutil", "aiohttp", "websockets",
                 "anthropic", "sqlglot", "cryptography", "pyflakes"):
        assert dist in required, f"{dist} disappeared from requirements.txt"


def test_verify_deps_does_not_read_the_optional_manifest():
    """Optional deps must not be able to fail the required-deps acceptance check."""
    src = (REPO_ROOT / "scripts" / "verify_deps.py").read_text(encoding="utf-8")
    assert "requirements-optional.txt" not in src
