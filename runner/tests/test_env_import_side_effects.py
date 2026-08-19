"""No NEW test module may override a production-read env var at import time.

pytest imports every test module during collection, before any fixture runs. So a
module-scope `os.environ[K] = v` is not scoped to that file — it rewrites K for every test
that runs afterwards in the same process, and `conftest.py`'s per-test environment restore
cannot undo it (the pollution is already inside the snapshot it takes).

That is not theoretical. Three separate instances cost a full session on 2026-08-18:

  * ORCH_DELIVERY_LEASE_REQUIRED, set by a delivery-lease test and never restored, made
    every later test see `require(None, ...)` raise;
  * ORCH_SHADOW_MODE, left set by tools_live_verify's import-time body, made the release
    canary fail with "shadow mode: promotion withheld" on perfectly good code;
  * SUPABASE_URL / SUPABASE_SERVICE_KEY, hard-assigned at import, repointed the control
    plane for the whole process.

Each looked like a product regression. Each was green standalone and red in the canary.

This test does not try to fix the existing debt in one go — it FREEZES it. The known
offenders are listed below and may only shrink. Anything new fails here, at the point it
is introduced, with an explanation instead of a three-hour bisect.

To fix one: use `os.environ.setdefault(...)` if the module only needs *a* value, or
`monkeypatch.setenv` inside the test if it needs a *specific* one. Then delete its line
from KNOWN_IMPORT_TIME_OVERRIDES.
"""
import ast
import os
import re

_RUNNER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# (env key, module path relative to runner/) — known, pre-existing, may only shrink.
#
# EMPTY, and it should stay that way. All 16 entries were drained in the same change that
# introduced env_during_import.import_with_env / during_import: every one of those modules
# reads its flag at IMPORT time, so the value has to exist before the module under test is
# imported — it just no longer has to survive the import.
KNOWN_IMPORT_TIME_OVERRIDES = set()

_ENV_READ = re.compile(r'environ(?:\.get\(|\[)\s*[\'"]([A-Za-z_][A-Za-z0-9_]*)[\'"]')


def _is_test_module(path):
    return os.path.basename(path).startswith("test_") or f"{os.sep}tests{os.sep}" in path


def _iter_py(directory):
    if not os.path.isdir(directory):
        return
    for name in sorted(os.listdir(directory)):
        if name.endswith(".py"):
            yield os.path.join(directory, name)


def _production_read_keys():
    """Env vars that NON-test runner modules actually read."""
    keys = set()
    for path in _iter_py(_RUNNER):
        if _is_test_module(path):
            continue
        try:
            keys.update(_ENV_READ.findall(open(path, encoding="utf-8").read()))
        except OSError:
            continue
    return keys


def _import_time_assignments(path):
    """Env keys assigned (not setdefault) at module scope."""
    try:
        tree = ast.parse(open(path, encoding="utf-8").read(), filename=path)
    except (SyntaxError, OSError):
        return []
    keys = []
    for node in tree.body:                      # module scope only
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        for sub in ast.walk(node):
            if not isinstance(sub, ast.Assign):
                continue
            for target in sub.targets:
                if (isinstance(target, ast.Subscript)
                        and isinstance(target.value, ast.Attribute)
                        and target.value.attr == "environ"
                        and isinstance(target.slice, ast.Constant)
                        and isinstance(target.slice.value, str)):
                    keys.append(target.slice.value)
    return keys


def _current_overrides():
    production = _production_read_keys()
    found = set()
    for directory in (_RUNNER, os.path.join(_RUNNER, "tests")):
        for path in _iter_py(directory):
            if not _is_test_module(path):
                continue
            rel = os.path.relpath(path, _RUNNER)
            for key in _import_time_assignments(path):
                if key in production:
                    found.add((key, rel))
    return found


def test_no_new_import_time_env_override_of_a_production_key():
    new = _current_overrides() - KNOWN_IMPORT_TIME_OVERRIDES
    assert not new, (
        "these test modules set a production-read env var AT IMPORT, which leaks into every "
        "test collected afterwards and cannot be undone by conftest's per-test restore:\n  "
        + "\n  ".join(f"{key} in {module}" for key, module in sorted(new))
        + "\n\nUse os.environ.setdefault(...) if any value will do, or monkeypatch.setenv "
          "inside the test if a specific one is needed.")


def test_the_baseline_does_not_list_things_that_are_already_fixed():
    """Keeps the allowlist honest: a stale entry hides a regression behind a fixed one."""
    stale = KNOWN_IMPORT_TIME_OVERRIDES - _current_overrides()
    assert not stale, (
        "these are in KNOWN_IMPORT_TIME_OVERRIDES but no longer present — delete them:\n  "
        + "\n  ".join(f"{key} in {module}" for key, module in sorted(stale)))


def test_the_control_plane_credentials_are_never_hard_assigned():
    """The specific case that broke the release canary. Must stay at zero, not baselined."""
    offenders = {(key, module) for key, module in _current_overrides()
                 if key in ("SUPABASE_URL", "SUPABASE_SERVICE_KEY", "SUPABASE_ANON_KEY")}
    assert not offenders, (
        "a test module repoints the control plane for the whole pytest process:\n  "
        + "\n  ".join(f"{key} in {module}" for key, module in sorted(offenders)))


def test_the_detector_sees_a_planted_override(tmp_path):
    """Guards the guard — an empty scan would make all of the above vacuously green."""
    planted = tmp_path / "test_planted.py"
    planted.write_text('import os\nos.environ["ORCH_PLANTED"] = "1"\n')

    assert _import_time_assignments(str(planted)) == ["ORCH_PLANTED"]


def test_the_detector_ignores_assignments_inside_functions(tmp_path):
    """Inside a test body, monkeypatch/env writes are scoped and fine."""
    scoped = tmp_path / "test_scoped.py"
    scoped.write_text('import os\ndef test_x():\n    os.environ["ORCH_SCOPED"] = "1"\n')

    assert _import_time_assignments(str(scoped)) == []


def test_the_detector_ignores_setdefault(tmp_path):
    """setdefault yields to the real environment, which is the recommended fix."""
    soft = tmp_path / "test_soft.py"
    soft.write_text('import os\nos.environ.setdefault("ORCH_SOFT", "1")\n')

    assert _import_time_assignments(str(soft)) == []
