"""The slowest step in the build pipeline was refetching the same dependencies.

`npm ci` deletes node_modules and reinstalls from the lockfile on every run, so the
darwin-kernel job downloaded every dependency from the registry on every push and every PR
update — for a tree that only changes when package-lock.json does.

Two details make the cache correct rather than merely fast, and both are asserted here:
the key is the LOCKFILE HASH (so a dependency change misses and installs fresh — `npm ci`
still decides what is installed, the cache only removes the download), and the cached path
is npm's own cache dir, NOT node_modules (which `npm ci` wipes before it starts, so a
node_modules cache would be deleted by the command it was meant to speed up).
"""
import os

import pytest

yaml = pytest.importorskip("yaml")

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CI = os.path.join(REPO, ".github", "workflows", "ci.yml")


@pytest.fixture(scope="module")
def darwin_steps():
    with open(CI, encoding="utf-8") as fh:
        return yaml.safe_load(fh)["jobs"]["darwin-kernel"]["steps"]


def _cache_step(steps):
    hits = [s for s in steps if str(s.get("uses", "")).startswith("actions/cache")]
    assert hits, "the darwin-kernel job has no dependency cache"
    return hits[0]


class TestCacheIsPresent:
    def test_the_job_caches_dependencies(self, darwin_steps):
        assert _cache_step(darwin_steps)

    def test_it_runs_before_the_install(self, darwin_steps):
        names = [str(s.get("uses", "")) + str(s.get("name", "")) for s in darwin_steps]
        cache_at = next(i for i, n in enumerate(names) if "actions/cache" in n)
        install_at = next(i for i, s in enumerate(darwin_steps)
                          if "npm ci" in str(s.get("run", "")))
        assert cache_at < install_at, "a cache restored after the install is useless"


class TestCacheIsCorrect:
    def test_the_key_is_the_lockfile_hash(self, darwin_steps):
        """A dependency change MUST miss the cache and install fresh."""
        key = _cache_step(darwin_steps)["with"]["key"]
        assert "hashFiles" in key
        assert "package-lock.json" in key

    def test_it_caches_the_npm_dir_not_node_modules(self, darwin_steps):
        """`npm ci` wipes node_modules; caching it would be self-defeating."""
        path = str(_cache_step(darwin_steps)["with"]["path"])
        assert ".npm" in path
        assert "node_modules" not in path

    def test_the_lockfile_the_key_points_at_actually_exists(self):
        assert os.path.isfile(os.path.join(REPO, "packages", "darwin-kernel",
                                           "package-lock.json"))

    def test_npm_ci_is_still_what_installs(self, darwin_steps):
        """The cache removes the download, never the resolution."""
        runs = [str(s.get("run", "")) for s in darwin_steps]
        assert any("npm ci" in r for r in runs)
        assert not any("npm install" in r for r in runs)


class TestNoBehaviourChange:
    def test_the_tests_and_typecheck_still_run(self, darwin_steps):
        runs = " ".join(str(s.get("run", "")) for s in darwin_steps)
        assert "node --test" in runs
        assert "tsc --noEmit" in runs

    def test_the_job_still_checks_out_first(self, darwin_steps):
        assert str(darwin_steps[0].get("uses", "")).startswith("actions/checkout")

    def test_the_concurrency_guard_from_the_sibling_slice_survives(self):
        """This branch stacks on the CI slice; do not undo it."""
        with open(CI, encoding="utf-8") as fh:
            workflow = yaml.safe_load(fh)
        assert "refs/heads/master" in str(workflow["concurrency"]["cancel-in-progress"])
