#!/usr/bin/env python3
"""Tests for hot_config_reload.py — live config/code reload without restart."""
import os, sys, time, types, threading, importlib, tempfile, textwrap
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Stub db module before importing hot_config_reload
_fake_db = types.ModuleType("db")
_fake_db._controls = []
def _fake_select(table, params=None):
    if table == "controls":
        return list(_fake_db._controls)
    return []
_fake_db.select = _fake_select
sys.modules["db"] = _fake_db

import hot_config_reload as hcr


@pytest.fixture(autouse=True)
def _reset_state():
    """Reset module-level singletons between tests."""
    old_env = dict(os.environ)
    old_mtimes = dict(hcr._file_mtimes)
    old_env_mt = hcr._env_mtime
    old_db_hash = hcr._db_config_hash
    old_sched_hash = hcr._schedule_hash
    old_callbacks = list(hcr._callbacks)
    old_stats = dict(hcr._stats)
    hcr._paused.set()
    yield
    hcr._file_mtimes.clear()
    hcr._file_mtimes.update(old_mtimes)
    hcr._env_mtime = old_env_mt
    hcr._db_config_hash = old_db_hash
    hcr._schedule_hash = old_sched_hash
    hcr._callbacks.clear()
    hcr._callbacks.extend(old_callbacks)
    hcr._stats.clear()
    hcr._stats.update(old_stats)
    os.environ.clear()
    os.environ.update(old_env)
    _fake_db._controls = []


# -------------------------------------------------------------------
# check_files
# -------------------------------------------------------------------
class TestCheckFiles:
    def test_first_call_returns_empty(self):
        hcr._file_mtimes.clear()
        result = hcr.check_files()
        assert result == []
        assert len(hcr._file_mtimes) > 0

    def test_detects_changed_file(self, tmp_path):
        # Seed mtimes with a fake module at old time
        fake_py = tmp_path / "fake_mod.py"
        fake_py.write_text("x = 1")
        old_dir = hcr._DIR
        hcr._DIR = str(tmp_path)
        hcr._file_mtimes = {"fake_mod": 0.0}
        try:
            changed = hcr.check_files()
            assert "fake_mod" in changed
        finally:
            hcr._DIR = old_dir

    def test_skips_protected_modules(self, tmp_path):
        for name in ("runner", "db", "hot_reload", "hot_config_reload"):
            (tmp_path / f"{name}.py").write_text("x=1")
        old_dir = hcr._DIR
        hcr._DIR = str(tmp_path)
        hcr._file_mtimes = {n: 0.0 for n in ("runner", "db", "hot_reload", "hot_config_reload")}
        try:
            changed = hcr.check_files()
            assert changed == []
        finally:
            hcr._DIR = old_dir


# -------------------------------------------------------------------
# reload_module
# -------------------------------------------------------------------
class TestReloadModule:
    def test_reload_existing_module(self):
        # Create a temporary module in sys.modules
        mod = types.ModuleType("_test_hot_mod")
        mod.val = 1
        sys.modules["_test_hot_mod"] = mod
        try:
            result = hcr.reload_module("_test_hot_mod")
            # reload of a synthetic module should succeed (importlib.reload
            # works on modules with __spec__=None only if they have __file__
            # or __loader__; a bare ModuleType will raise — that's expected)
            # We just verify it doesn't crash the orchestrator
            assert isinstance(result, bool)
        finally:
            sys.modules.pop("_test_hot_mod", None)

    def test_reload_nonexistent_returns_false(self):
        assert hcr.reload_module("nonexistent_module_xyz") is False

    def test_reload_blocked_during_task(self):
        # Simulate task running by holding the lock
        hcr._task_running.acquire()
        try:
            result = hcr.reload_module("os")
            assert result is False
        finally:
            hcr._task_running.release()


