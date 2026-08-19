"""Owner directive #36: self-improvement fills IDLE capacity. It never jumps user work.

Two mechanisms were supposed to enforce that. Neither reached.

1. ev_scheduler._self_improve_tier tiers by project and returns 1 for the orchestrator's
   own project. But it only feeds claim_task's `_ev_rank` -- the TWENTY-FIRST sort key.
   `_portfolio_project_rank` is the ELEVENTH, and PROJECT_PRIORITY_ORDER puts the
   orchestrator's own project at rank 4: ahead of madeus(5), vigil(6), smarter(7),
   illuminati(8) and pareto(9). The sort was decided ten keys before the tier was
   consulted, so a swarm bot's remediation task beat user-directed work in five products.

2. ORCH_SELF_WORK_MAX_SHARE caps self-maintenance at 35% of running lanes -- but only for
   slugs matching SELF_MAINTENANCE_PREFIXES, which contained "remediate-" and not
   "remediation-". Every swarm bot files "remediation-*" (conflict_marker_sentinel:
   remediation-conflict-markers-*, canary_triage: remediation-canary-*). One missing
   suffix exempted the entire class from the cap.

These tests pin both, and pin the two things the fix must NOT break: orchestrator PRODUCT
work keeps rank 4, and remediation filed against a product repo stays product work.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import db  # noqa: E402


# --- the prefix gap ---------------------------------------------------------------------

@pytest.mark.parametrize("slug", [
    "remediation-conflict-markers-on-master",     # conflict_marker_sentinel
    "remediation-conflict-markers-in-worktree",   # conflict_marker_sentinel
    "remediation-canary-import-error-a1b2c3d4",   # canary_triage
])
def test_every_slug_a_swarm_bot_actually_files_is_self_maintenance(slug):
    assert db._is_self_maintenance({"slug": slug}), (
        f"{slug!r} escapes ORCH_SELF_WORK_MAX_SHARE entirely — it competes with product "
        f"work for every lane")


def test_the_prefix_that_was_there_did_not_match_what_the_bots_emit():
    """Guards the premise: 'remediate-' alone never matched a real swarm slug."""
    assert not "remediation-conflict-markers-on-master".startswith("remediate-")


def test_product_slugs_are_not_swept_into_self_maintenance():
    """The cap diverts lanes away from these; a false positive starves real work."""
    for slug in ("add-checkout-flow", "fix-login-redirect", "remediate"):
        assert not db._is_self_maintenance({"slug": slug}), slug


# --- the project-rank inheritance -------------------------------------------------------

def _rank(monkeypatch, slug, project, demoted=True):
    """Call the real ranking function -- the one claim_task's closure delegates to.

    Deliberately NOT a reimplementation of the rule: a test that recomputes the logic it is
    checking passes even when the shipped code is deleted.
    """
    if demoted:
        monkeypatch.delenv("ORCH_SELF_WORK_INHERITS_PROJECT_RANK", raising=False)
    else:
        monkeypatch.setenv("ORCH_SELF_WORK_INHERITS_PROJECT_RANK", "1")
    return db.portfolio_rank(project, {"slug": slug})


def test_the_orchestrators_own_rank_is_genuinely_ahead_of_real_products():
    """The premise. If this stops being true the demotion is pointless, not merely safe."""
    own = db._project_rank_name("beethoven")
    for product in ("madeus", "vigil", "smarter", "illuminati", "pareto"):
        assert own < db._project_rank_name(product), \
            f"beethoven({own}) no longer outranks {product}"


@pytest.mark.parametrize("product", ["madeus", "vigil", "smarter", "illuminati", "pareto",
                                     "hisanta", "galop", "sustainable-barks"])
def test_swarm_work_now_sorts_below_every_named_product(monkeypatch, product):
    self_work = _rank(monkeypatch, "remediation-conflict-markers-on-master", "beethoven")
    assert self_work > db._project_rank_name(product), \
        f"swarm remediation still outranks user work in {product}"


def test_it_also_sorts_below_an_unlisted_project(monkeypatch):
    """prediction-markets-institute has no PROJECT_PRIORITY_ORDER entry and lands on the
    rank-13 default -- and it is one of the four apps the owner names as a priority. A
    demotion TO 13 would tie with it, and ties fall through to later keys where self-work
    can still win. It has to be strictly below."""
    self_work = _rank(monkeypatch, "remediation-canary-import-error", "beethoven")
    assert self_work > db._project_rank_name("prediction-markets-institute")


def test_orchestrator_product_work_keeps_its_rank(monkeypatch):
    """The demotion is for self-maintenance, not for the orchestrator as a product."""
    assert _rank(monkeypatch, "add-fleet-health-dashboard", "beethoven") == \
        db._project_rank_name("beethoven")


def test_remediation_against_a_product_repo_stays_product_work(monkeypatch):
    """Fixing conflict markers in the tomorrow repo IS work on tomorrow."""
    assert _rank(monkeypatch, "remediation-conflict-markers-on-master", "tomorrow") == \
        db._project_rank_name("tomorrow")


def test_the_orchestrator_alias_is_covered_too(monkeypatch):
    """PROJECT_PRIORITY_ORDER lists both names at rank 4; missing one leaves a way through."""
    assert _rank(monkeypatch, "remediation-canary-x", "orchestrator") == db.SELF_WORK_PROJECT_RANK


def test_the_old_behaviour_is_recoverable(monkeypatch):
    """A ranking change to a 24-key sort needs an off switch that does not need a deploy."""
    assert _rank(monkeypatch, "remediation-canary-x", "beethoven", demoted=False) == \
        db._project_rank_name("beethoven")


# --- the claim sort still consults it ---------------------------------------------------

def test_portfolio_rank_is_still_wired_into_the_claim_sort():
    """The demotion is worthless if the key is ever dropped from the sort tuple."""
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "db.py")).read()
    assert "_portfolio_project_rank(t)," in src, \
        "the project key is no longer part of claim_task's sort tuple"
    assert "portfolio_rank(project_names.get" in src, \
        "the closure no longer delegates to the function these tests exercise"


def test_swarm_enqueue_no_longer_claims_the_tier_it_never_had():
    """The docstring asserted _self_improve_tier enforced the ordering. It did not.

    A wrong comment is how this survived review: it named a mechanism that exists, in a
    file where it does not apply.
    """
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "swarm_enqueue.py")
    src = open(path).read()
    head = src.split('"""', 2)[1]
    assert "SELF_WORK_PROJECT_RANK" in head, \
        "swarm_enqueue must document what actually holds it below user work"
