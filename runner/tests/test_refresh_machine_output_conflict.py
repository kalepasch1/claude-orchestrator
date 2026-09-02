"""A release must not fail because two agents rewrote the same cache file.

2026-09-02. Of the 106 releases this fleet attempted in three days -- none of which
succeeded -- 14 failed at the staging/prod refresh, and one named its file outright:

    [gate:refresh] staging/prod refresh failed — self-heal queued:
    nflict in .aider.tags.cache.v4/cache.db-shm
    Automatic merge failed; fix conflicts and t...

That is aider's symbol-tag database. Two of the fleet's repos track it -- pasch and
Sustainable_Barks, five tracked .aider files each and no .gitignore entry -- while the
other four ignore it. Every agent run rewrites the database, so it conflicts on every
single refresh, and each conflict costs a failed release plus a queued relfix task.

The existing _repair_lockfile_only_merge already establishes the shape: a conflict in
deterministic machine output should not be sent through an LLM repair lane. What is
different for a cache is what "repair" means. A lockfile is REGENERATED, because its
contents decide what ships. A cache has no correct contents at all -- both sides are
equally meaningless -- so taking one and moving on IS the resolution.

Classification comes from regenerable_artifacts, not from a second list living here:
that module already holds the fleet's answer to "would losing this destroy something
nobody can get back?". Source conflicts stay fail-closed, and the tests below spend
most of their effort proving exactly that.
"""
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import regenerable_artifacts  # noqa: E402
import release_train  # noqa: E402


def _git(cwd, *args, **kw):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                          timeout=60, **kw)


@pytest.fixture
def conflicted(tmp_path):
    """A real repo mid-conflict. The function under test reads git's index, so a
    fake would prove nothing."""
    def _make(path, left, right, extra=None):
        repo = tmp_path / "r"
        if repo.exists():
            import shutil
            shutil.rmtree(repo)
        repo.mkdir()
        _git(str(repo), "init", "-q", "-b", "main", ".")
        _git(str(repo), "config", "user.email", "t@t")
        _git(str(repo), "config", "user.name", "t")
        target = repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("base\n")
        if extra:
            for name in extra:
                p = repo / name
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text("base\n")
        _git(str(repo), "add", "-A")
        _git(str(repo), "commit", "-qm", "base")
        _git(str(repo), "checkout", "-q", "-b", "other")
        target.write_text(right)
        if extra:
            for name in extra:
                (repo / name).write_text(right)
        _git(str(repo), "commit", "-qam", "other")
        _git(str(repo), "checkout", "-q", "main")
        target.write_text(left)
        if extra:
            for name in extra:
                (repo / name).write_text(left)
        _git(str(repo), "commit", "-qam", "main")
        merged = _git(str(repo), "merge", "--no-ff", "other")
        assert merged.returncode != 0, "the fixture did not actually conflict"
        return str(repo)
    return _make


CACHE = ".aider.tags.cache.v4/cache.db-shm"


# ── the regression ────────────────────────────────────────────────────────────

def test_a_cache_only_conflict_is_resolved(conflicted):
    repo = conflicted(CACHE, "left\n", "right\n")
    ok, note = release_train._repair_regenerable_only_merge(repo)
    assert ok, note
    assert "machine output" in note
    assert not _git(repo, "diff", "--name-only", "--diff-filter=U").stdout.strip()


def test_the_merge_is_actually_committed(conflicted):
    repo = conflicted(CACHE, "left\n", "right\n")
    ok, _note = release_train._repair_regenerable_only_merge(repo)
    assert ok
    assert _git(repo, "rev-parse", "-q", "--verify", "MERGE_HEAD").returncode != 0, (
        "the merge was resolved but never committed")


def test_the_staging_side_is_kept(conflicted):
    """--ours: the next agent run overwrites it anyway, but be explicit."""
    repo = conflicted(CACHE, "left\n", "right\n")
    release_train._repair_regenerable_only_merge(repo)
    assert open(os.path.join(repo, CACHE)).read() == "left\n"


# ── what must STILL fail closed ───────────────────────────────────────────────

def test_a_source_conflict_is_refused(conflicted):
    repo = conflicted("src/app.vue", "left\n", "right\n")
    ok, note = release_train._repair_regenerable_only_merge(repo)
    assert ok is False
    assert "src/app.vue" in note, "the refusal must name the file that blocked it"


def test_a_mixed_conflict_is_refused(conflicted):
    """The dangerous case: a cache conflict that also carries real work."""
    repo = conflicted(CACHE, "left\n", "right\n", extra=["lib/commerce/coppa.ts"])
    ok, note = release_train._repair_regenerable_only_merge(repo)
    assert ok is False
    assert "coppa.ts" in note
    assert _git(repo, "diff", "--name-only", "--diff-filter=U").stdout.strip(), (
        "a refused repair must leave the conflict intact for the caller to abort")


def test_a_lockfile_conflict_is_not_swallowed_here(conflicted):
    """package-lock.json is deliberately NOT regenerable: its diff changes what ships.
    It belongs to _repair_lockfile_only_merge, which REGENERATES it."""
    repo = conflicted("package-lock.json", "left\n", "right\n")
    ok, note = release_train._repair_regenerable_only_merge(repo)
    assert ok is False
    assert "package-lock.json" in note


def test_the_chat_transcript_is_not_treated_as_a_cache(conflicted):
    """.aider.chat.history.md records what an agent did and nothing can rebuild it."""
    repo = conflicted(".aider.chat.history.md", "left\n", "right\n")
    ok, _note = release_train._repair_regenerable_only_merge(repo)
    assert ok is False


def test_no_conflict_at_all_is_not_a_repair(tmp_path):
    repo = tmp_path / "clean"
    repo.mkdir()
    _git(str(repo), "init", "-q", "-b", "main", ".")
    ok, note = release_train._repair_regenerable_only_merge(str(repo))
    assert ok is False
    assert note == ""


# ── the classifier ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("path", [
    ".aider.tags.cache.v4/cache.db",
    ".aider.tags.cache.v4/cache.db-shm",
    ".aider.tags.cache.v4/cache.db-wal",
    "web/.aider.tags.cache.v4/cache.db",
])
def test_the_tag_cache_is_regenerable(path):
    assert regenerable_artifacts.is_regenerable(path) is True


@pytest.mark.parametrize("path", [
    ".aider.chat.history.md",
    ".aider.input.history",
    "package-lock.json",
    "src/app.vue",
    "supabase/migrations/0001_init.sql",
])
def test_these_are_not_regenerable(path):
    assert regenerable_artifacts.is_regenerable(path) is False
