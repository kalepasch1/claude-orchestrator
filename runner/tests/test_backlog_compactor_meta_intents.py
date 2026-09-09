"""The backlog compactor must not recycle the planner's own bookkeeping.

`backlog_compactor` collapses stale queued tasks into one batch task by quoting
each one's original request as a bullet. It quoted every request, including the
two kinds that describe no work at all:

  * an EMPTY original request. `backlog-batch-tomorrow-9d5e4db-slice-1` reached
    the queue reading, in full:

        Original intents:
        1.

    A task with no described change. No agent can do anything with it, and it
    still consumes a claim from one of sixteen executors.

  * a DECOMPOSITION instruction. `backlog-batch-tomorrow-9d5e4db`'s only intent
    was "Split the initial build task into 3-4 smaller sub-tasks"; the batch was
    then decomposed again into slices that say the same thing.
    `backlog-batch-tomorrow-27c692f` decomposed into five children that are all
    "split the build task into...", "verify the task cannot be split", "reply
    ATOMIC". Nine tasks across two families, none able to produce a diff.

The loop feeds on its own output: planner bookkeeping becomes a build task,
which is decomposed into more bookkeeping. Nothing errors, the queue simply
fills with work that cannot be done — which is why it ran for so long.

The filter is deliberately narrow. It matches the planner's stock phrasings, not
anything that mentions a task, because dropping a real request would lose work
silently and that is a worse failure than the one being fixed.
"""
import os
import sys

import pytest

RUNNER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RUNNER)

import backlog_compactor as bc  # noqa: E402


def row(prompt, slug="t"):
    return {"slug": slug, "prompt": prompt, "id": slug}


# ── what counts as planner bookkeeping ──────────────────────────────────────

@pytest.mark.parametrize("text", [
    "Split the initial build task into 3-4 smaller sub-tasks.",
    "Split the build task into 2-5 smaller sub-tasks, each with a concrete acceptance test.",
    "Split the failed build task into 2-5 smaller sub-tasks",
    "Split the original build task into smaller sub-tasks",
    "Split the large task into smaller subtasks",
    "If the task is atomic and small, reply 'ATOMIC'.",
    "Double-check that the task cannot be split into smaller sub-tasks and is genuinely atomic "
    "and small. If so, reply 'ATOMIC'.",
    "Verify the task cannot be split into smaller sub-tasks",
])
def test_decomposition_instructions_are_recognised(text):
    assert bc.is_meta_intent(text), text


@pytest.mark.parametrize("text", [
    "Fix the OAuth session expiry handling in the runner.",
    "The production build is RED. Make npm run build pass with the smallest change.",
    "Add a retry to the settlement queue writer.",
    "Split the payment into two ledger rows so partial refunds reconcile.",
    "Reconcile the local ChatGPT/Codex build evidence without destroying it.",
    "Implement unit tests for currency determination.",
])
def test_real_requests_are_not_mistaken_for_bookkeeping(text):
    """The direction that must not over-fire.

    Dropping a genuine request loses work silently, which is worse than the loop
    this filter exists to stop. Note the fourth case: a request that legitimately
    says "split" about the product, not about the task.
    """
    assert not bc.is_meta_intent(text), text


def test_empty_and_none_are_not_meta_but_are_still_dropped():
    # is_meta_intent answers one question only; emptiness is handled separately
    # so the two reasons stay distinguishable in the counters.
    assert not bc.is_meta_intent("")
    assert not bc.is_meta_intent(None)


# ── what survives collapsing ────────────────────────────────────────────────

def test_an_empty_intent_is_dropped():
    assert bc.collapsible([row("")]) == []
    assert bc.collapsible([row("   \n  ")]) == []


def test_a_decomposition_only_row_is_dropped():
    assert bc.collapsible([row("Split the build task into 2-5 smaller sub-tasks.")]) == []


def test_real_work_survives():
    keep = bc.collapsible([row("Fix the OAuth session expiry handling.", "real")])
    assert [r["slug"] for r in keep] == ["real"]


def test_a_mixed_group_keeps_only_the_real_work():
    rows = [
        row("Split the build task into smaller sub-tasks", "meta-1"),
        row("", "empty"),
        row("Fix the failing migration name check", "real-1"),
        row("If the task is atomic and small, reply 'ATOMIC'.", "meta-2"),
        row("Add a timeout to the reconciler", "real-2"),
    ]
    assert [r["slug"] for r in bc.collapsible(rows)] == ["real-1", "real-2"]


def test_the_orchestration_wrapper_is_stripped_before_judging():
    """Intents arrive wrapped in the pipeline contract.

    Matching against the raw prompt would let the wrapper's own boilerplate —
    which contains phrases like "do not recreate one task per bullet" — decide
    the verdict for every row.
    """
    import pipeline_contract
    wrapped = pipeline_contract.wrap_prompt(
        "Split the build task into 2-5 smaller sub-tasks.",
        project="tomorrow", kind="build", source="test", slug="x", material=False,
    )
    assert bc.collapsible([row(wrapped)]) == []

    wrapped_real = pipeline_contract.wrap_prompt(
        "Fix the OAuth session expiry handling.",
        project="tomorrow", kind="build", source="test", slug="y", material=False,
    )
    assert len(bc.collapsible([row(wrapped_real)])) == 1


def test_collapsible_preserves_order_and_does_not_mutate():
    rows = [row("real one", "a"), row("", "b"), row("real two", "c")]
    before = [dict(r) for r in rows]
    out = bc.collapsible(rows)
    assert [r["slug"] for r in out] == ["a", "c"]
    assert rows == before


def test_an_all_bookkeeping_group_collapses_to_nothing():
    # The load-bearing case: a group made entirely of planner artifacts must not
    # be able to reach the minimum group size and mint a batch with nothing to do.
    rows = [row("Split the build task into smaller sub-tasks", f"m{i}") for i in range(20)]
    assert bc.collapsible(rows) == []
