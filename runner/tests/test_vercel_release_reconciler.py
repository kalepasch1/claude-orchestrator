"""The releases table was blind to every deploy the orchestrator did not cut itself.

Measured 2026-08-23: smarter had 70 releases, all deploy_status=failed, none since
2026-07-15 — while Vercel had production deployments READY throughout, the newest
90 minutes old, serving apparently.cc. canonical_proof_ledger asks for a release
naming a task's artifact commit; there were none, so every MERGED smarter task
stopped at LEVEL_MERGED.

The second half is the URL: every row the orchestrator DID write stores the
*.vercel.app deployment URL, and deployment protection is
`all_except_custom_domains`, so all of them 302 to an SSO login for an anonymous
caller — including the fleet's own journey runner.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import vercel_release_reconciler as rec


def _dep(sha, dep_id="dpl_x", created=1_787_501_962_246, state="READY",
         target="production", url="smarter-abc-kalepasch1s-projects.vercel.app"):
    return {"id": dep_id, "url": url, "created": created, "state": state,
            "target": target, "meta": {"githubCommitSha": sha}}


# ------------------------------------------------------------- URL selection

def test_custom_domain_beats_the_sso_gated_deployment_url():
    url, gated, _ = rec.public_production_url(
        [{"name": "apparently.cc", "verified": True}],
        "smarter-bij5tbxvp-kalepasch1s-projects.vercel.app")
    assert url == "https://apparently.cc"
    assert gated is False


def test_apex_beats_www():
    url, _, _ = rec.public_production_url(
        [{"name": "www.apparently.cc"}, {"name": "apparently.cc"}], "")
    assert url == "https://apparently.cc"


def test_redirect_only_domains_are_not_where_the_app_is_served():
    url, gated, _ = rec.public_production_url(
        [{"name": "smrter.us", "redirect": "apparently.cc"},
         {"name": "apparently.cc"}], "")
    assert url == "https://apparently.cc"
    assert gated is False


def test_an_unverified_domain_is_skipped_but_an_unknown_one_is_not():
    url, _, _ = rec.public_production_url(
        [{"name": "not-yet.example", "verified": False},
         {"name": "apparently.cc", "verified": True}], "")
    assert url == "https://apparently.cc"
    # `verified` absent means the payload did not say, which is not a refusal.
    url2, gated2, _ = rec.public_production_url([{"name": "apparently.cc"}], "")
    assert url2 == "https://apparently.cc" and gated2 is False


def test_only_a_vercel_app_url_is_reported_as_gated_with_a_reason():
    url, gated, reason = rec.public_production_url(
        [], "smarter-bij5tbxvp-kalepasch1s-projects.vercel.app")
    assert gated is True
    assert url.endswith(".vercel.app")
    assert "SSO" in reason and "anonymously" in reason


def test_a_vercel_app_domain_never_counts_as_a_public_domain():
    url, gated, _ = rec.public_production_url(
        [{"name": "smarter-git-main-kalepasch1s-projects.vercel.app", "verified": True}],
        "smarter-abc.vercel.app")
    assert gated is True, "a *.vercel.app project domain is gated too"


def test_nothing_at_all_is_gated_and_empty():
    url, gated, reason = rec.public_production_url([], "")
    assert (url, gated) == ("", True)
    assert reason


# ----------------------------------------------------------- what is a release

def test_a_ready_preview_is_not_a_release():
    assert rec.is_live_production(_dep("a" * 40, target=None)) is False
    assert rec.is_live_production(_dep("a" * 40, target="production")) is True


def test_a_building_production_deploy_is_not_a_release():
    assert rec.is_live_production(_dep("a" * 40, state="BUILDING")) is False
    assert rec.is_live_production(_dep("a" * 40, state="ERROR")) is False


def test_missing_releases_skips_shas_already_recorded():
    deps = [_dep("aa" * 20, "dpl_1"), _dep("bb" * 20, "dpl_2")]
    out = rec.missing_releases(deps, {"aa" * 20})
    assert [d["id"] for d in out] == ["dpl_2"]


def test_a_redeploy_of_the_same_commit_is_one_release():
    deps = [_dep("aa" * 20, "dpl_1", created=1), _dep("aa" * 20, "dpl_2", created=2)]
    assert len(rec.missing_releases(deps, set())) == 1


def test_a_deployment_with_no_commit_sha_is_skipped():
    dep = _dep("x", "dpl_1")
    dep["meta"] = {}
    assert rec.missing_releases([dep], set()) == []


def test_missing_releases_are_returned_oldest_first():
    deps = [_dep("bb" * 20, "dpl_new", created=200), _dep("aa" * 20, "dpl_old", created=100)]
    assert [d["id"] for d in rec.missing_releases(deps, set())] == ["dpl_old", "dpl_new"]


# ------------------------------------------------------------------- the row

def test_the_row_records_the_public_domain_not_the_deployment_url():
    row = rec.release_row("smarter", _dep("cc" * 20), "https://apparently.cc", False, "")
    assert row["vercel_url"] == "apparently.cc"
    assert row["deploy_status"] == "success"
    assert row["to_sha"] == "cc" * 20
    assert "reconciled from Vercel" in row["note"]
    assert "WARNING" not in row["note"]


def test_a_gated_url_is_written_with_the_warning_attached():
    row = rec.release_row("smarter", _dep("cc" * 20),
                          "https://smarter-abc.vercel.app", True, "SSO-gated")
    assert "WARNING" in row["note"] and "SSO-gated" in row["note"]


def test_created_at_comes_from_vercel_not_from_now():
    row = rec.release_row("smarter", _dep("cc" * 20, created=1_787_501_962_246),
                          "https://apparently.cc", False, "", now_iso="2099-01-01T00:00:00Z")
    assert row["created_at"].startswith("2026-08-23")
    assert row["deployed_at"] == row["created_at"]


# -------------------------------------------------------------- the reconcile

def _fake_vget(deployments, domains):
    def vget(path):
        if "/deployments" in path:
            return {"deployments": deployments}
        if "/domains" in path:
            return {"domains": domains}
        return {}
    return vget


def test_reconcile_adds_only_what_is_missing():
    written = []
    deps = [_dep("aa" * 20, "dpl_1", created=1), _dep("bb" * 20, "dpl_2", created=2)]
    out = rec.reconcile_project(
        "smarter", "smarter",
        select_fn=lambda t, p: [{"to_sha": "aa" * 20, "deploy_status": "success"}],
        insert_fn=lambda t, row: written.append(row),
        vget=_fake_vget(deps, [{"name": "apparently.cc", "verified": True}]))
    assert out["added"] == 1 and out["error"] is None
    assert written[0]["to_sha"] == "bb" * 20
    assert written[0]["vercel_url"] == "apparently.cc"


def test_a_failed_row_for_the_same_sha_does_not_count_as_recorded():
    """The whole defect: smarter had 70 rows for shas that DID deploy, all failed."""
    written = []
    out = rec.reconcile_project(
        "smarter", "smarter",
        select_fn=lambda t, p: [{"to_sha": "aa" * 20, "deploy_status": "failed"}],
        insert_fn=lambda t, row: written.append(row),
        vget=_fake_vget([_dep("aa" * 20)], [{"name": "apparently.cc"}]))
    assert out["added"] == 1, "a failed row must not suppress the successful truth"


def test_dry_run_writes_nothing_but_reports_everything():
    written = []
    out = rec.reconcile_project(
        "smarter", "smarter",
        select_fn=lambda t, p: [],
        insert_fn=lambda t, row: written.append(row),
        vget=_fake_vget([_dep("aa" * 20)], [{"name": "apparently.cc"}]),
        dry_run=True)
    assert written == []
    assert out["added"] == 1 and len(out["rows"]) == 1


def test_an_unreadable_releases_table_refuses_rather_than_duplicating():
    def boom(*a, **k):
        raise RuntimeError("postgrest down")

    written = []
    out = rec.reconcile_project(
        "smarter", "smarter", select_fn=boom,
        insert_fn=lambda t, row: written.append(row),
        vget=_fake_vget([_dep("aa" * 20)], [{"name": "apparently.cc"}]))
    assert written == []
    assert out["added"] == 0
    assert "could not read existing releases" in out["error"]


def test_auth_failure_is_reported_not_raised():
    def vget(path):
        raise rec.VercelAuthError("Vercel API auth failed (403)")

    out = rec.reconcile_project("smarter", "smarter",
                                select_fn=lambda t, p: [],
                                insert_fn=lambda t, row: None, vget=vget)
    assert out["added"] == 0
    assert "403" in out["error"]


def test_the_gated_flag_surfaces_on_the_result():
    out = rec.reconcile_project(
        "web", "web", select_fn=lambda t, p: [],
        insert_fn=lambda t, row: None,
        vget=_fake_vget([_dep("aa" * 20)], []), dry_run=True)
    assert out["gated"] is True


def test_deployment_id_reads_the_key_v6_actually_returns():
    """/v6/deployments returns `uid`; only `id` was read, so every note said None."""
    assert rec.deployment_id({"uid": "dpl_from_v6"}) == "dpl_from_v6"
    assert rec.deployment_id({"id": "dpl_from_v13"}) == "dpl_from_v13"
    assert rec.deployment_id({}) == ""
    assert rec.deployment_id(None) == ""


def test_the_note_and_version_name_the_deployment_from_a_v6_payload():
    dep = {"uid": "dpl_real", "url": "x.vercel.app", "created": 1_787_501_962_246,
           "state": "READY", "target": "production", "meta": {"githubCommitSha": "dd" * 20}}
    row = rec.release_row("smarter", dep, "https://apparently.cc", False, "")
    assert row["version"] == "dpl_real"
    assert "dpl_real" in row["note"]
    assert "None" not in row["note"]
