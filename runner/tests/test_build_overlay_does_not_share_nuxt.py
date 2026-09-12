"""A production build overlay must not borrow the checkout's .nuxt.

link_shared_runtime links .nuxt into fresh worktrees on purpose: vitest needs
.nuxt/tsconfig.json, which git ignores and no install step produces, and
operators reported the resulting "~10 broken test files" twice, months apart.
That reasoning is sound for a worktree that RUNS tests.

It is wrong for the one that runs the production build. That worktree generates
.nuxt itself before anything reads it, so the link buys nothing — and the
checkout's copy carries whatever mode it was last used in. Ours carried a dev
state (`import.meta.hot` in .nuxt/app.config.mjs), so the production build read
a dev artifact and died with

    [vite:css] [postcss] Cannot use 'import.meta' outside a module

naming web/assets/main.css, a file with nothing wrong with it. The commit built
green in the real checkout the whole time. production_push_guard then refused
the promotion on that evidence — a gate failing an innocent commit, which is
worse than no gate at all.

These tests pin both halves, because either one alone is a regression waiting
to happen: the worktree path must keep the link, and the build path must not.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import dependency_prewarm as prewarm  # noqa: E402


def _repo_with_generated_dirs():
    repo = tempfile.mkdtemp(prefix="prewarm-repo-")
    os.makedirs(os.path.join(repo, ".nuxt"), exist_ok=True)
    with open(os.path.join(repo, ".nuxt", "tsconfig.json"), "w") as fh:
        fh.write("{}")
    with open(os.path.join(repo, "package.json"), "w") as fh:
        fh.write('{"name":"probe","private":true}')
    os.makedirs(os.path.join(repo, "node_modules"), exist_ok=True)
    return repo


def test_a_worktree_still_gets_nuxt_by_default():
    """The default must not change: this is what stops the phantom vitest failures."""
    repo = _repo_with_generated_dirs()
    worktree = tempfile.mkdtemp(prefix="prewarm-wt-")
    with open(os.path.join(worktree, "package.json"), "w") as fh:
        fh.write('{"name":"probe","private":true}')
    prewarm.link_shared_runtime(repo, worktree)
    assert os.path.exists(os.path.join(worktree, ".nuxt")), (
        "a fresh worktree lost its .nuxt link; vitest will fail ~10 files on a "
        "missing .nuxt/tsconfig.json and it will read as broken tests"
    )


def test_a_build_overlay_does_not_get_nuxt():
    repo = _repo_with_generated_dirs()
    overlay = tempfile.mkdtemp(prefix="prewarm-overlay-")
    with open(os.path.join(overlay, "package.json"), "w") as fh:
        fh.write('{"name":"probe","private":true}')
    prewarm.link_shared_runtime(repo, overlay, share_generated=False)
    assert not os.path.exists(os.path.join(overlay, ".nuxt")), (
        "the build overlay borrowed the checkout's .nuxt. A production build "
        "regenerates it, and borrowing a dev-mode copy fails postcss on a file "
        "that is not broken — which is how a good commit gets refused promotion"
    )


def test_the_build_path_asks_for_no_generated_dirs():
    """Pin the call site, not just the capability."""
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(here, "build_gate.py")) as fh:
        source = fh.read()
    assert "link_shared_runtime(repo, tmp, share_generated=False)" in source, (
        "build_gate's overlay path no longer opts out of shared generated dirs"
    )
