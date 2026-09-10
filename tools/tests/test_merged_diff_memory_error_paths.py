"""merged-diff memory — the five paths the spec names, on the code that lacked them.

The spec's `tests-minimum-8-test-cases` section asks for the success path, git
errors, I/O errors, DB errors, and retrieval with and without a keyword. Most of
those words already have tests somewhere in this repo; these are the ones that
did not.

What was actually uncovered, checked before writing rather than assumed:

  * `stats()` had NO test at all — it appeared in no test file in the repo. It is
    the entry point behind `merged_diff_memory.py --stats`, so an operator asking
    "is there anything to learn from here?" was asking an unverified function.
  * `sync_project_memory()`'s return contract — True ONLY when a write landed —
    was untested for the case that matters: diffs exist but the write fails. A
    True there would tell a caller the memory was synced when nothing was
    written.
  * `write_memory_file()`'s append path could not be told apart from its create
    path by any assertion, though the difference is load-bearing: the function
    carries two fixed bugs (re-emitted frontmatter, unrecognised commit hashes)
    that both lived in exactly that distinction.
  * `merged_diff_library.record()` returning False when EVERY table rejects the
    insert — the existing test covers one insert failing, not the exhausted case.

Every test here is fail-soft in the same direction as the code: these helpers
must degrade to an empty result rather than raise, because they run inside the
merge train where an exception is a stalled queue, not a visible error.
"""
import importlib.util
import os
import subprocess
import sys

import pytest

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(TOOLS)
RUNNER = os.path.join(ROOT, "runner")

