"""A consolidated backlog batch is not itself a collapsed stub.

The recovery loop collapses stub tasks into one batch prompt that QUOTES the stubs it
replaced. Because `is_collapsed` matched `PATCH TEMPLATE <hex>` anywhere in the text, the
batch it had just produced was re-classified as collapsed on the next audit and recovered
again — the loop re-recovering its own output. preflight_filter/parallel_dispatch already
apply the near-top-or-short-body rule; this brings the audit into line with them.
"""
import os
import sys

RUNNER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runner")
if RUNNER not in sys.path:
    sys.path.insert(0, RUNNER)

import backlog_audit  # noqa: E402

REAL_STUB = (
    "PATCH TEMPLATE 3d86782460c5\n"
    "Intent: 0010789999 001082 05907660 060155600 0686892 0697712 15934 17762 19785\n"
    "Acceptance: preserve existing behavior, make the smallest mergeable diff, "
    "run build/tests.\n"
)

CONSOLIDATED_BATCH = (
    "## ORCHESTRATION PIPELINE CONTRACT\n"
    "- source: backlog-compactor\n"
    "- project: beethoven\n"
    "- task class: plan\n"
    "- coordination rule: reconcile with active loop-generated work, reuse prior "
    "solutions first, do not delete or overwrite unrelated queued improvements.\n"
    "## END ORCHESTRATION PIPELINE CONTRACT\n\n"
    "# Original improvement request\n"
    "Consolidated stale backlog recovery.\n\n"
    "Original intents:\n"
    "1. multi-agent-debate-hard-slice-1: - PATCH TEMPLATE 3d86782460c5 Intent: 0010789 "
    "001082 05907660 060155600 0686892 0697712 15934 17762 19785 200000\n"
    "2. provider-failover-sla-slice-1: - PATCH TEMPLATE fc13d0739285 Intent: 0398eb6 "
    "07071626 1ad7cbc 27d8ff8 2807983 4a3feba 750555b 865741a\n\n"
    "Select the smallest coherent high-value implementation that covers the most "
    "repeated intent. Do not recreate one task per bullet. Reuse existing code, "
    "merged-diff patterns, and current project conventions. Run relevant checks and "
    "commit. If some bullets are obsolete or already covered by release work, leave "
    "them collapsed.\n"
)


def test_real_stub_still_detected():
    assert backlog_audit.is_collapsed(REAL_STUB) is True


def test_tagged_short_stub_still_detected():
    assert backlog_audit.is_collapsed("[patch-template:fc13d0739285] transplant it") is True


def test_hex_bag_intent_still_detected_without_header():
    assert backlog_audit.is_collapsed(
        "Intent: 0398eb6 07071626 1ad7cbc 27d8ff8 2807983 4a3feba 750555b 865741a\n"
    ) is True


def test_consolidated_batch_is_not_collapsed():
    assert backlog_audit.is_collapsed(CONSOLIDATED_BATCH) is False


def test_real_task_mentioning_a_sha_is_not_collapsed():
    assert backlog_audit.is_collapsed(
        "## TASK\nRevert the regression introduced in d90037dd and add a regression "
        "test that pins the corrected banner text so it cannot drift again.\n"
    ) is False


def test_empty_and_garbage_inputs_are_fail_soft():
    assert backlog_audit.is_collapsed("") is False
    assert backlog_audit.is_collapsed(None) is False


def test_intent_summary_recovers_the_batch_directive():
    summary = backlog_audit.intent_summary(CONSOLIDATED_BATCH)
    assert "smallest coherent high-value implementation" in summary


def test_hashes_from_the_batch_are_still_recoverable():
    hashes = backlog_audit.extract_hashes(CONSOLIDATED_BATCH)
    assert "3d86782460c5" in hashes and "fc13d0739285" in hashes
