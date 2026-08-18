"""Acceptance tests for runner/release_closure.py.

The contract the task states, in its own words:

  * a fixture improvement is traceable from queue row to exact production SHA and both
    public/authenticated assertions
  * negative fixtures create ONE deduplicated release-fix task and never report completion

So the five required negative cases each get a test, plus the dedupe property and the
secret-redaction requirement (evidence is stored and read by humans; an authenticated
page's text is exactly where a session token ends up).
"""
import os
import sys
import time

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_RUNNER = os.path.join(os.path.dirname(_HERE), "runner")
sys.path.insert(0, _RUNNER)

import release_closure as rc  # noqa: E402


NOW = 1_786_500_000.0
MERGE = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0"


@pytest.fixture(autouse=True)
def _clean_ledger():
    rc.clear_fix_ledger()
    yield
    rc.clear_fix_ledger()


def _assertions(public_ok=True, authed_ok=True):
    return [
        rc.route_assertion("/", "public", public_ok,
                           before="Old headline", after="New headline",
                           status=200, evidence_url="https://example.test/run/1"),
        rc.route_assertion("/app/dashboard", "authed", authed_ok,
                           before="0 items", after="3 items",
                           status=200, evidence_url="https://example.test/run/2"),
    ]


def _evidence(**over):
    base = {
        "task_id": "t-1",
        "slug": "improve-landing-copy",
        "project": "beethoven",
        "branch": "agent/improve-landing-copy",
        "merge_commit": MERGE,
        "merged_at": NOW - 600,
        "release_id": "rel-2026-08-12-01",
        "deployed_sha": MERGE,
        "deployed_at": NOW - 300,
        "assertions": _assertions(),
    }
    base.update(over)
    return base


# ─── 1. Successful closure ──────────────────────────────────────────────────

def test_successful_closure_is_traceable_end_to_end():
    c = rc.evaluate_closure(_evidence(), now=NOW)
    assert c["closed"] is True
    assert c["missing"] == []
    assert c["failures"] == []
    assert c["stage"] == "authed_route_asserted"
    assert list(c["stages_reached"]) == list(rc.STAGES)
    ok, reason = rc.report_completion(c)
    assert ok is True and "seven stages" in reason


def test_closure_statement_names_the_commit_and_the_deployment():
    c = rc.evaluate_closure(_evidence(), now=NOW)
    assert "CLOSED" in c["statement"]
    assert MERGE[:12] in c["statement"]
    assert "rel-2026-08-12-01" in c["statement"]


def test_a_closed_task_opens_no_release_fix():
    c = rc.evaluate_closure(_evidence(), now=NOW)
    result = rc.open_release_fix(c)
    assert result["created"] is False
    assert "nothing to fix" in result["reason"]


# ─── 2. MERGED alone is not DONE ────────────────────────────────────────────

def test_merged_only_is_not_reported_complete():
    c = rc.evaluate_closure(
        _evidence(release_id=None, deployed_sha=None, deployed_at=None, assertions=[]),
        now=NOW,
    )
    assert c["closed"] is False
    assert c["stage"] == "merge_commit"
    ok, reason = rc.report_completion(c)
    assert ok is False
    assert "MERGED is not DONE" in reason


def test_stage_is_contiguous_so_an_incoherent_task_is_not_nearly_done():
    # Assertions present but no merge commit: reporting the furthest stage would
    # flatter a task that never landed any code.
    c = rc.evaluate_closure(_evidence(merge_commit=None, deployed_sha=None), now=NOW)
    assert c["stage"] == "branch"
    assert c["closed"] is False


# ─── 3. Stale merge ─────────────────────────────────────────────────────────

def test_stale_merge_past_the_slo_is_a_failure():
    c = rc.evaluate_closure(
        _evidence(release_id=None, deployed_sha=None, deployed_at=None, assertions=[],
                  merged_at=NOW - (rc.deploy_slo_minutes() + 30) * 60),
        now=NOW,
    )
    kinds = {f["kind"] for f in c["failures"]}
    assert "stale_merge" in kinds
    assert rc.report_completion(c)[0] is False


