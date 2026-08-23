"""A release that CONTAINS the artifact commit is evidence; equality was too strict.

Measured 2026-08-23, after 419 real production releases had been reconciled into
the table: six task artifacts in the entire history matched a live release by sha.
Six rows, not six percent. smarter merges branches into main and deploys main, so
the artifact commit is inside a merge commit and can never equal the release head.
Every MERGED task therefore stopped at LEVEL_MERGED reporting "no release names
this artifact commit as its head" -- true, and useless.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import canonical_proof_ledger as ledger
import git_ancestry

ARTIFACT = "a" * 40
MERGE_HEAD = "b" * 40
OTHER = "c" * 40


def _release(to_sha, created="2026-08-20T00:00:00Z", status="success", rid="rel_1"):
    return {"id": rid, "project": "smarter", "to_sha": to_sha,
            "deploy_status": status, "vercel_url": "apparently.cc",
            "created_at": created}


def _contains(pairs):
    """contains_fn over an explicit {(head, candidate): answer} map."""
    def fn(head, candidate, project=None):
        return pairs.get((str(head or "").lower(), str(candidate or "").lower()))
    return fn


# ------------------------------------------------------------ _live_release_for

def test_without_a_contains_fn_behaviour_is_unchanged():
    rel, why = ledger._live_release_for(ARTIFACT, [_release(MERGE_HEAD)])
    assert rel is None
    assert why == "no release names this artifact commit as its head"


def test_a_merge_release_containing_the_artifact_now_counts():
    rel, why = ledger._live_release_for(
        ARTIFACT, [_release(MERGE_HEAD)],
        contains_fn=_contains({(MERGE_HEAD, ARTIFACT): True}))
    assert rel is not None, why
    assert rel["to_sha"] == MERGE_HEAD


def test_a_release_that_does_not_contain_it_still_does_not_count():
    rel, why = ledger._live_release_for(
        ARTIFACT, [_release(OTHER)],
        contains_fn=_contains({(OTHER, ARTIFACT): False}))
    assert rel is None
    assert "no live release contains" in why


def test_unknown_is_not_containment():
    """A clone that cannot answer must not be read as a yes."""
    rel, why = ledger._live_release_for(
        ARTIFACT, [_release(MERGE_HEAD)],
        contains_fn=_contains({(MERGE_HEAD, ARTIFACT): None}))
    assert rel is None, "None means we could not check, never that it contains"


def test_a_dead_release_that_contains_it_is_still_dead():
    rel, why = ledger._live_release_for(
        ARTIFACT, [_release(MERGE_HEAD, status="failed")],
        contains_fn=_contains({(MERGE_HEAD, ARTIFACT): True}))
    assert rel is None
    assert "did not deploy" in why or "not live" in why


def test_a_release_predating_the_artifact_cannot_certify_it_even_if_reachable():
    """Guards a real hazard: ancestry is time-blind, the stale rule is not."""
    rel, why = ledger._live_release_for(
        ARTIFACT, [_release(MERGE_HEAD, created="2026-08-01T00:00:00Z")],
        artifact_at="2026-08-15T00:00:00Z",
        contains_fn=_contains({(MERGE_HEAD, ARTIFACT): True}))
    assert rel is None
    assert why == ledger.STALE_RELEASE_NOTE


def test_the_exact_head_wins_over_a_later_release_that_merely_contains_it():
    exact = _release(ARTIFACT, created="2026-08-10T00:00:00Z", rid="rel_exact")
    merged = _release(MERGE_HEAD, created="2026-08-20T00:00:00Z", rid="rel_merge")
    rel, _ = ledger._live_release_for(
        ARTIFACT, [merged, exact],
        contains_fn=_contains({(MERGE_HEAD, ARTIFACT): True}))
    assert rel["id"] == "rel_exact"


def test_exact_matches_never_consult_the_oracle():
    def explode(*a, **k):
        raise AssertionError("contains_fn must not be called for an exact match")

    rel, _ = ledger._live_release_for(ARTIFACT, [_release(ARTIFACT)], contains_fn=explode)
    assert rel is not None


# ----------------------------------------------------------------- projection

def _evidence(releases, journeys=None, project="smarter"):
    return {"artifacts": {}, "releases": releases, "journeys": journeys or {},
            "read_errors": [], "project": project}


def test_the_project_comes_from_the_bundle_when_the_task_has_none():
    """tasks carry a project_id uuid, not a name; the bundle is built per project."""
    seen = []

    def fn(head, candidate, project=None):
        seen.append(project)
        return True

    ledger.project_task({"slug": "s", "state": "MERGED", "artifact_commit": ARTIFACT},
                        _evidence([_release(MERGE_HEAD)], project="smarter"),
                        contains_fn=fn)
    assert seen and seen[0] == "smarter"


def test_a_merged_task_reaches_released_through_containment():
    entry = ledger.project_task(
        {"slug": "s", "state": "MERGED", "artifact_commit": ARTIFACT, "project": "smarter"},
        _evidence([_release(MERGE_HEAD)]),
        contains_fn=_contains({(MERGE_HEAD, ARTIFACT): True}))
    assert entry["level"] == ledger.LEVEL_RELEASED
    assert entry["verdict"] == ledger.PENDING, "released is not verified"
    assert "match=contains" in entry["receipt"]["detail"]


def test_containment_alone_never_reaches_verified():
    """The whole safety argument: ancestry cannot see a revert, a journey can."""
    entry = ledger.project_task(
        {"slug": "s", "state": "MERGED", "artifact_commit": ARTIFACT, "project": "smarter"},
        _evidence([_release(MERGE_HEAD)]),
        contains_fn=_contains({(MERGE_HEAD, ARTIFACT): True}))
    assert entry["level"] != ledger.LEVEL_DEPLOYED_AND_VERIFIED


def test_containment_plus_a_passing_journey_reaches_verified():
    journeys = {MERGE_HEAD: [{"release_sha": MERGE_HEAD, "journey": "http", "ok": True,
                              "url": "https://apparently.cc",
                              "recorded_at": "2026-08-23T17:53:58Z"}]}
    entry = ledger.project_task(
        {"slug": "s", "state": "MERGED", "artifact_commit": ARTIFACT, "project": "smarter"},
        _evidence([_release(MERGE_HEAD)], journeys),
        contains_fn=_contains({(MERGE_HEAD, ARTIFACT): True}))
    assert entry["level"] == ledger.LEVEL_DEPLOYED_AND_VERIFIED
    assert entry["verdict"] == ledger.PASS
    assert entry["receipt"] is not None


def test_an_exact_match_says_head_not_contains():
    entry = ledger.project_task(
        {"slug": "s", "state": "MERGED", "artifact_commit": ARTIFACT, "project": "smarter"},
        _evidence([_release(ARTIFACT)]), contains_fn=_contains({}))
    assert "match=head" in entry["receipt"]["detail"]
    assert "is the artifact commit" in " ".join(entry["reasons"])


# ------------------------------------------------------------------- the oracle

def _fake_git(answers, objects=None, calls=None):
    """(rc, stdout) for the two git commands the oracle issues."""
    objects = objects if objects is not None else set()

    def run(repo, args, timeout=None):
        if calls is not None:
            calls.append(args)
        if args[0] == "cat-file":
            sha = args[2].split("^")[0]
            return (0 if sha in objects else 1), ""
        if args[:2] == ["merge-base", "--is-ancestor"]:
            candidate, head = args[2], args[3]
            answer = answers.get((head, candidate))
            if answer is None:
                return 128, ""
            return (0 if answer else 1), ""
        return 128, ""
    return run


@pytest.fixture
def repo(tmp_path):
    (tmp_path / ".git").mkdir()
    return str(tmp_path)


def test_oracle_reports_containment(repo):
    o = git_ancestry.AncestryOracle(lambda p: repo,
                                    run=_fake_git({(MERGE_HEAD, ARTIFACT): True},
                                                  objects={ARTIFACT, MERGE_HEAD}))
    assert o.contains(MERGE_HEAD, ARTIFACT, "smarter") is True


def test_oracle_reports_non_containment(repo):
    o = git_ancestry.AncestryOracle(lambda p: repo,
                                    run=_fake_git({(OTHER, ARTIFACT): False},
                                                  objects={ARTIFACT, OTHER}))
    assert o.contains(OTHER, ARTIFACT, "smarter") is False


def test_a_missing_object_is_unknown_not_absent(repo):
    """A shallow clone that never fetched the commit cannot answer."""
    o = git_ancestry.AncestryOracle(lambda p: repo,
                                    run=_fake_git({}, objects={MERGE_HEAD}))
    assert o.contains(MERGE_HEAD, ARTIFACT, "smarter") is None


def test_a_project_with_no_clone_is_unknown():
    o = git_ancestry.AncestryOracle(lambda p: None, run=_fake_git({}))
    assert o.contains(MERGE_HEAD, ARTIFACT, "nowhere") is None


def test_a_commit_contains_itself_without_spending_budget(repo):
    calls = []
    o = git_ancestry.AncestryOracle(lambda p: repo, run=_fake_git({}, calls=calls))
    assert o.contains(ARTIFACT, ARTIFACT, "smarter") is True
    assert calls == [], "the common case must not shell out"


def test_answers_are_memoised(repo):
    calls = []
    o = git_ancestry.AncestryOracle(
        lambda p: repo,
        run=_fake_git({(MERGE_HEAD, ARTIFACT): True}, objects={ARTIFACT, MERGE_HEAD},
                      calls=calls))
    for _ in range(5):
        assert o.contains(MERGE_HEAD, ARTIFACT, "smarter") is True
    ancestry_calls = [c for c in calls if c[0] == "merge-base"]
    assert len(ancestry_calls) == 1, f"{len(ancestry_calls)} git calls for one question"


def test_the_call_ceiling_degrades_to_unknown_not_to_false(repo):
    o = git_ancestry.AncestryOracle(
        lambda p: repo, call_ceiling=0,
        run=_fake_git({(MERGE_HEAD, ARTIFACT): True}, objects={ARTIFACT, MERGE_HEAD}))
    assert o.contains(MERGE_HEAD, ARTIFACT, "smarter") is None
    assert o.stats()["exhausted"] is True


def test_git_failing_to_run_is_unknown(repo):
    def dead(repo_, args, timeout=None):
        return None, ""

    o = git_ancestry.AncestryOracle(lambda p: repo, run=dead)
    assert o.contains(MERGE_HEAD, ARTIFACT, "smarter") is None


def test_blank_shas_are_unknown(repo):
    o = git_ancestry.AncestryOracle(lambda p: repo, run=_fake_git({}))
    assert o.contains("", ARTIFACT, "smarter") is None
    assert o.contains(MERGE_HEAD, None, "smarter") is None
