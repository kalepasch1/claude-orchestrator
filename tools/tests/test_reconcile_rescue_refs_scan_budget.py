"""reconcile_rescue_refs — the scan has to finish, and say so when it doesn't.

This file covers the three properties that decide whether a rescue-ref
reconciliation is usable at all, none of which were pinned before:

  * the two memo caches. `newest_touch` was called once per touched file per
    ref and `agent_branches_containing` once per ref, both issuing full-history
    git walks. On this repo (653 rescue refs, hundreds of agent branches) the
    uncached scan did not finish inside any budget a caller was willing to wait,
    so these tasks were repeatedly killed and requeued. The caches are only
    sound because `base` is fixed for a run and the keys are pure — that
    soundness is what the tests below hold in place.

  * the `--max-seconds` budget. A killed scan produces NO ledger; a budgeted one
    produces a partial ledger that names its own gap. Unreached refs must stay
    UNKNOWN — inventing a classification for a ref nobody looked at is exactly
    the "missing input masquerading as clean evidence" this reconciler family
    exists to prevent, so the exit code stays non-zero and the completion gate
    stays shut.

  * progress output. A tool silent for six minutes is indistinguishable from a
    hung one, which is the proximate reason these scans kept being killed.

The caches are process-global, so each test clears them first; a leaked entry
between tests would make a broken cache look like a working one.
"""
import os
import sys

import pytest

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, TOOLS)

rrr = pytest.importorskip("reconcile_rescue_refs")


@pytest.fixture(autouse=True)
def clear_caches():
    rrr._NEWEST_TOUCH_CACHE.clear()
    rrr._CONTAINS_CACHE.clear()
    yield
    rrr._NEWEST_TOUCH_CACHE.clear()
    rrr._CONTAINS_CACHE.clear()


# ── newest_touch memoisation ────────────────────────────────────────────────

def test_a_repeated_path_is_only_walked_once(monkeypatch):
    calls = []

    def fake_git(*args, **kw):
        calls.append(args)
        return "1700000000\n"

    monkeypatch.setattr(rrr, "git", fake_git)

    for _ in range(50):
        assert rrr.newest_touch("origin/master", "runner/runner.py") == 1700000000
    assert len(calls) == 1, "the same (base, path) was walked more than once"


def test_distinct_paths_are_each_walked(monkeypatch):
    calls = []
    monkeypatch.setattr(rrr, "git",
                        lambda *a, **k: (calls.append(a), "1700000000\n")[1])

    rrr.newest_touch("origin/master", "a.py")
    rrr.newest_touch("origin/master", "b.py")
    assert len(calls) == 2


def test_the_base_is_part_of_the_cache_key(monkeypatch):
    """Two projects in one process must not share an answer.

    `newest_touch` is only a pure function once `base` is pinned. Keying on the
    path alone would let a scan of origin/main return an age measured against
    origin/master — a wrong answer that looks entirely plausible in the ledger.
    """
    answers = {"origin/master": "100\n", "origin/main": "200\n"}
    monkeypatch.setattr(rrr, "git", lambda *a, **k: answers[a[3]])

    assert rrr.newest_touch("origin/master", "x.py") == 100
    assert rrr.newest_touch("origin/main", "x.py") == 200


def test_an_unparseable_git_answer_caches_zero_rather_than_re_walking(monkeypatch):
    """A path that git cannot date is the common case for deleted files.

    Zero is the right value (it can never be newer than the ref, so the ref is
    never wrongly called SUPERSEDED). Caching it matters because these paths are
    otherwise re-walked on every ref that touches them.
    """
    calls = []
    monkeypatch.setattr(rrr, "git",
                        lambda *a, **k: (calls.append(a), "")[1])

    assert rrr.newest_touch("origin/master", "deleted.py") == 0
    assert rrr.newest_touch("origin/master", "deleted.py") == 0
    assert len(calls) == 1


# ── agent_branches_containing memoisation ───────────────────────────────────

def test_a_repeated_sha_is_only_asked_once(monkeypatch):
    """Periodic sweeps re-record the same branch tip under a new dated ref, so
    one sha genuinely recurs across many refs."""
    calls = []
    monkeypatch.setattr(rrr, "git",
                        lambda *a, **k: (calls.append(a),
                                         "  origin/agent/foo\n")[1])

    for _ in range(20):
        assert rrr.agent_branches_containing("deadbeef") == ["origin/agent/foo"]
    assert len(calls) == 1


