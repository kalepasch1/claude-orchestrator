"""PROPRIETARY -- Apparently Inc. Trade Secret. Protected under DTSA (18 U.S.C. 1836).

Revert-mutation / vacuity gate for the orchestrator DoD.

The single highest-value objective gate the manual loop does not yet have: after
a task's proof test is green, mechanically REVERT the task's change and confirm
the SAME proof test now FAILS. A test that still passes after the change is
reverted proves nothing about the change (tautological / self-passing) and must
be rejected. This makes the automated DoD strictly stronger than "test is green".

Pure orchestration (assess_vacuity) is injectable so it is unit-tested without
git or a test runner; make_git_vacuity_probe wires the real git+subprocess probe.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import Callable, Optional, Sequence


@dataclass
class VacuityResult:
    passed: bool
    reason: str
    green_before: bool
    green_after_revert: Optional[bool]


def assess_vacuity(
    run_test: Callable[[], bool],
    apply_revert: Callable[[], None],
    restore: Callable[[], None],
) -> VacuityResult:
    """Return passed=True only if the proof test is green now AND fails once the
    change is reverted. `restore` is ALWAYS called, even if a probe raises."""
    green_before = bool(run_test())
    if not green_before:
        return VacuityResult(False, "proof test is not green before revert", False, None)

    apply_revert()
    try:
        green_after_revert = bool(run_test())
    finally:
        restore()

    if green_after_revert:
        return VacuityResult(
            False,
            "VACUOUS: proof test still passes after reverting the change -- test does not exercise the change",
            True,
            True,
        )
    return VacuityResult(True, "non-vacuous: proof test is sensitive to the change", True, False)


def make_git_vacuity_probe(
    repo_dir: str,
    changed_paths: Sequence[str],
    test_cmd: Sequence[str],
    run: Optional[Callable[..., subprocess.CompletedProcess]] = None,
):
    """Build (run_test, apply_revert, restore) that revert the change by checking
    out its parent revision for the changed paths, then restore HEAD. Injectable
    `run` for testing."""
    _run = run or (lambda cmd: subprocess.run(cmd, cwd=repo_dir, capture_output=True))
    paths = list(changed_paths)

    def run_test() -> bool:
        return _run(list(test_cmd)).returncode == 0

    def apply_revert() -> None:
        _run(["git", "checkout", "HEAD~1", "--", *paths])

    def restore() -> None:
        _run(["git", "checkout", "HEAD", "--", *paths])

    return run_test, apply_revert, restore
