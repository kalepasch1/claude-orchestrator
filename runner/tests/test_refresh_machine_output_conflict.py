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
    """.aider.chat.history.md records what an agent did and nothing can rebuild it, so
    it must NOT be resolved the way a cache is. It is resolved by union instead -- see
    the append-only section below -- and the property that matters is that neither
    side is discarded."""
    repo = conflicted(".aider.chat.history.md", "left\n", "right\n")
    ok, _note = release_train._repair_regenerable_only_merge(repo)
    assert ok is True
    merged = open(os.path.join(repo, ".aider.chat.history.md")).read()
    assert "left" in merged and "right" in merged, (
        "the transcript was resolved by taking one side, which deletes history")


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


# ── append-only transcripts: union, never "ours" ─────────────────────────────
#
# The layer below named its own blocker. Once the tag cache stopped failing
# kalepasch-com's releases, the row read:
#
#   lockfile auto-repair: not a lockfile-only conflict;
#   conflict includes non-regenerable file(s): .aider.chat.history.md
#
# That file conflicts on every refresh for exactly the reason the cache did -- two
# branches appended different lines -- but it is NOT regenerable: nothing can rebuild a
# record of what an agent did. Taking one side would delete the other side's history.
#
# An append-only log has a merge that loses nothing: keep BOTH sides. That is the only
# reason this file class can be auto-resolved at all, and it is why "ours" is wrong here
# and right for the cache.

TRANSCRIPT = ".aider.chat.history.md"


def test_an_append_only_transcript_is_resolved(conflicted):
    repo = conflicted(TRANSCRIPT, "left line\n", "right line\n")
    ok, note = release_train._repair_regenerable_only_merge(repo)
    assert ok, note


def test_the_union_keeps_both_sides(conflicted):
    """The whole point. Losing either side is losing a record nothing can rebuild."""
    repo = conflicted(TRANSCRIPT, "left line\n", "right line\n")
    release_train._repair_regenerable_only_merge(repo)
    merged = open(os.path.join(repo, TRANSCRIPT)).read()
    assert "left line" in merged, "the union dropped our side"
    assert "right line" in merged, "the union dropped their side"
    assert "<<<<<<<" not in merged, "conflict markers were committed"


def test_a_transcript_and_a_cache_together_are_both_resolved(conflicted):
    """The real kalepasch-com shape: the cache AND the transcript in one conflict."""
    repo = conflicted(TRANSCRIPT, "left line\n", "right line\n", extra=[CACHE])
    ok, note = release_train._repair_regenerable_only_merge(repo)
    assert ok, note
    merged = open(os.path.join(repo, TRANSCRIPT)).read()
    assert "left line" in merged and "right line" in merged
    assert not _git(repo, "diff", "--name-only", "--diff-filter=U").stdout.strip()


def test_a_transcript_plus_real_source_is_still_refused(conflicted):
    repo = conflicted(TRANSCRIPT, "left\n", "right\n", extra=["lib/commerce/coppa.ts"])
    ok, note = release_train._repair_regenerable_only_merge(repo)
    assert ok is False
    assert "coppa.ts" in note


def test_the_transcript_is_still_not_classified_as_regenerable():
    """It is resolvable, which is not the same as rebuildable. If it ever lands in the
    regenerable list, the resolution silently becomes 'take ours' and deletes history."""
    assert regenerable_artifacts.is_regenerable(TRANSCRIPT) is False
    assert regenerable_artifacts.is_regenerable(".aider.input.history") is False


@pytest.mark.parametrize("path,expected", [
    (".aider.chat.history.md", True),
    (".aider.input.history", True),
    ("web/.aider.chat.history.md", True),
    ("./.aider.chat.history.md", True),
    (".aider.tags.cache.v4/cache.db", False),
    ("src/app.vue", False),
    ("CHANGELOG.md", False),
])
def test_append_only_classification(path, expected):
    assert release_train._is_append_only(path) is expected