def test_a_fresh_merge_inside_the_slo_is_not_yet_a_failure():
    c = rc.evaluate_closure(
        _evidence(release_id=None, deployed_sha=None, deployed_at=None, assertions=[],
                  merged_at=NOW - 60),
        now=NOW,
    )
    assert c["closed"] is False
    assert {f["kind"] for f in c["failures"]} == set()
    # …and therefore opens no fix task: alerting inside the SLO is how a channel is muted.
    assert rc.open_release_fix(c)["created"] is False


# ─── 4. Wrong deployed SHA ──────────────────────────────────────────────────

def test_wrong_deployed_sha_is_detected():
    c = rc.evaluate_closure(_evidence(deployed_sha="ffffffffffffffffffffffffffffffffffffffff"), now=NOW)
    kinds = {f["kind"] for f in c["failures"]}
    assert "wrong_deployed_sha" in kinds
    assert "deployed_sha" not in c["stages_reached"]
    assert c["closed"] is False


def test_a_deployment_containing_the_merge_counts_even_when_the_shas_differ():
    # The normal production case: the deployment SHA is a later merge that CONTAINS ours.
    c = rc.evaluate_closure(
        _evidence(deployed_sha="9999999999999999999999999999999999999999",
                  deployed_contains=[MERGE, "0000000000000000000000000000000000000000"]),
        now=NOW,
    )
    assert "deployed_sha" in c["stages_reached"]
    assert c["closed"] is True


def test_a_plausible_but_unrelated_deployment_does_not_count():
    c = rc.evaluate_closure(
        _evidence(deployed_sha="9999999999999999999999999999999999999999",
                  deployed_contains=["0000000000000000000000000000000000000000"]),
        now=NOW,
    )
    assert {f["kind"] for f in c["failures"]} == {"wrong_deployed_sha"}


# ─── 5. Failed public assertion ─────────────────────────────────────────────

def test_failed_public_assertion_blocks_closure():
    c = rc.evaluate_closure(_evidence(assertions=_assertions(public_ok=False)), now=NOW)
    kinds = {f["kind"] for f in c["failures"]}
    assert "failed_public_assertion" in kinds
    assert "public_route_asserted" not in c["stages_reached"]
    assert rc.report_completion(c)[0] is False


def test_a_never_attempted_public_assertion_past_slo_is_also_a_failure():
    # Silence is not success. A deployment that nobody ever checked must not close.
    c = rc.evaluate_closure(
        _evidence(assertions=[], deployed_at=NOW - (rc.assertion_slo_minutes() + 10) * 60),
        now=NOW,
    )
    kinds = {f["kind"] for f in c["failures"]}
    assert "failed_public_assertion" in kinds
    assert "failed_authenticated_assertion" in kinds
    assert "NO public route assertion attempted" in " ".join(f["detail"] for f in c["failures"])


# ─── 6. Failed authenticated assertion ──────────────────────────────────────

def test_failed_authenticated_assertion_blocks_closure():
    c = rc.evaluate_closure(_evidence(assertions=_assertions(authed_ok=False)), now=NOW)
    kinds = {f["kind"] for f in c["failures"]}
    assert "failed_authenticated_assertion" in kinds
    assert "public_route_asserted" in c["stages_reached"]
    assert c["closed"] is False


def test_public_passing_does_not_certify_the_authenticated_page():
    # The reported symptom: a landing page updates while the logged-in app does not.
    c = rc.evaluate_closure(
        _evidence(assertions=[rc.route_assertion("/", "public", True, after="New headline")]),
        now=NOW,
    )
    assert "public_route_asserted" in c["stages_reached"]
    assert "authed_route_asserted" not in c["stages_reached"]
    assert c["closed"] is False


# ─── 7. One deduplicated release-fix task ───────────────────────────────────

def test_a_negative_fixture_opens_exactly_one_release_fix_task():
    c = rc.evaluate_closure(_evidence(assertions=_assertions(public_ok=False)), now=NOW)
    first = rc.open_release_fix(c)
    second = rc.open_release_fix(c)
    assert first["created"] is True
    assert second["created"] is False
    assert second["slug"] == first["slug"]
    assert rc.open_fix_slugs() == [first["slug"]]


