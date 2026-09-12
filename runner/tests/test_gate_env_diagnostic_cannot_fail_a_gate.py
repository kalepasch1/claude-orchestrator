"""gate_env's own diagnostic line must not be able to fail the gate that calls it.

The fleet named this frame itself, at 2026-09-03 16:40:02Z, once release_train
started recording tracebacks instead of only `str(exc)`:

    gate_env.py, line 63, in gate_env
        print(f"[gate-env] node not on PATH; prepending {nb}", flush=True)
    BrokenPipeError: [Errno 32] Broken pipe

release_train's QA block catches Exception, so that print became
"staging QA failed (tests required)" on a suite that had not run. gate_env() is
called by every gate that shells out, which is why the guard is installed here
rather than only in the two trains -- build_gate and clean_clone_gate run as
their own processes and never reach release_train.run().
"""
import io
import os

import gate_env
import stdio_guard


class DeadPipe(io.TextIOBase):
    """A stream that behaves like stdout with no reader: writes raise EPIPE."""

    def write(self, data):
        raise BrokenPipeError(32, "Broken pipe")

    def flush(self):
        raise BrokenPipeError(32, "Broken pipe")

    def writable(self):
        return True


def test_gate_env_survives_a_dead_stdout(monkeypatch, tmp_path):
    monkeypatch.setattr(stdio_guard, "_installed", False)
    monkeypatch.setenv("ORCH_STDIO_FALLBACK", str(tmp_path / "fallback.log"))
    monkeypatch.setattr("sys.stdout", DeadPipe())
    gate_env.reset_cache()
    # Force the branch that prints: a PATH with no npm in it.
    monkeypatch.setenv("PATH", "/nonexistent-for-this-test")
    monkeypatch.setattr(gate_env, "node_bin_dir", lambda: "/opt/homebrew/bin")

    env = gate_env.gate_env()          # must not raise

    assert env["PATH"].startswith("/opt/homebrew/bin")
    assert (tmp_path / "fallback.log").exists()
    assert "[gate-env] node not on PATH" in (tmp_path / "fallback.log").read_text()


def test_gate_env_still_returns_a_usable_environment(monkeypatch):
    """The guard must not change what gate_env is for."""
    monkeypatch.setattr(stdio_guard, "_installed", False)
    gate_env.reset_cache()
    monkeypatch.setattr(gate_env, "node_bin_dir", lambda: "/opt/homebrew/bin")
    env = gate_env.gate_env()
    assert "/opt/homebrew/bin" in env["PATH"].split(os.pathsep)
    assert env.get("HOME") == os.environ.get("HOME")


def test_a_base_environment_is_still_extended_not_replaced(monkeypatch):
    monkeypatch.setattr(stdio_guard, "_installed", False)
    gate_env.reset_cache()
    monkeypatch.setattr(gate_env, "node_bin_dir", lambda: "/opt/homebrew/bin")
    env = gate_env.gate_env({"PATH": "/usr/bin", "NODE_ENV": "test"})
    assert env["NODE_ENV"] == "test"
    assert env["PATH"].startswith("/opt/homebrew/bin")


def test_the_guard_being_unimportable_does_not_break_the_gate(monkeypatch):
    """A guard that cannot load must not take the gate down with it."""
    import builtins
    real_import = builtins.__import__

    def refuse(name, *args, **kwargs):
        if name == "stdio_guard":
            raise ImportError("simulated")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", refuse)
    gate_env.reset_cache()
    env = gate_env.gate_env()
    assert isinstance(env, dict) and "PATH" in env
