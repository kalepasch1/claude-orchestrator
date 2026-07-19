"""Integration tests for warm_pool — verifies runner integration contract."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from warm_pool import (
    WarmPool, SubprocessWarmPool,
    get_or_create_pool, shutdown_all_pools, POOL_REGISTRY,
)


def test_acceptance_test_from_spec():
    """Exact acceptance test from the task specification."""
    wp = get_or_create_pool('/tmp', max_size=1)
    wp.start()
    assert wp.health_check() in (True, False)
    shutdown_all_pools()
    assert len(POOL_REGISTRY) == 0


def test_runner_integration_contract():
    """Verify the API runner.py depends on works correctly."""
    import warm_pool
    # acquire on the module-level singleton
    pool = WarmPool(pool_size=2)
    result = pool.acquire("/nonexistent")
    assert isinstance(result, str)
    # stats returns a dict
    s = pool.stats()
    assert "pool_size" in s
    assert "loaded" in s


def test_preload_multiple_repos():
    """preload() warms multiple repos without error."""
    pool = WarmPool(pool_size=3)
    with tempfile.TemporaryDirectory() as td:
        repos = []
        for i in range(3):
            rp = os.path.join(td, f"repo{i}")
            os.makedirs(rp)
            # Write a CLAUDE.md
            with open(os.path.join(rp, "CLAUDE.md"), "w") as f:
                f.write(f"# Repo {i}\nProject context for repo {i}.")
            repos.append(rp)
        pool.preload(repos)
        s = pool.stats()
        assert s["loaded"] == 3
        # acquire should return content
        ctx = pool.acquire(repos[0])
        assert "Repo 0" in ctx


def test_invalidate_then_reacquire():
    """After invalidate, next acquire re-reads from disk."""
    pool = WarmPool(pool_size=2)
    with tempfile.TemporaryDirectory() as td:
        md_path = os.path.join(td, "CLAUDE.md")
        with open(md_path, "w") as f:
            f.write("Version 1")
        ctx1 = pool.acquire(td)
        assert "Version 1" in ctx1

        # Update file and invalidate
        with open(md_path, "w") as f:
            f.write("Version 2")
        pool.invalidate(td)
        ctx2 = pool.acquire(td)
        assert "Version 2" in ctx2