def test_the_same_failure_signature_dedupes_across_polls():
    c1 = rc.evaluate_closure(_evidence(assertions=_assertions(public_ok=False)), now=NOW)
    c2 = rc.evaluate_closure(_evidence(assertions=_assertions(public_ok=False)), now=NOW + 3600)
    assert rc.release_fix_slug(c1) == rc.release_fix_slug(c2)


def test_a_different_failure_signature_gets_its_own_task():
    public = rc.evaluate_closure(_evidence(assertions=_assertions(public_ok=False)), now=NOW)
    sha = rc.evaluate_closure(_evidence(deployed_sha="f" * 40), now=NOW)
    assert rc.release_fix_slug(public) != rc.release_fix_slug(sha)


def test_an_externally_known_open_fix_suppresses_creation():
    c = rc.evaluate_closure(_evidence(assertions=_assertions(public_ok=False)), now=NOW)
    slug = rc.release_fix_slug(c)
    result = rc.open_release_fix(c, known=[slug])
    assert result["created"] is False
    assert "already open" in result["reason"]


def test_the_fix_prompt_scopes_the_work_and_forbids_reimplementation():
    c = rc.evaluate_closure(_evidence(deployed_sha="f" * 40), now=NOW)
    task = rc.open_release_fix(c)["task"]
    assert task["kind"] == "relfix"
    assert task["parent_slug"] == "improve-landing-copy"
    assert "Do not re-implement the original change" in task["prompt"]
    assert "MERGED alone is not done" in task["prompt"]
    assert "production is serving a SHA that does not contain the merge" in task["prompt"]


# ─── 8. Evidence carries no secrets ─────────────────────────────────────────

@pytest.mark.parametrize("secret", [
    "ghp_abcdefghijklmnopqrstuvwxyz0123",
    "sk-abcdefghijklmnopqrstuvwxyz",
    "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dBjftJeZ4CVPmB92K27uhbUJU1p1r_wW1gFWFOEjXk",
    "Authorization: Bearer supersecretvalue",
    "password=hunter2hunter2",
    "user@example.com",
])
def test_redaction_strips_credentials_from_assertion_text(secret):
    a = rc.route_assertion("/app", "authed", True, before="clean", after="page shows %s" % secret)
    assert secret not in a["after"]
    assert rc.REDACTED in a["after"]


def test_redaction_strips_credentials_from_urls():
    a = rc.route_assertion("/app", "authed", True, evidence_url="https://x.test/run?token=abc123def456")
    assert "abc123def456" not in a["evidence_url"]


def test_evidence_links_are_redacted_on_the_closure():
    c = rc.evaluate_closure(
        _evidence(deployment_url="https://vercel.test/d/1?access_token=zzzzzzzzzzzz"),
        now=NOW,
    )
    assert all("zzzzzzzzzzzz" not in link for link in c["evidence_links"])


def test_the_assertion_record_has_nowhere_to_put_a_screenshot():
    a = rc.route_assertion("/", "public", True)
    assert "screenshot" not in a
    assert "image" not in a


# ─── 9. Fail-soft ───────────────────────────────────────────────────────────

def test_evaluate_closure_never_raises_on_garbage():
    for bad in (None, {}, {"assertions": "not-a-list"}, {"merged_at": "not-a-number"}):
        c = rc.evaluate_closure(bad, now=NOW)
        assert c["closed"] is False
        assert isinstance(c["missing"], list)


def test_report_completion_defaults_to_refusing():
    ok, reason = rc.report_completion(None)
    assert ok is False and reason


def test_redact_returns_empty_string_rather_than_raising():
    assert rc.redact(None) == ""
    assert rc.redact_all(None) == []


def test_thresholds_are_orch_prefixed_env_vars(monkeypatch):
    monkeypatch.setenv("ORCH_RELEASE_DEPLOY_SLO_MIN", "5")
    assert rc.deploy_slo_minutes() == 5
    monkeypatch.setenv("ORCH_RELEASE_DEPLOY_SLO_MIN", "not-a-number")
    assert rc.deploy_slo_minutes() == 90  # fail-soft back to the default