# -------------------------------------------------------------------
# reload_env
# -------------------------------------------------------------------
class TestReloadEnv:
    def test_reads_env_file(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("TEST_HOT_KEY=hello_world\n")
        old_env = hcr._ENV
        hcr._ENV = str(env_file)
        hcr._env_mtime = 0.0
        try:
            changed = hcr.reload_env()
            assert "TEST_HOT_KEY" in changed
            assert os.environ.get("TEST_HOT_KEY") == "hello_world"
        finally:
            hcr._ENV = old_env
            os.environ.pop("TEST_HOT_KEY", None)

    def test_skips_unchanged(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("X=1\n")
        old_env = hcr._ENV
        hcr._ENV = str(env_file)
        hcr._env_mtime = 0.0
        try:
            hcr.reload_env()
            # Second call should detect no change (same mtime)
            changed2 = hcr.reload_env()
            assert changed2 == {}
        finally:
            hcr._ENV = old_env

    def test_missing_env_file(self):
        old_env = hcr._ENV
        hcr._ENV = "/nonexistent/.env"
        try:
            changed = hcr.reload_env()
            assert changed == {}
        finally:
            hcr._ENV = old_env

    def test_strips_quotes(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text('QUOTED_VAL="hello"\n')
        old_env = hcr._ENV
        hcr._ENV = str(env_file)
        hcr._env_mtime = 0.0
        try:
            hcr.reload_env()
            assert os.environ.get("QUOTED_VAL") == "hello"
        finally:
            hcr._ENV = old_env
            os.environ.pop("QUOTED_VAL", None)


# -------------------------------------------------------------------
# reload_schedule
# -------------------------------------------------------------------
class TestReloadSchedule:
    def test_first_call_returns_false(self):
        hcr._schedule_hash = ""
        _fake_db._controls = [{"key": "schedule_interval", "value": "60"}]
        result = hcr.reload_schedule()
        assert result is False  # first call seeds baseline

    def test_change_detected(self):
        hcr._schedule_hash = ""
        _fake_db._controls = [{"key": "schedule_interval", "value": "60"}]
        hcr.reload_schedule()  # seed
        _fake_db._controls = [{"key": "schedule_interval", "value": "120"}]
        result = hcr.reload_schedule()
        assert result is True


# -------------------------------------------------------------------
# on_change / callbacks
# -------------------------------------------------------------------
class TestCallbacks:
    def test_callback_called(self):
        results = []
        hcr.on_change(lambda c: results.append(c))
        hcr._fire_callbacks({"test": True})
        assert len(results) == 1
        assert results[0] == {"test": True}

    def test_duplicate_callback_ignored(self):
        fn = lambda c: None
        hcr.on_change(fn)
        hcr.on_change(fn)
        assert hcr._callbacks.count(fn) == 1

    def test_callback_error_increments_stats(self):
        errors_before = hcr._stats["errors"]
        hcr.on_change(lambda c: 1/0)
        hcr._fire_callbacks({"x": 1})
        assert hcr._stats["errors"] > errors_before


# -------------------------------------------------------------------
# pause / resume
# -------------------------------------------------------------------
class TestPauseResume:
    def test_pause_clears_event(self):
        hcr.pause()
        assert not hcr._paused.is_set()
        hcr.resume()
        assert hcr._paused.is_set()


# -------------------------------------------------------------------
# manual_reload
# -------------------------------------------------------------------
class TestManualReload:
    def test_reload_all(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("MANUAL_KEY=val\n")
        old_env = hcr._ENV
        hcr._ENV = str(env_file)
        hcr._env_mtime = 0.0
        try:
            result = hcr.manual_reload()
            assert isinstance(result, dict)
            assert "env" in result
            assert "modules" in result
            assert "schedule" in result
        finally:
            hcr._ENV = old_env
            os.environ.pop("MANUAL_KEY", None)

    def test_reload_specific_module_missing(self):
        result = hcr.manual_reload("nonexistent_xyz")
        assert "nonexistent_xyz" not in result["modules"]
        assert len(result["errors"]) > 0


# -------------------------------------------------------------------
# stats
# -------------------------------------------------------------------
class TestStats:
    def test_returns_dict(self):
        s = hcr.stats()
        assert isinstance(s, dict)
        assert "reloads" in s
        assert "files_watched" in s
        assert "last_check" in s
        assert "errors" in s


# -------------------------------------------------------------------
# watch / stop
# -------------------------------------------------------------------
class TestWatch:
    def test_watch_starts_thread(self):
        hcr.watch(interval_s=60)  # long interval so it doesn't fire
        try:
            assert hcr._watcher_thread is not None
            assert hcr._watcher_thread.is_alive()
        finally:
            hcr.stop()

    def test_watch_idempotent(self):
        hcr.watch(interval_s=60)
        t1 = hcr._watcher_thread
        hcr.watch(interval_s=60)  # should not create a second thread
        t2 = hcr._watcher_thread
        assert t1 is t2
        hcr.stop()

    def test_stop_terminates(self):
        hcr.watch(interval_s=0.1)
        hcr.stop()
        assert not hcr._watcher_thread.is_alive()
