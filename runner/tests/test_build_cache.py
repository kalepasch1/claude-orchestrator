#!/usr/bin/env python3
"""Tests for runner/build_cache.py"""
import os, sys, tempfile, shutil
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import build_cache


def _make_worktree(tmp, lockfile_content="lock-v1", lockfile_name="package-lock.json"):
    wt = os.path.join(tmp, "worktree")
    web = os.path.join(wt, "web")
    os.makedirs(web, exist_ok=True)
    with open(os.path.join(web, lockfile_name), "w") as f:
        f.write(lockfile_content)
    return wt


class TestCacheKey:
    def test_stable_for_identical_lockfiles(self):
        with tempfile.TemporaryDirectory() as tmp:
            wt1 = _make_worktree(os.path.join(tmp, "a"), "identical-content")
            wt2 = _make_worktree(os.path.join(tmp, "b"), "identical-content")
            k1 = build_cache.cache_key(wt1)
            k2 = build_cache.cache_key(wt2)
            assert k1 and k2
            assert k1 == k2, "identical lockfiles must produce the same cache key"

    def test_changes_when_lockfile_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            wt1 = _make_worktree(os.path.join(tmp, "a"), "version-1")
            wt2 = _make_worktree(os.path.join(tmp, "b"), "version-2")
            k1 = build_cache.cache_key(wt1)
            k2 = build_cache.cache_key(wt2)
            assert k1 != k2, "different lockfiles must produce different keys"

    def test_empty_on_no_lockfile(self):
        with tempfile.TemporaryDirectory() as tmp:
            wt = os.path.join(tmp, "empty")
            os.makedirs(os.path.join(wt, "web"), exist_ok=True)
            assert build_cache.cache_key(wt) == ""

    def test_yarn_lock_also_works(self):
        with tempfile.TemporaryDirectory() as tmp:
            wt = _make_worktree(tmp, "yarn-lock-content", "yarn.lock")
            assert build_cache.cache_key(wt) != ""


class TestRestoreSave:
    def test_miss_returns_false(self):
        with tempfile.TemporaryDirectory() as tmp:
            wt = _make_worktree(tmp, "no-cache-yet")
            cache_root = os.path.join(tmp, "cache")
            assert build_cache.restore(wt, root=cache_root) is False

    def test_save_then_restore(self):
        with tempfile.TemporaryDirectory() as tmp:
            wt = _make_worktree(tmp, "save-restore-test")
            cache_root = os.path.join(tmp, "cache")
            # create fake node_modules + .nuxt
            nm = os.path.join(wt, "web", "node_modules")
            nuxt = os.path.join(wt, "web", ".nuxt")
            os.makedirs(nm)
            os.makedirs(nuxt)
            with open(os.path.join(nm, "marker.txt"), "w") as f:
                f.write("cached")
            with open(os.path.join(nuxt, "build.js"), "w") as f:
                f.write("built")

            assert build_cache.save(wt, root=cache_root) is True

            # remove originals
            shutil.rmtree(nm)
            shutil.rmtree(nuxt)
            assert not os.path.isdir(nm)

            # restore
            assert build_cache.restore(wt, root=cache_root) is True
            assert os.path.isfile(os.path.join(nm, "marker.txt"))
            assert os.path.isfile(os.path.join(nuxt, "build.js"))

    def test_no_lockfile_save_returns_false(self):
        with tempfile.TemporaryDirectory() as tmp:
            wt = os.path.join(tmp, "empty")
            os.makedirs(os.path.join(wt, "web"), exist_ok=True)
            assert build_cache.save(wt, root=os.path.join(tmp, "c")) is False