# `merged_diff_memory` exists in BOTH tools/ and runner/, with different APIs
# (tools' write_memory_file takes (project, diffs); runner's takes one argument).
# Whichever directory lands first on sys.path wins, which makes an import here
# depend on what some other test imported earlier in the session. Loading the
# tools copy explicitly by path removes that coupling — this file is about the
# tools module and says so.
def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        pytest.skip("cannot load %s" % path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mdm = _load("tools_merged_diff_memory",
            os.path.join(TOOLS, "merged_diff_memory.py"))

if RUNNER not in sys.path:
    sys.path.append(RUNNER)


# ── fixtures ────────────────────────────────────────────────────────────────

def _git(repo, *args):
    return subprocess.run(("git",) + args, cwd=repo, capture_output=True,
                          text=True, timeout=30)


@pytest.fixture
def merged_repo(tmp_path):
    """A real repo with one merged agent/* branch — the success-path input."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "master")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    (repo / "a.py").write_text("print('base')\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")

    _git(repo, "checkout", "-q", "-b", "agent/thing")
    (repo / "b.py").write_text("print('work')\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "work")

    _git(repo, "checkout", "-q", "master")
    _git(repo, "merge", "--no-ff", "-q", "-m", "Merge branch 'agent/thing'", "agent/thing")
    return str(repo)


# ── 1. success path ─────────────────────────────────────────────────────────

def test_a_merged_agent_branch_is_found_end_to_end(merged_repo):
    branches = mdm.get_recent_merged_agent_branches(merged_repo)
    assert len(branches) == 1
    assert branches[0]["branch_name"] == "thing"
    assert branches[0]["commit_hash"]


def test_stats_reports_the_merge_and_names_the_branch(merged_repo):
    """`stats()` had no test anywhere in the repo before this."""
    s = mdm.stats(merged_repo)
    assert s["total_merge_commits"] == 1
    assert s["sample_branches"] == ["thing"]


def test_stats_samples_at_most_five_branches(tmp_path, monkeypatch):
    # The sample is for a human reading CLI output; an unbounded list would bury
    # the count it sits next to.
    fake = [{"branch_name": "b%d" % i, "commit_hash": "h%d" % i} for i in range(12)]
    monkeypatch.setattr(mdm, "get_recent_merged_agent_branches",
                        lambda repo, limit=50: fake)
    s = mdm.stats(str(tmp_path))
    assert s["total_merge_commits"] == 12
    assert len(s["sample_branches"]) == 5


def test_extract_returns_the_diff_and_the_changed_files(merged_repo):
    diffs = mdm.extract_merged_diffs(merged_repo)
    assert len(diffs) == 1
    assert "b.py" in diffs[0]["files"]
    assert "print('work')" in diffs[0]["diff"]


def test_sync_writes_the_memory_file_and_reports_true(merged_repo, tmp_path, monkeypatch):
    monkeypatch.setattr(mdm.Path, "home", staticmethod(lambda: tmp_path / "home"))
    assert mdm.sync_project_memory(merged_repo, project="demo") is True


# ── 2. git errors ───────────────────────────────────────────────────────────

def test_a_directory_that_is_not_a_repo_yields_no_branches(tmp_path):
    assert mdm.get_recent_merged_agent_branches(str(tmp_path)) == []


def test_stats_on_a_non_repo_reports_zero_rather_than_raising(tmp_path):
    # The CLI prints this as JSON; raising here would turn "nothing to learn"
    # into a traceback.
    assert mdm.stats(str(tmp_path)) == {"total_merge_commits": 0,
                                        "sample_branches": []}


def test_a_missing_repo_path_is_not_fatal():
    assert mdm.get_recent_merged_agent_branches("/does/not/exist") == []
    assert mdm.get_merge_diff("/does/not/exist", "deadbeef") == ""
    assert mdm.get_changed_files("/does/not/exist", "deadbeef") == []


def test_an_unknown_commit_yields_an_empty_diff(merged_repo):
    assert mdm.get_merge_diff(merged_repo, "0" * 40) == ""
    assert mdm.get_changed_files(merged_repo, "0" * 40) == []


def test_a_git_timeout_is_swallowed_not_raised(merged_repo, monkeypatch):
    def boom(*a, **k):
        raise subprocess.TimeoutExpired(["git"], 30)

    monkeypatch.setattr(mdm.subprocess, "check_output", boom)
    assert mdm.get_recent_merged_agent_branches(merged_repo) == []
    assert mdm.get_merge_diff(merged_repo, "abc") == ""
    assert mdm.get_changed_files(merged_repo, "abc") == []


def test_a_non_merge_commit_message_is_skipped(tmp_path):
    """A repo whose merges are not agent/* branches has nothing to learn from,
    and must not be reported as if it did."""
    repo = tmp_path / "r"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "master")
    _git(repo, "config", "user.email", "t@e.com")
    _git(repo, "config", "user.name", "t")
    (repo / "f").write_text("x")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    _git(repo, "checkout", "-q", "-b", "feature/x")
    (repo / "g").write_text("y")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "w")
    _git(repo, "checkout", "-q", "master")
    _git(repo, "merge", "--no-ff", "-q", "-m", "Merge branch 'feature/x'", "feature/x")

    assert mdm.get_recent_merged_agent_branches(str(repo)) == []


def test_extract_survives_a_repo_with_no_merges_at_all(tmp_path):
    repo = tmp_path / "r"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "master")
    assert mdm.extract_merged_diffs(str(repo)) == []


# ── 3. I/O errors ───────────────────────────────────────────────────────────

def _diff_entry(h="a" * 40):
    return {"commit_hash": h, "branch_name": "b", "merge_message": "m",
            "author_date": "2026-01-01T00:00:00Z", "files": ["x.py"],
            "diff": "diff", "extracted_at": "2026-01-01T00:00:00Z"}


def test_an_unwritable_memory_dir_returns_none_rather_than_raising(tmp_path, monkeypatch):
    """Documented contract: None on failure.

    This is the guard added after an unguarded mkdir raised out of a fail-soft
    helper; it stays pinned because the caller treats None as 'nothing synced'
    and an exception as a crashed merge train.
    """
    monkeypatch.setattr(mdm.Path, "home", staticmethod(lambda: tmp_path / "home"))

    def boom(*a, **k):
        raise PermissionError("read-only file system")

    monkeypatch.setattr(mdm.Path, "mkdir", boom)
    assert mdm.write_memory_file("demo", [_diff_entry()]) is None


def test_a_failed_write_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(mdm.Path, "home", staticmethod(lambda: tmp_path / "home"))

    def boom(*a, **k):
        raise OSError("No space left on device")

    monkeypatch.setattr(mdm.Path, "write_text", boom)
    assert mdm.write_memory_file("demo", [_diff_entry()]) is None


def test_sync_reports_false_when_the_write_fails(merged_repo, tmp_path, monkeypatch):
    """The one that matters for callers.

    Diffs WERE extracted, so the early 'no diffs' return does not apply; the
    write is what failed. Returning True here would tell a caller the memory was
    synced when nothing landed on disk.
    """
    monkeypatch.setattr(mdm.Path, "home", staticmethod(lambda: tmp_path / "home"))
    monkeypatch.setattr(mdm, "write_memory_file", lambda project, diffs: None)
    assert mdm.sync_project_memory(merged_repo, project="demo") is False


def test_an_unreadable_existing_file_does_not_abort_the_write(tmp_path, monkeypatch):
    # A corrupt memory file must not permanently block new entries: the hash
    # scan is best-effort and falls back to "nothing recorded yet".
    monkeypatch.setattr(mdm.Path, "home", staticmethod(lambda: tmp_path / "home"))
    first = mdm.write_memory_file("demo", [_diff_entry("a" * 40)])
    assert first

    real_read = mdm.Path.read_text
    calls = {"n": 0}

    def flaky(self, *a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("I/O error")
        return real_read(self, *a, **k)

    monkeypatch.setattr(mdm.Path, "read_text", flaky)
    assert mdm.write_memory_file("demo", [_diff_entry("b" * 40)])


def test_writing_no_diffs_is_a_no_op(tmp_path, monkeypatch):
    monkeypatch.setattr(mdm.Path, "home", staticmethod(lambda: tmp_path / "home"))
    assert mdm.write_memory_file("demo", []) is None


def test_an_already_recorded_commit_is_not_appended_twice(tmp_path, monkeypatch):
    """Idempotency, asserted on the file rather than the return value.

    The writer carried a bug where no hash was ever recognised as already
    present, so every run re-appended every entry and the file doubled each
    time. Checking only the return value would not have caught it.
    """
    monkeypatch.setattr(mdm.Path, "home", staticmethod(lambda: tmp_path / "home"))
    path = mdm.write_memory_file("demo", [_diff_entry("c" * 40)])
    assert path
    size_after_first = os.path.getsize(path)

    assert mdm.write_memory_file("demo", [_diff_entry("c" * 40)]) is None
    assert os.path.getsize(path) == size_after_first


def test_appending_does_not_plant_a_second_frontmatter_block(tmp_path, monkeypatch):
    """A second `---` block mid-document ends the file for any parser reading it."""
    monkeypatch.setattr(mdm.Path, "home", staticmethod(lambda: tmp_path / "home"))
    path = mdm.write_memory_file("demo", [_diff_entry("d" * 40)])
    mdm.write_memory_file("demo", [_diff_entry("e" * 40)])
    content = open(path).read()
    assert content.count("name: merged-changes-log") == 1


# ── 4. DB errors ────────────────────────────────────────────────────────────

mdl = pytest.importorskip("merged_diff_library")


def test_record_returns_false_when_every_table_rejects_the_insert(monkeypatch):
    """The exhausted case: `record` tries merged_diffs then knowledge.

    A True here would tell the merge train the diff was learned when nothing was
    stored, and the library would silently stop growing.
    """
    monkeypatch.setattr(mdl, "_changed_files", lambda *a, **k: ["x.py"])
    monkeypatch.setattr(mdl, "_diff", lambda *a, **k: "diff --git a/x b/x")

    def boom(*a, **k):
        raise RuntimeError("db=down")

    monkeypatch.setattr(mdl.db, "insert", boom)
    assert mdl.record("p", "s", "build", "prompt words here", "/repo", "b", "h") is False


def test_record_succeeds_if_any_table_accepts(monkeypatch):
    monkeypatch.setattr(mdl, "_changed_files", lambda *a, **k: [])
    monkeypatch.setattr(mdl, "_diff", lambda *a, **k: "")
    seen = []

    def picky(table, body, upsert=False):
        seen.append(table)
        if table == "merged_diffs":
            raise RuntimeError("no such table")
        return body

    monkeypatch.setattr(mdl.db, "insert", picky)
    assert mdl.record("p", "s", "build", "prompt words", "/repo", "b", "h") is True
    assert seen == ["merged_diffs", "knowledge"]


def test_find_returns_empty_when_the_database_is_unreachable(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(mdl.db, "select", boom)
    assert mdl.find({"prompt": "add a retry to the queue writer"}) == []


def test_a_db_outage_degrades_the_directive_to_silence(monkeypatch):
    # The directive is injected into a task prompt. Failing loud here would put a
    # stack trace in front of a coding agent; failing empty just means no prior
    # art was offered.
    monkeypatch.setattr(mdl.db, "select",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db=down")))
    assert mdl.directive({"prompt": "add a retry to the queue writer"}) == ""


# ── 5. retrieval, with and without a keyword ────────────────────────────────

def test_a_prompt_with_no_words_retrieves_nothing_and_never_queries(monkeypatch):
    """Short-circuit before the DB: an empty query would score every row against
    nothing and rank the library by noise."""
    called = []
    monkeypatch.setattr(mdl.db, "select",
                        lambda *a, **k: (called.append(1), [])[1])
    assert mdl.find({"prompt": ""}) == []
    assert mdl.find({}) == []
    assert mdl.find(None) == []
    assert called == [], "the database was queried for a keyword-less prompt"


def test_a_keyword_match_above_the_floor_is_returned(monkeypatch):
    prompt = "add retry logic to the settlement queue writer"
    row = {"project": "p", "slug": "s", "kind": "build", "prompt": prompt,
           "diff": "", "words": list(mdl._words(prompt))}
    monkeypatch.setattr(mdl.db, "select", lambda *a, **k: [row])

    hits = mdl.find({"prompt": prompt})
    assert len(hits) == 1
    assert hits[0]["slug"] == "s"
    assert hits[0]["similarity"] >= mdl.similarity_floor()


def test_a_weak_keyword_overlap_is_rejected_by_the_floor(monkeypatch):
    """The floor exists because low-similarity priors were being rendered into
    prompts as 'adapt this proven diff', wrapping a one-paragraph spec in
    kilobytes of someone else's work."""
    row = {"project": "p", "slug": "unrelated", "kind": "build",
           "prompt": "rewrite the css grid for the marketing page",
           "diff": "", "words": list(mdl._words("rewrite css grid marketing page"))}
    monkeypatch.setattr(mdl.db, "select", lambda *a, **k: [row])

    assert mdl.find({"prompt": "add retry logic to the settlement queue writer"}) == []


def test_results_are_ranked_best_first_and_limited(monkeypatch):
    prompt = "add retry logic to the settlement queue writer"
    exact = {"slug": "exact", "project": "p", "kind": "build", "prompt": prompt,
             "diff": "", "words": list(mdl._words(prompt))}
    partial = {"slug": "partial", "project": "p", "kind": "build",
               "prompt": "add retry logic to the settlement queue writer and more words here",
               "diff": "", "words": list(mdl._words(prompt + " and more words here"))}
    monkeypatch.setattr(mdl.db, "select", lambda *a, **k: [partial, exact])

    hits = mdl.find({"prompt": prompt}, limit=1)
    assert [h["slug"] for h in hits] == ["exact"]
