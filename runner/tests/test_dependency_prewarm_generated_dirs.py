#!/usr/bin/env python3
"""A prepared worktree needs the GENERATED files too, not just node_modules.

A fresh worktree has only tracked files. `.nuxt/tsconfig.json` is generated and
gitignored, so it is absent, and vitest dies with

    TSConfckParseError: ... .nuxt/tsconfig.json ... ENOENT

on roughly ten files. That reads as broken tests rather than as an unprepared
checkout, which is the expensive part: the agent starts debugging source it
never touched. Operator feedback in this queue reports it twice, months apart,
in almost the same words — recurring identically is the tell that it had been
worked around rather than fixed.

These tests pin that link_shared_runtime prepares the generated directories as
well as the installed ones, and that it stays a link rather than a copy.
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import dependency_prewarm as prewarm  # noqa: E402


def make_repo(root, package_roots=(".",), with_nuxt=True):
    """A checkout with warmed node_modules and .nuxt at each package root."""
    for rel in package_roots:
        base = root if rel == "." else os.path.join(root, rel)
        os.makedirs(base, exist_ok=True)
        with open(os.path.join(base, "package.json"), "w") as handle:
            handle.write('{"name": "pkg"}')
        os.makedirs(os.path.join(base, "node_modules", "vitest"), exist_ok=True)
        if with_nuxt:
            os.makedirs(os.path.join(base, ".nuxt"), exist_ok=True)
            with open(os.path.join(base, ".nuxt", "tsconfig.json"), "w") as handle:
                handle.write("{}")
    return root


def make_worktree(root, package_roots=(".",)):
    """A fresh worktree: tracked files only, nothing generated or installed."""
    for rel in package_roots:
        base = root if rel == "." else os.path.join(root, rel)
        os.makedirs(base, exist_ok=True)
        with open(os.path.join(base, "package.json"), "w") as handle:
            handle.write('{"name": "pkg"}')
    return root


class TestGeneratedDirsArePrepared:
    def test_the_tsconfig_that_broke_vitest_is_reachable(self):
        with tempfile.TemporaryDirectory() as temp_root:
            repo = make_repo(os.path.join(temp_root, "repo"))
            worktree_path = make_worktree(os.path.join(temp_root, "wt"))
            prewarm.link_shared_runtime(repo, worktree_path)
            assert os.path.exists(os.path.join(worktree_path, ".nuxt", "tsconfig.json")), \
                "the exact file whose absence produced TSConfckParseError"

    def test_nested_package_roots_each_get_their_own(self):
        with tempfile.TemporaryDirectory() as temp_root:
            roots = (".", "web")
            repo = make_repo(os.path.join(temp_root, "repo"), roots)
            worktree_path = make_worktree(os.path.join(temp_root, "wt"), roots)
            prewarm.link_shared_runtime(repo, worktree_path)
            assert os.path.exists(os.path.join(worktree_path, "web", ".nuxt", "tsconfig.json"))

    def test_it_is_a_link_not_a_copy(self):
        # Regenerable and small: a worktree that runs `nuxt prepare` should
        # refresh the shared copy rather than fork a stale one.
        with tempfile.TemporaryDirectory() as temp_root:
            repo = make_repo(os.path.join(temp_root, "repo"))
            worktree_path = make_worktree(os.path.join(temp_root, "wt"))
            prewarm.link_shared_runtime(repo, worktree_path)
            assert os.path.islink(os.path.join(worktree_path, ".nuxt"))

    def test_node_modules_is_still_prepared(self):
        with tempfile.TemporaryDirectory() as temp_root:
            repo = make_repo(os.path.join(temp_root, "repo"))
            worktree_path = make_worktree(os.path.join(temp_root, "wt"))
            prewarm.link_shared_runtime(repo, worktree_path)
            assert os.path.exists(os.path.join(worktree_path, "node_modules", "vitest"))


class TestItDoesNotMakeThingsWorse:
    def test_a_repo_without_the_generated_dir_is_fine(self):
        with tempfile.TemporaryDirectory() as temp_root:
            repo = make_repo(os.path.join(temp_root, "repo"), with_nuxt=False)
            worktree_path = make_worktree(os.path.join(temp_root, "wt"))
            prewarm.link_shared_runtime(repo, worktree_path)
            assert not os.path.exists(os.path.join(worktree_path, ".nuxt"))

    def test_an_existing_generated_dir_in_the_worktree_is_not_clobbered(self):
        # If the worktree already prepared its own, that one wins.
        with tempfile.TemporaryDirectory() as temp_root:
            repo = make_repo(os.path.join(temp_root, "repo"))
            worktree_path = make_worktree(os.path.join(temp_root, "wt"))
            own = os.path.join(worktree_path, ".nuxt")
            os.makedirs(own)
            with open(os.path.join(own, "marker"), "w") as handle:
                handle.write("mine")
            prewarm.link_shared_runtime(repo, worktree_path)
            assert not os.path.islink(own)
            assert os.path.exists(os.path.join(own, "marker"))

    def test_running_twice_is_a_no_op(self):
        with tempfile.TemporaryDirectory() as temp_root:
            repo = make_repo(os.path.join(temp_root, "repo"))
            worktree_path = make_worktree(os.path.join(temp_root, "wt"))
            first = prewarm.link_shared_runtime(repo, worktree_path)
            second = prewarm.link_shared_runtime(repo, worktree_path)
            assert first
            assert second == []

    def test_the_generated_list_is_explicit(self):
        # A named constant, so adding .output or .next later is a decision
        # someone makes rather than a regex quietly widening.
        assert ".nuxt" in prewarm.GENERATED_SHARED_DIRS