def test_an_empty_result_is_cached_too(monkeypatch):
    # The uncontained case is the expensive one — git has to exhaust every agent
    # tip before it can answer "none" — so it is the one most worth caching.
    calls = []
    monkeypatch.setattr(rrr, "git", lambda *a, **k: (calls.append(a), "")[1])

    assert rrr.agent_branches_containing("cafe") == []
    assert rrr.agent_branches_containing("cafe") == []
    assert len(calls) == 1


def test_the_cached_list_cannot_be_mutated_by_a_caller(monkeypatch):
    """`classify` reads the returned list; if it were the cached object itself,
    any caller that mutated it would silently corrupt every later answer."""
    monkeypatch.setattr(rrr, "git", lambda *a, **k: "  origin/agent/foo\n")

    first = rrr.agent_branches_containing("sha1")
    first.append("origin/agent/injected")
    assert rrr.agent_branches_containing("sha1") == ["origin/agent/foo"]


def test_different_shas_are_asked_separately(monkeypatch):
    monkeypatch.setattr(rrr, "git", lambda *a, **k: "  origin/agent/" + a[3] + "\n")
    assert rrr.agent_branches_containing("aaa") == ["origin/agent/aaa"]
    assert rrr.agent_branches_containing("bbb") == ["origin/agent/bbb"]


# ── the budget, and honest partial ledgers ──────────────────────────────────

def _item(ref="refs/orch-rescue/x", sha="s"):
    return rrr.Item(ref=ref, sha=sha, subject="subj", created_at=1)


def test_an_unreached_ref_stays_unknown(monkeypatch, tmp_path):
    """The load-bearing assertion of this file.

    A budgeted scan must not guess. If an unreached ref were recorded as
    ALREADY_PRESENT the evidence would be reported as clean and the ref would
    never be looked at again; if it were CONFLICTED it would generate a
    follow-up task nobody needs. UNKNOWN is the only honest answer, and it is
    what keeps the exit code non-zero.
    """
    items = [_item(f"refs/orch-rescue/{i}", f"sha{i}") for i in range(6)]
    monkeypatch.setattr(rrr, "enumerate_refs", lambda: items)
    monkeypatch.setattr(rrr, "base_patch_ids", lambda base, depth: set())

    def slow_classify(item, base, known):
        item.classification = "ALREADY_PRESENT"
        item.disposition = "scanned"

    monkeypatch.setattr(rrr, "classify", slow_classify)

    # monotonic jumps past any positive budget on the very first check.
    ticks = iter([0.0] + [10_000.0] * 50)
    monkeypatch.setattr(rrr.time, "monotonic", lambda: next(ticks))

    out = tmp_path / "ledger.json"
    rc = rrr.main.__wrapped__ if hasattr(rrr.main, "__wrapped__") else rrr.main
    monkeypatch.setattr(sys, "argv", [
        "reconcile_rescue_refs.py", "--fingerprint", "f" * 64,
        "--base", "origin/master", "--out", str(out),
        "--max-seconds", "1", "--progress-every", "0"])

    assert rc() == 1, "a truncated scan must not exit 0"

    import json
    ledger = json.loads(out.read_text())
    assert ledger["truncated"] is True
    assert ledger["unknown"] == len(items)
    assert all(i["classification"] == "UNKNOWN" for i in ledger["items"])
    assert "budget spent" in ledger["items"][0]["disposition"]


def test_the_ledger_is_written_even_when_the_budget_is_spent(monkeypatch, tmp_path):
    # A killed scan leaves nothing behind. A budgeted one must leave a file, or
    # the budget buys nothing over being killed.
    items = [_item()]
    monkeypatch.setattr(rrr, "enumerate_refs", lambda: items)
    monkeypatch.setattr(rrr, "base_patch_ids", lambda base, depth: set())
    ticks = iter([0.0] + [10_000.0] * 20)
    monkeypatch.setattr(rrr.time, "monotonic", lambda: next(ticks))

    out = tmp_path / "nested" / "ledger.json"
    monkeypatch.setattr(sys, "argv", [
        "reconcile_rescue_refs.py", "--fingerprint", "a" * 64,
        "--out", str(out), "--max-seconds", "1", "--progress-every", "0"])
    rrr.main()
    assert out.exists()


