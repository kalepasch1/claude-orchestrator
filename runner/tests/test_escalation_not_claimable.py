"""
An escalation must be invisible to the dispatcher and visible to a person.

WHAT WENT WRONG
---------------
Rows whose slug starts with `escalate-` or `human-decision-` are questions for an
operator: their content is a question, their state is the question's status, and
no coder can resolve them.

agentic_repair grew an is_operator_decision() guard for exactly this reason,
after the standing Guardrail-8 escalation was pulled into the repair pipeline,
reached attempt=4, and had its note rewritten to "Continue the same
implementation to completion" — over the text a human was supposed to read.

But that guard only covered REPAIR. db.claim_task() selected
`state in (QUEUED, TESTING)` with no exclusion at all, so an agent could still
CLAIM an escalation and hand it to a coder. And _awaiting_operator_patch() puts
the row back in QUEUED, the same state as the 2,260 mechanical tasks it is
queued behind.

The alarm was inside the fire.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import db  # noqa: E402


def test_escalation_slugs_are_recognised():
    assert db.is_operator_decision_slug("escalate-p1-queue-clearance-no-improvement-20260810-nk73")
    assert db.is_operator_decision_slug("human-decision-approvals-decided-at-null-20260820-ad91")


def test_ordinary_work_is_not_mistaken_for_an_escalation():
    """The filter must not swallow real work — that would stall the fleet."""
    for slug in (
        "copyfix-beethoven-07180848-slice-3-public-landing-hero-control-copy",
        "improve-missing-branch-auto-creator-slice-3-finalize-build-and-config",
        "relfix-v15-smarter-c7599db3",
        "canary-codex-39",
        # near-misses that must still be claimable
        "escalation-policy-refactor",
        "humanize-copy-tone",
    ):
        assert not db.is_operator_decision_slug(slug), slug


def test_empty_and_missing_slugs_are_safe():
    assert not db.is_operator_decision_slug(None)
    assert not db.is_operator_decision_slug("")


def test_both_modules_agree_on_the_prefixes():
    """Two chokepoints, one definition of what an escalation is.

    agentic_repair guards repair; db guards claim. If they ever disagree, a row
    is protected at one stage and consumed at the other — which is the state
    this test exists to prevent recurring.
    """
    import agentic_repair
    assert set(db.OPERATOR_DECISION_SLUG_PREFIXES) == set(
        agentic_repair.OPERATOR_DECISION_PREFIXES
    ), "the claim guard and the repair guard must recognise the same rows"
