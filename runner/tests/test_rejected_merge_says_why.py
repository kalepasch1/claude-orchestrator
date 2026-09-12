"""The fleet's most consequential "no" was not written down anywhere.

auto_conflict_resolver._reject_merge undoes a merge that has ALREADY been committed,
because the anti-regression gate found it would destroy code. Whether that decision was
ever recorded depended entirely on the caller reading result["error"] --
continuous_merger does; the path driving this fleet does not.

The cost, read straight off master's reflog on 2026-09-04:

    05:35:48  merge agent/backlog-batch-beethoven-52d9da1
    05:35:52  reset: moving to af2ea939...            (four seconds later)
    ... four more branches, each merged and immediately reset ...
    06:31:45  merge agent/backlog-batch-beethoven-52d9da1     <- the same six branches
    06:31:49  reset: moving to af2ea939...               again, an hour later

Six branches merged and rolled back, then merged and rolled back again on the next
cycle, indefinitely. runner.log holds three REGRESSION BLOCKED lines in total, all from
2026-08-18. The work itself is safe -- the branch is deliberately preserved -- but
nothing on disk said which gate refused it or why, so nobody could either fix the branch
or agree with the gate.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import auto_conflict_resolver as acr


def test_a_rolled_back_merge_names_the_branch_and_the_finding(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(acr, "_git", lambda argv, repo: calls.append((argv, repo)))

    result = {"branch": "agent/some-slug", "merged": True, "resolved_files": ["a.py"]}
    out = acr._reject_merge("/repo", "abc123def456789", result,
                            "[net-deletion] runner/x.py: merge removes 40 lines")

    assert out["merged"] is False
    assert out["strategy"] == "regression-blocked"
    printed = capsys.readouterr().out
    assert "REGRESSION BLOCKED" in printed
    assert "agent/some-slug" in printed, printed
    assert "net-deletion" in printed, printed
    assert "abc123def456" in printed, printed


def test_the_rollback_still_happens(monkeypatch, capsys):
    """The logging is an addition, not a replacement."""
    calls = []
    monkeypatch.setattr(acr, "_git", lambda argv, repo: calls.append((argv, repo)))
    acr._reject_merge("/repo", "deadbeefcafe", {"branch": "agent/x"}, "findings")
    assert calls == [(["git", "reset", "--hard", "deadbeefcafe"], "/repo")]


def test_a_long_finding_is_bounded(monkeypatch, capsys):
    """These lines go to a log a human reads; a 12k-character gate dump does not."""
    monkeypatch.setattr(acr, "_git", lambda argv, repo: None)
    acr._reject_merge("/repo", "abc", {"branch": "agent/x"}, "x" * 5000)
    assert len(capsys.readouterr().out) < 1000
