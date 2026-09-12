#!/usr/bin/env python3
"""A failed worktree preparation must not look like a repo that needed nothing.

prepare_worktree returned `[]` for both "this repo has no dependencies to link"
and "the preparation raised". Those are opposite facts, and conflating them is
expensive in one specific direction: when preparation had actually failed, the
worktree was handed to a task with no node_modules and no .nuxt, and the run
died on ERR_MODULE_NOT_FOUND. That reads as broken code rather than as an
unprepared checkout, so the agent debugs source it never touched.

Same shape as the .nuxt gap one layer down — a setup problem wearing a source
problem's clothes — and silence is what let it wear the costume.

Fail-soft is preserved on purpose: a bug in preparation still must not block a
project. The report just says what happened.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import worktree_preflight as preflight  # noqa: E402


class StubPrewarm:
    def __init__(self, result=None, raises=None):
        self.result = result
        self.raises = raises
        self.calls = []

    def link_shared_runtime(self, repo, worktree):
        self.calls.append((repo, worktree))
        if self.raises:
            raise self.raises
        return self.result


@pytest.fixture
def stub(monkeypatch):
    def install(prewarm):
        monkeypatch.setitem(sys.modules, "dependency_prewarm", prewarm)
        return prewarm
    return install


class TestSuccessAndNoOpAreDistinguishable:
    def test_a_successful_preparation_reports_what_it_linked(self, stub):
        stub(StubPrewarm(result=["/wt/node_modules", "/wt/.nuxt"]))
        report = preflight.prepare_worktree_report("/repo", "/wt")
        assert report["error"] is None
        assert report["linked"] == ["/wt/node_modules", "/wt/.nuxt"]

    def test_a_repo_needing_nothing_reports_no_error(self, stub):
        stub(StubPrewarm(result=[]))
        report = preflight.prepare_worktree_report("/repo", "/wt")
        assert report == {"linked": [], "error": None}


class TestAFailureIsNamed:
    def test_the_error_is_reported_rather_than_swallowed(self, stub):
        stub(StubPrewarm(raises=OSError("disk full")))
        report = preflight.prepare_worktree_report("/repo", "/wt")
        assert report["linked"] == []
        assert "OSError" in report["error"]
        assert "disk full" in report["error"]

    def test_a_failure_is_not_mistaken_for_a_no_op(self, stub):
        stub(StubPrewarm(raises=RuntimeError("boom")))
        failed = preflight.prepare_worktree_report("/repo", "/wt")
        stub(StubPrewarm(result=[]))
        nothing_to_do = preflight.prepare_worktree_report("/repo", "/wt")
        assert failed["linked"] == nothing_to_do["linked"] == []
        assert failed["error"] is not None
        assert nothing_to_do["error"] is None

    def test_the_failure_is_printed_with_both_paths(self, stub, capsys):
        stub(StubPrewarm(raises=RuntimeError("boom")))
        preflight.prepare_worktree_report("/repo", "/wt")
        printed = capsys.readouterr().out
        assert "/wt" in printed
        assert "/repo" in printed
        assert "FAILED" in printed


class TestFailSoftIsPreserved:
    def test_it_never_raises(self, stub):
        stub(StubPrewarm(raises=RuntimeError("boom")))
        # A bug in preparation must not be able to block a project.
        assert preflight.prepare_worktree_report("/repo", "/wt")["error"]

    def test_the_old_signature_still_returns_a_list(self, stub):
        stub(StubPrewarm(result=["/wt/node_modules"]))
        assert preflight.prepare_worktree("/repo", "/wt") == ["/wt/node_modules"]

    def test_the_old_signature_is_still_fail_soft(self, stub):
        stub(StubPrewarm(raises=RuntimeError("boom")))
        assert preflight.prepare_worktree("/repo", "/wt") == []

    def test_nonexistent_paths_are_still_fail_soft(self):
        # The behaviour the existing suite pins, unchanged.
        assert preflight.prepare_worktree("/nonexistent", "/also-nonexistent") == []
