"""No tracked Python file may carry unresolved merge-conflict markers.

Four files were committed to master with `<<<<<<< HEAD` still in them
(hisanta/__init__.py, both copies of contracts/family.py, and
hisanta/hisanta/mastery/engine.py). Each was a SyntaxError, so
tests/test_gifting_protocol.py, tests/test_kindness_mint.py and
tests/test_school_mode.py — 23 tests — could not even be collected, and pytest
reported "3 errors during collection" rather than a failure anyone read as a
broken merge.

A committed conflict marker is always a mistake and is trivially detectable, so
it should never survive a second time.
"""
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# Split so this file does not match its own guard.
MARKERS = ("<" * 7 + " ", "=" * 7, ">" * 7 + " ")


def _tracked_python_files():
    try:
        out = subprocess.run(
            ["git", "ls-files", "-z", "*.py"], cwd=REPO_ROOT,
            capture_output=True, text=True, timeout=60, check=True).stdout
    except (OSError, subprocess.SubprocessError):
        pytest.skip("git not available")
    return [REPO_ROOT / p for p in out.split("\0") if p]


def test_no_conflict_markers_in_tracked_python_files():
    offenders = []
    for path in _tracked_python_files():
        if path.resolve() == Path(__file__).resolve() or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            if line.startswith(MARKERS[0]) or line.startswith(MARKERS[2]) \
                    or line.rstrip() == MARKERS[1]:
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{lineno}")
    assert offenders == [], \
        "unresolved merge-conflict markers: " + ", ".join(offenders[:20])


@pytest.mark.parametrize("module", [
    "hisanta/__init__.py",
    "hisanta/contracts/family.py",
    "hisanta/hisanta/contracts/family.py",
    "hisanta/hisanta/mastery/engine.py",
])
def test_previously_conflicted_modules_compile(module):
    """The four files the bad merge broke must stay syntactically valid."""
    path = REPO_ROOT / module
    compile(path.read_text(encoding="utf-8"), str(path), "exec")


def test_both_import_spellings_yield_the_same_objects():
    """hisanta/contracts is canonical; the nested copy is a pure re-export.

    This identity is the whole point of the resolution: an isinstance check or
    an enum comparison must not fail just because a caller reached the domain
    through hisanta.hisanta.contracts.family instead.
    """
    import hisanta.contracts.family as canonical
    import hisanta.hisanta.contracts.family as nested

    assert nested.__all__, "nested shim exports nothing"
    for name in nested.__all__:
        assert getattr(canonical, name) is getattr(nested, name), name


def test_approval_status_is_defined_and_complete():
    """ParentApproval.status defaults to ApprovalStatus.APPROVED.

    The enum lived only on the losing side of the merge, so resolving toward
    the canonical file left the annotation pointing at an undefined name.
    """
    from hisanta.contracts.family import ApprovalStatus, ParentApproval

    assert {m.name for m in ApprovalStatus} == {"APPROVED", "DENIED", "PENDING"}
    assert {m.value for m in ApprovalStatus} == {"approved", "denied", "pending"}
    assert ParentApproval().status is ApprovalStatus.APPROVED


def test_constitution_action_is_an_alias_not_a_second_enum():
    from hisanta.contracts.family import ConstitutionAction, ConstitutionVerdict

    assert ConstitutionAction is ConstitutionVerdict
