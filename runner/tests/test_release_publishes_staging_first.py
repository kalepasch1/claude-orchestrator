"""45 failed releases whose real reason was one line above the one that got recorded.

sustainable-barks recorded this, 45 times over three days, and it is git's LAST line:

    error: failed to push some refs to 'https://github.com/kalepasch1/Sustainable_Barks.git'

The line above it was the reason:

    production_push_guard: BLOCKED — production push that never met staging
    11fad7ff6a31 is not contained in origin/orchestrator/dev — 1 commit(s) would
    reach production without ever being integrated on staging.

_integrate_prod_into_staging() creates a NEW merge commit on the LOCAL staging branch
(prod integrated into staging, then re-gated). _integrate_regate_and_push() then pushed
that straight to prod -- promoting a commit that existed only on this machine's disk.
The guard refused it, correctly, every time.

The guard's own remedy text spells out the missing step:

    git push origin HEAD:refs/heads/orchestrator/dev
    git push origin <new-dev-sha>:refs/heads/main

This was invisible until 57a1646d fixed the proof lookup, because the guard checked the
build proof FIRST and stopped there. One masked failure hiding the next is why the row
said only "failed to push some refs" for three days.

FAIL-CLOSED on the staging publish. If the integrated tip cannot reach the shared
staging branch, the release does not happen -- promoting it anyway is how one machine's
local merge reaches production without meeting the rest of the in-flight work, which is
the whole failure the guard exists to prevent.
"""
import ast
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

RUNNER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _fn_source():
    with open(os.path.join(RUNNER, "release_train.py")) as fh:
        src = fh.read()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_integrate_regate_and_push":
            return src, node, ast.get_source_segment(src, node) or ""
    raise AssertionError("_integrate_regate_and_push() not found")


def test_staging_is_published_before_prod_is_promoted():
    """The regression, stated as an ordering."""
    _src, _node, seg = _fn_source()
    staging_push = seg.find('f"{STAGING}:{STAGING}"')
    prod_push = seg.find('f"{STAGING}:{prod}"')
    assert staging_push != -1, (
        "the integrated tip is never pushed to origin/<staging>; the production push "
        "guard will refuse it as 'never met staging'")
    assert prod_push != -1, "the production push is gone"
    assert staging_push < prod_push, (
        "staging is published AFTER prod is promoted, which is no help at all")


def test_the_staging_publish_is_skipped_when_already_contained():
    """A tip already on origin/<staging> needs no push; this runs on every release."""
    _src, _node, seg = _fn_source()
    assert "merge-base" in seg and "--is-ancestor" in seg
    guard = seg.find("--is-ancestor")
    staging_push = seg.find('f"{STAGING}:{STAGING}"')
    assert guard < staging_push, "the containment check must gate the push, not follow it"


def test_a_failed_staging_publish_stops_the_release():
    """FAIL-CLOSED. Promoting a tip that never reached the shared branch is the exact
    thing the guard refuses."""
    _src, _node, seg = _fn_source()
    window = seg[seg.find('f"{STAGING}:{STAGING}"'):seg.find('f"{STAGING}:{prod}"')]
    assert "return False" in window, (
        "a failed staging publish falls through to the production push")
    assert "staging-publish" in window, (
        "the failure is not recorded under its own gate name, so it will look like a "
        "push failure again")


def test_a_moved_staging_branch_retries_the_whole_sequence():
    """origin/<staging> advancing mid-release is normal; it must re-integrate, not
    force."""
    _src, _node, seg = _fn_source()
    window = seg[seg.find('f"{STAGING}:{STAGING}"'):seg.find('f"{STAGING}:{prod}"')]
    assert "_is_non_fast_forward" in window
    assert "continue" in window
    assert "--force" not in window and "-f " not in window


def test_shadow_mode_covers_the_new_push():
    """Shadow mode's whole promise is that no shared ref moves. A new push that
    bypassed it would be a hole in the one switch the operator is asked to trust."""
    _src, _node, seg = _fn_source()
    window = seg[seg.find('f"{STAGING}:{STAGING}"') - 900:seg.find('f"{STAGING}:{STAGING}"')]
    assert "shadow_mode.refuse" in window
    assert "push-integration-branch" in window


def test_the_production_promotion_is_unchanged():
    """This adds a step; it must not have altered the one that was already right."""
    _src, _node, seg = _fn_source()
    assert 'push", "origin", f"{STAGING}:{prod}"' in seg
    assert "delivery_lease.require" in seg
    assert "promote-to-production" in seg
