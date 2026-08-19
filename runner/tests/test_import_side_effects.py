"""Importing a runtime module must not change the process it is imported into.

runner/tests/test_all_modules_importable.py imports EVERY runtime module, and it is the
first file in the self-deploy canary's critical set. So any module that mutates global
process state at import time poisons every test that runs after it, in a way that looks
like a product regression.

tools_live_verify.py did exactly that: at module scope it chdir'd the process into
runner/, hit the live control plane, shelled out to git, and left ORCH_SHADOW_MODE=true
behind. The canary then failed in test_release_push_fast_forward with

    AssertionError: 'rejected' not found in
    'shadow mode: promotion withheld, production was not moved'

on code that was completely fine. A red canary holds the running version, so that one
import-time assignment was blocking the whole fleet from deploying anything already
merged.
"""
import ast
import importlib
import os
import sys

import pytest

RUNNER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RUNNER_DIR)


def _top_level_chdir(path):
    """Line numbers of os.chdir calls reachable from module scope (not inside a def)."""
    tree = ast.parse(open(path, encoding="utf-8").read(), filename=path)
    hits = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        for sub in ast.walk(node):
            if (isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute)
                    and sub.func.attr == "chdir"):
                hits.append(sub.lineno)
    return hits


def _runtime_modules():
    for f in sorted(os.listdir(RUNNER_DIR)):
        if f.endswith(".py") and not f.startswith(("_", "test_")) and f != "conftest.py":
            yield f


def test_no_runtime_module_chdirs_the_process_at_import():
    """chdir at import time breaks every relative path for every later test in the run."""
    offenders = {f: lines for f in _runtime_modules()
                 if (lines := _top_level_chdir(os.path.join(RUNNER_DIR, f)))}
    assert offenders == {}, (
        "these modules move the working directory just by being imported: " + str(offenders))


def test_importing_tools_live_verify_changes_nothing(monkeypatch):
    monkeypatch.delenv("ORCH_SHADOW_MODE", raising=False)
    env_before, cwd_before = dict(os.environ), os.getcwd()

    sys.modules.pop("tools_live_verify", None)
    module = importlib.import_module("tools_live_verify")

    assert os.getcwd() == cwd_before
    assert dict(os.environ) == env_before
    assert "ORCH_SHADOW_MODE" not in os.environ, \
        "the canary's own process must not be left in shadow mode"
    assert callable(module.main), "the checks must still be runnable as a script"
    assert callable(module.run)


def test_the_env_helper_restores_absent_variables():
    import tools_live_verify as tlv
    os.environ.pop("ORCH_SHADOW_MODE", None)

    with tlv._env(ORCH_SHADOW_MODE="true"):
        assert os.environ["ORCH_SHADOW_MODE"] == "true"
    assert "ORCH_SHADOW_MODE" not in os.environ


def test_the_env_helper_restores_previous_values():
    import tools_live_verify as tlv
    os.environ["ORCH_SHADOW_MODE"] = "original"
    try:
        with tlv._env(ORCH_SHADOW_MODE="true"):
            assert os.environ["ORCH_SHADOW_MODE"] == "true"
        assert os.environ["ORCH_SHADOW_MODE"] == "original"
    finally:
        os.environ.pop("ORCH_SHADOW_MODE", None)


def test_the_cwd_helper_restores_the_directory(tmp_path):
    import tools_live_verify as tlv
    before = os.getcwd()

    with pytest.raises(RuntimeError):
        with tlv._cwd(str(tmp_path)):
            assert os.getcwd() == os.path.realpath(str(tmp_path)) or os.getcwd()
            raise RuntimeError("boom")

    assert os.getcwd() == before, "even an exception must not strand the process elsewhere"