def test_no_budget_means_no_truncation(monkeypatch, tmp_path):
    items = [_item(f"refs/orch-rescue/{i}", f"sha{i}") for i in range(4)]
    monkeypatch.setattr(rrr, "enumerate_refs", lambda: items)
    monkeypatch.setattr(rrr, "base_patch_ids", lambda base, depth: set())

    def ok(item, base, known):
        item.classification = "ALREADY_PRESENT"

    monkeypatch.setattr(rrr, "classify", ok)

    out = tmp_path / "ledger.json"
    monkeypatch.setattr(sys, "argv", [
        "reconcile_rescue_refs.py", "--fingerprint", "b" * 64,
        "--out", str(out), "--progress-every", "0"])

    assert rrr.main() == 0

    import json
    ledger = json.loads(out.read_text())
    assert ledger["truncated"] is False
    assert ledger["unknown"] == 0
    assert ledger["scan_seconds"] >= 0


def test_a_classification_error_is_still_not_unknown(monkeypatch, tmp_path):
    """Pre-existing contract, re-pinned next to the new UNKNOWN path.

    An exception means the ref WAS examined and the examination failed — that is
    a focused-follow-up, not an unexamined ref. The two must not collapse into
    one label now that UNKNOWN has a second producer.
    """
    items = [_item()]
    monkeypatch.setattr(rrr, "enumerate_refs", lambda: items)
    monkeypatch.setattr(rrr, "base_patch_ids", lambda base, depth: set())

    def boom(item, base, known):
        raise RuntimeError("git exploded")

    monkeypatch.setattr(rrr, "classify", boom)

    out = tmp_path / "ledger.json"
    monkeypatch.setattr(sys, "argv", [
        "reconcile_rescue_refs.py", "--fingerprint", "c" * 64,
        "--out", str(out), "--progress-every", "0"])

    assert rrr.main() == 0
    import json
    item = json.loads(out.read_text())["items"][0]
    assert item["classification"] == "CONFLICTED_NEEDS_FOCUSED_TASK"
    assert "git exploded" in item["disposition"]


# ── progress ────────────────────────────────────────────────────────────────

def test_progress_goes_to_stderr_so_it_never_pollutes_the_ledger_stdout(
        monkeypatch, tmp_path, capsys):
    items = [_item(f"refs/orch-rescue/{i}", f"s{i}") for i in range(4)]
    monkeypatch.setattr(rrr, "enumerate_refs", lambda: items)
    monkeypatch.setattr(rrr, "base_patch_ids", lambda base, depth: set())
    monkeypatch.setattr(rrr, "classify",
                        lambda i, b, k: setattr(i, "classification", "ALREADY_PRESENT"))

    monkeypatch.setattr(sys, "argv", [
        "reconcile_rescue_refs.py", "--fingerprint", "d" * 64,
        "--out", str(tmp_path / "l.json"), "--progress-every", "2"])
    rrr.main()

    cap = capsys.readouterr()
    assert "2/4 refs" in cap.err and "4/4 refs" in cap.err
    assert "refs," not in cap.out          # stdout stays parseable JSON
    import json
    json.loads(cap.out)


def test_progress_can_be_switched_off(monkeypatch, tmp_path, capsys):
    items = [_item(f"refs/orch-rescue/{i}", f"s{i}") for i in range(4)]
    monkeypatch.setattr(rrr, "enumerate_refs", lambda: items)
    monkeypatch.setattr(rrr, "base_patch_ids", lambda base, depth: set())
    monkeypatch.setattr(rrr, "classify",
                        lambda i, b, k: setattr(i, "classification", "ALREADY_PRESENT"))

    monkeypatch.setattr(sys, "argv", [
        "reconcile_rescue_refs.py", "--fingerprint", "e" * 64,
        "--out", str(tmp_path / "l.json"), "--progress-every", "0"])
    rrr.main()
    assert "refs," not in capsys.readouterr().err
