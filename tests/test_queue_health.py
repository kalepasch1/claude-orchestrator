"""Tests for tools/queue_health.py.

Covers the two ways a QUEUED task becomes invisible to every executor:

  * an unsatisfied dependency (the deadlock in QUEUE-DEADLOCK-2026-08-25.md), and
  * `project_id IS NULL`, which the claim CTE's inner join on projects drops
    silently and permanently.

Both currently read as "queue empty" at the claim step. The point of the tool is
that they must not.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from tools.queue_health import (  # noqa: E402
    blocking_deps,
    classify_task,
    deps_of,
    summarize,
)

PROJECT = "11111111-1111-1111-1111-111111111111"
OTHER_PROJECT = "22222222-2222-2222-2222-222222222222"
PROJECT_IDS = {PROJECT, OTHER_PROJECT}


def task(slug, project_id=PROJECT, deps=None, kind="build"):
    return {"slug": slug, "project_id": project_id, "deps": deps, "kind": kind}


@pytest.fixture
def satisfied():
    return {PROJECT: {"done-1", "merged-1"}}


class TestDepsOf:
    def test_none_deps_is_empty(self):
        assert deps_of(task("a", deps=None)) == []

    def test_empty_list_is_empty(self):
        assert deps_of(task("a", deps=[])) == []

    def test_blank_entries_are_dropped(self):
        assert deps_of(task("a", deps=["real", "", None])) == ["real"]


class TestBlockingDeps:
    def test_satisfied_dep_does_not_block(self, satisfied):
        assert blocking_deps(task("a", deps=["done-1"]), satisfied) == []

    def test_unsatisfied_dep_blocks(self, satisfied):
        assert blocking_deps(task("a", deps=["nope"]), satisfied) == ["nope"]

    def test_only_the_unsatisfied_deps_are_reported(self, satisfied):
        blocking = blocking_deps(task("a", deps=["done-1", "nope"]), satisfied)
        assert blocking == ["nope"]

    def test_satisfaction_does_not_leak_across_projects(self, satisfied):
        # `done-1` is DONE in PROJECT, not in OTHER_PROJECT.
        item = task("a", project_id=OTHER_PROJECT, deps=["done-1"])
        assert blocking_deps(item, satisfied) == ["done-1"]


class TestClassifyTask:
    def test_no_deps_is_claimable(self, satisfied):
        verdict, _ = classify_task(task("a"), PROJECT_IDS, satisfied)
        assert verdict == "claimable"

    def test_satisfied_deps_are_claimable(self, satisfied):
        verdict, _ = classify_task(task("a", deps=["done-1", "merged-1"]),
                                   PROJECT_IDS, satisfied)
        assert verdict == "claimable"

    def test_unsatisfied_dep_is_blocked_and_names_the_blocker(self, satisfied):
        verdict, detail = classify_task(task("a", deps=["ghost"]),
                                        PROJECT_IDS, satisfied)
        assert verdict == "blocked"
        assert "ghost" in detail

    def test_null_project_id_is_an_orphan(self, satisfied):
        verdict, detail = classify_task(task("a", project_id=None),
                                        PROJECT_IDS, satisfied)
        assert verdict == "orphan_project"
        assert "never be claimed" in detail

    def test_unknown_project_id_is_an_orphan(self, satisfied):
        verdict, detail = classify_task(task("a", project_id="deadbeef"),
                                        PROJECT_IDS, satisfied)
        assert verdict == "orphan_project"
        assert "no row in projects" in detail

    def test_orphan_check_precedes_the_dependency_check(self, satisfied):
        # A NULL-project task with satisfiable deps is still unclaimable, and
        # reporting it as merely "blocked" would send someone chasing the deps.
        verdict, _ = classify_task(task("a", project_id=None, deps=["done-1"]),
                                   PROJECT_IDS, satisfied)
        assert verdict == "orphan_project"

    def test_speculative_is_excluded_not_blocked(self, satisfied):
        verdict, _ = classify_task(task("a", kind="speculative"),
                                   PROJECT_IDS, satisfied)
        assert verdict == "speculative"


class TestSummarize:
    def test_empty_queue_is_not_deadlocked(self, satisfied):
        report = summarize([], PROJECT_IDS, satisfied)
        assert report["queued"] == 0
        assert report["deadlocked"] is False

    def test_queue_with_claimable_work_is_not_deadlocked(self, satisfied):
        report = summarize([task("a"), task("b", deps=["ghost"])],
                           PROJECT_IDS, satisfied)
        assert report["claimable"] == 1
        assert report["deadlocked"] is False

    def test_fully_blocked_queue_is_deadlocked(self, satisfied):
        report = summarize([task("a", deps=["ghost"]), task("b", deps=["ghost"])],
                           PROJECT_IDS, satisfied)
        assert report["queued"] == 2
        assert report["claimable"] == 0
        assert report["blocked"] == 2
        assert report["deadlocked"] is True

    def test_a_queue_held_up_only_by_orphans_is_deadlocked(self, satisfied):
        # This is the case that used to be indistinguishable from an empty
        # queue: the count query said one task was claimable, the claim CTE
        # returned zero rows, and nothing reconciled the two.
        report = summarize([task("a", project_id=None)], PROJECT_IDS, satisfied)
        assert report["orphan_project"] == 1
        assert report["claimable"] == 0
        assert report["deadlocked"] is True

    def test_buckets_carry_the_slugs(self, satisfied):
        report = summarize([task("orphaned", project_id=None)],
                           PROJECT_IDS, satisfied)
        assert report["buckets"]["orphan_project"][0]["slug"] == "orphaned"

    def test_counts_add_up_to_the_queued_total(self, satisfied):
        tasks = [
            task("claimable-1"),
            task("blocked-1", deps=["ghost"]),
            task("orphan-1", project_id=None),
            task("spec-1", kind="speculative"),
        ]
        report = summarize(tasks, PROJECT_IDS, satisfied)
        total = (report["claimable"] + report["blocked"]
                 + report["orphan_project"] + report["speculative"])
        assert total == report["queued"] == 4
