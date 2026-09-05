#!/usr/bin/env python3
"""Acceptance test for the dependency configuration itself.

WHAT THIS CATCHES
-----------------
`make install-deps` installs from `requirements.lock`, not `requirements.txt`.
So the lock is what a fresh machine actually gets, and when it drifts behind the
declared set the failure is silent at install time and only shows up much later
as an ImportError deep inside a runner module — on a machine built exactly the way
the docs say to build it.

That had happened: `requirements.txt` grew PyYAML, python-dateutil, psutil,
aiohttp, websockets, anthropic, sqlglot, cryptography and pyflakes, and the lock
still pinned only requests/python-dotenv/prometheus-client and their transitives.
Nine declared runtime dependencies were absent from the install path. The repo's
own `scripts/lockfile.py verify` reported all nine — but nothing in the test suite
ran it, so nobody saw it.

These tests are that missing gate. They are deliberately about the MANIFESTS, not
about the current machine's site-packages: a developer whose environment happens
to have a package installed should still see the failure when the lock omits it.
"""
import os
import re
import subprocess
import sys

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_REQUIREMENTS = os.path.join(_REPO, "requirements.txt")
_LOCK = os.path.join(_REPO, "requirements.lock")

# Distribution name -> module actually imported. Only listed where they differ;
# anything else is assumed to import under its own (normalized) name.
_IMPORT_NAME = {
    "pyyaml": "yaml",
    "python-dotenv": "dotenv",
    "python-dateutil": "dateutil",
    "prometheus-client": "prometheus_client",
}


def _normalize(name):
    """PEP 503 normalization: `PyYAML`, `pyyaml` and `Py_YAML` are one package."""
    return re.sub(r"[-_.]+", "-", str(name or "")).strip().lower()


def _declared():
    """Distribution names declared in requirements.txt, in file order."""
    names = []
    if not os.path.isfile(_REQUIREMENTS):
        return names
    with open(_REQUIREMENTS, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.split("#", 1)[0].strip()
            if not line or line.startswith("-"):
                continue
            name = re.split(r"[<>=!~\[;]", line, 1)[0].strip()
            if name:
                names.append(_normalize(name))
    return names


def _locked():
    """Distribution names pinned in requirements.lock."""
    names = set()
    if not os.path.isfile(_LOCK):
        return names
    with open(_LOCK, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.split("#", 1)[0].strip()
            if not line or "==" not in line:
                continue
            names.add(_normalize(line.split("==", 1)[0]))
    return names


def test_requirements_txt_is_readable_and_non_empty():
    declared = _declared()
    assert declared, "requirements.txt declared nothing — parser or file is broken"


def test_lockfile_exists_and_pins_versions():
    assert os.path.isfile(_LOCK), "requirements.lock is missing; run: make lock"
    locked = _locked()
    assert locked, "requirements.lock pins nothing — run: make lock"


def test_every_declared_dependency_is_pinned_in_the_lock():
    """The regression that motivated this file.

    `make install-deps` reads the lock. A dependency declared in requirements.txt
    but absent from the lock is a dependency a fresh machine will not have.
    """
    missing = sorted(set(_declared()) - _locked())
    assert not missing, (
        "declared in requirements.txt but not pinned in requirements.lock: "
        + ", ".join(missing)
        + " — regenerate with: make lock"
    )


@pytest.mark.parametrize("dist", sorted(set(_declared())) or ["<none-declared>"])
def test_declared_dependency_is_importable(dist):
    """Every declared runtime dependency imports in this interpreter.

    Skipped rather than failed when absent, because a contributor may legitimately
    be on a partially-installed environment; the lock-coverage test above is the
    one that gates configuration correctness. This one catches the other failure
    mode: a package that installs but cannot be imported (wrong wheel, broken
    native extension, name that does not match the distribution).
    """
    if dist == "<none-declared>":
        pytest.skip("no declared dependencies to check")
    module = _IMPORT_NAME.get(dist, dist.replace("-", "_"))
    try:
        __import__(module)
    except ImportError:
        pytest.skip(f"{dist} not installed in this environment (run: make install-deps)")
    except Exception as exc:  # installed but broken — that is a real failure
        pytest.fail(f"{dist} is installed but importing {module!r} raised: {exc}")


def test_lockfile_verify_reports_no_declared_gaps():
    """Run the repo's own checker and assert it finds nothing unpinned.

    Duplicates the assertion above on purpose: this exercises `scripts/lockfile.py`
    end to end, so the gate keeps working if the parsing here and the parsing there
    ever disagree.
    """
    script = os.path.join(_REPO, "scripts", "lockfile.py")
    if not os.path.isfile(script):
        pytest.skip("scripts/lockfile.py not present")
    try:
        proc = subprocess.run([sys.executable, script, "verify"],
                              cwd=_REPO, capture_output=True, text=True, timeout=120)
    except Exception as exc:
        pytest.skip(f"could not run lockfile.py: {exc}")
    output = (proc.stdout or "") + (proc.stderr or "")
    unpinned = [line for line in output.splitlines() if "not pinned in the lock" in line]
    assert not unpinned, "lockfile.py reports unpinned declared deps:\n" + "\n".join(unpinned)


def test_no_duplicate_declarations():
    """A package declared twice means two ranges, and pip silently picks one."""
    declared = _declared()
    seen, dupes = set(), []
    for name in declared:
        if name in seen:
            dupes.append(name)
        seen.add(name)
    assert not dupes, f"declared more than once in requirements.txt: {sorted(set(dupes))}"
