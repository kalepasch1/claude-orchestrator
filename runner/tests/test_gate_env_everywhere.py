"""Every gate that runs a project's own command must get node on PATH.

2026-09-01: every merge-train TESTFAIL on this host was `bash: npm: command not found`.
The gates shell out with `bash -lc`, which sources ~/.bash_profile -- but nvm is
initialised in ~/.zshrc here, so a login bash never sees node, and under launchd there is
no interactive shell at all. Working code was marked TESTFAIL for an environment fault,
burned its redo cap and was abandoned.

The fix went into merge_train._gate_env() and was wired into merge_train's own suite call
and nowhere else. Measured 2026-09-02, the day after: `[gate-env] node not on PATH` had
fired 15 times AND `bash: npm: command not found` had appeared 14 more times in the same
log -- every one prefixed `overlay:<sha>`, which is release_train's return shape, from a
`bash -lc` that never received the repaired environment.

Reproduced on this host under launchd's PATH:

    bash -lc 'npm --version'   [inherited PATH]   rc=127  bash: npm: command not found
    bash -lc 'npm --version'   [gate env]         rc=0    11.19.0

The structural tests below are the point of this file: they fail if a new project-command
shell-out is added without the environment, which is exactly how the first fix ended up
covering one caller out of five.
"""
import os
import re
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import gate_env  # noqa: E402

RUNNER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GATED_MODULES = ("merge_train.py", "release_train.py", "build_gate.py")


def _source(name):
    with open(os.path.join(RUNNER, name)) as fh:
        return fh.read()


@pytest.mark.parametrize("module", GATED_MODULES)
def test_every_bash_lc_call_passes_an_env(module):
    """The regression that let this ship half-done."""
    src = _source(module)
    missing = []
    for m in re.finditer(r'subprocess\.run\(\["bash", "-lc"', src):
        # the call ends at the first ")" that closes it; scan a generous window
        window = src[m.start():m.start() + 500]
        depth, end = 0, len(window)
        for i, ch in enumerate(window):
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        call = window[:end]
        if "env=" not in call:
            line = src[:m.start()].count("\n") + 1
            missing.append("%s:%d" % (module, line))
    assert not missing, "bash -lc without env=: " + ", ".join(missing)


@pytest.mark.parametrize("module", GATED_MODULES)
def test_the_gated_modules_import_gate_env(module):
    assert re.search(r"^import gate_env", _source(module), re.M), module


def test_build_gate_no_longer_reaches_into_merge_train_for_its_path():
    """It used to `import merge_train` and fall back to env=None on any exception."""
    src = _source("build_gate.py")
    assert "merge_train._gate_env" not in src
    assert "_env = None" not in src


def test_merge_train_gate_env_is_the_shared_one():
    import merge_train
    gate_env.reset_cache()
    assert merge_train._gate_env() is gate_env.gate_env()


def test_merge_train_node_bin_dir_is_the_shared_one():
    import merge_train
    assert merge_train._node_bin_dir() == gate_env.node_bin_dir()


def test_node_bin_dir_honours_an_explicit_override(tmp_path, monkeypatch):
    (tmp_path / "npm").write_text("#!/bin/sh\n")
    monkeypatch.setenv("ORCH_NODE_BIN", str(tmp_path))
    assert gate_env.node_bin_dir() == str(tmp_path)


def test_an_override_without_npm_in_it_is_ignored(tmp_path, monkeypatch):
    monkeypatch.setenv("ORCH_NODE_BIN", str(tmp_path))
    assert gate_env.node_bin_dir() != str(tmp_path)


def test_gate_env_prepends_the_node_bin_dir(tmp_path, monkeypatch):
    (tmp_path / "npm").write_text("#!/bin/sh\n")
    monkeypatch.setenv("ORCH_NODE_BIN", str(tmp_path))
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    gate_env.reset_cache()
    env = gate_env.gate_env()
    assert env["PATH"].split(os.pathsep)[0] == str(tmp_path)
    gate_env.reset_cache()


def test_gate_env_does_not_duplicate_an_entry_already_on_path(tmp_path, monkeypatch):
    (tmp_path / "npm").write_text("#!/bin/sh\n")
    monkeypatch.setenv("ORCH_NODE_BIN", str(tmp_path))
    monkeypatch.setenv("PATH", str(tmp_path) + ":/usr/bin")
    gate_env.reset_cache()
    env = gate_env.gate_env()
    assert env["PATH"].count(str(tmp_path)) == 1
    gate_env.reset_cache()


def test_gate_env_extends_a_caller_supplied_base(tmp_path, monkeypatch):
    (tmp_path / "npm").write_text("#!/bin/sh\n")
    monkeypatch.setenv("ORCH_NODE_BIN", str(tmp_path))
    gate_env.reset_cache()
    env = gate_env.gate_env({"PATH": "/usr/bin", "NODE_ENV": "test"})
    assert env["NODE_ENV"] == "test"
    assert env["PATH"].split(os.pathsep)[0] == str(tmp_path)
    gate_env.reset_cache()


def test_a_caller_supplied_base_is_not_cached(tmp_path, monkeypatch):
    (tmp_path / "npm").write_text("#!/bin/sh\n")
    monkeypatch.setenv("ORCH_NODE_BIN", str(tmp_path))
    gate_env.reset_cache()
    gate_env.gate_env({"PATH": "/usr/bin", "MARK": "one"})
    assert "MARK" not in gate_env.gate_env()
    gate_env.reset_cache()


def test_missing_node_leaves_path_alone(tmp_path, monkeypatch):
    monkeypatch.setenv("ORCH_NODE_BIN", str(tmp_path / "nope"))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("PATH", "/nowhere")
    gate_env.reset_cache()
    env = gate_env.gate_env()
    assert env["PATH"] in ("/nowhere", "/opt/homebrew/bin:/nowhere", "/usr/local/bin:/nowhere")
    gate_env.reset_cache()


@pytest.mark.skipif(not gate_env.node_bin_dir(), reason="no node on this host")
def test_the_repaired_environment_actually_finds_npm():
    """The end-to-end claim, run for real."""
    gate_env.reset_cache()
    env = dict(gate_env.gate_env())
    env["PATH"] = gate_env.node_bin_dir() + ":/usr/bin:/bin"
    r = subprocess.run(["bash", "-lc", "npm --version"], capture_output=True,
                       text=True, timeout=60, env=env)
    assert r.returncode == 0, (r.stdout or "") + (r.stderr or "")
    gate_env.reset_cache()
