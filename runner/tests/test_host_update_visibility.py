"""A host that cannot update itself must say so — proven, not asserted.

Each test maps to one clause of the 2026-08-06 defect: a host pinned at code_sha
10d9e408 for two days, heartbeating normally, with ZERO rows anywhere explaining why
its pull failed, that was then RESUMED from a pause on the basis of an attempted pull.
"""
import os
import sys
import datetime
import types

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import host_update_visibility as huv


class FakeDB:
    """Minimal runner_alerts stand-in: records inserts, supports the ilike dedupe query."""

    def __init__(self):
        self.rows = []
        self._next_id = 1

    def insert(self, table, row):
        assert table == "runner_alerts"
        stored = dict(row)
        stored["id"] = self._next_id
        self._next_id += 1
        self.rows.append(stored)
        return stored

    def select(self, table, params):
        assert table == "runner_alerts"
        out = []
        want_kind = (params.get("kind") or "").removeprefix("eq.")
        want_resolved = params.get("resolved")
        pattern = (params.get("detail") or "").removeprefix("ilike.")
        needles = [p for p in pattern.split("*") if p]
        for row in self.rows:
            if want_kind and row.get("kind") != want_kind:
                continue
            if want_resolved == "eq.false" and row.get("resolved"):
                continue
            if want_resolved == "eq.true" and not row.get("resolved"):
                continue
            if needles and not all(n.lower() in (row.get("detail") or "").lower()
                                   for n in needles):
                continue
            out.append(row)
        return out

    def update(self, table, match, patch):
        assert table == "runner_alerts"
        for row in self.rows:
            if row.get("id") == match.get("id"):
                row.update(patch)

    # --- helpers used by assertions -------------------------------------------------
    def unresolved(self):
        return [r for r in self.rows if not r.get("resolved")]

    def details(self):
        return "\n".join(r.get("detail") or "" for r in self.rows)


@pytest.fixture
def fake_db(monkeypatch):
    fdb = FakeDB()
    monkeypatch.setattr(huv, "db", fdb)
    huv.reset_state()
    yield fdb
    huv.reset_state()


HOST = "Mandys-MacBook-Pro.local"


# 1. Successful pull records old->new sha.
def test_success_records_old_and_new_sha(fake_db):
    result = huv.record_success(HOST, "10d9e408aaaa", "03f59545bbbb")

    assert result["outcome"] == "success"
    assert "10d9e408->03f59545" in result["detail"]
    assert f"host={HOST}" in result["detail"]
    assert fake_db.rows, "a success must still be recorded — silence is the defect"
    assert all(r["kind"] == huv.ALERT_KIND for r in fake_db.rows)
    assert not fake_db.unresolved(), "a successful update must not leave an alarm ringing"


def test_success_resolves_the_hosts_open_failure_alert(fake_db):
    huv.record_failure(HOST, "fatal: could not read Username", escalate_after=1)
    assert fake_db.unresolved(), "precondition: an open escalation exists"

    huv.record_success(HOST, "10d9e408", "03f59545")

    assert not fake_db.unresolved()


# 2. Failed pull records verbatim stderr and does not claim success.
def test_failure_records_verbatim_stderr_and_never_claims_success(fake_db):
    stderr = ("error: Your local changes to the following files would be overwritten by "
              "merge:\n\trunner/context_cache.json\nPlease commit your changes or stash "
              "them before you merge.\naborting")

    result = huv.record_failure(HOST, stderr, current_sha="10d9e408aaaa", behind=40)

    assert result["outcome"] == "failure"
    assert result["outcome"] != "success"
    assert stderr in result["stderr"], "stderr must be VERBATIM, not summarized"
    assert "commits_behind=40" in result["detail"]
    assert "sha=10d9e408" in result["detail"]
    assert "outcome=failure" in fake_db.details()
    assert "outcome=success" not in fake_db.details()


def test_failure_truncates_absurd_stderr_but_keeps_the_head(fake_db, monkeypatch):
    monkeypatch.setenv("ORCH_HOST_UPDATE_STDERR_MAX", "80")
    stderr = "fatal: authentication failed " + ("x" * 5000)

    result = huv.record_failure(HOST, stderr)

    assert len(result["stderr"]) < 200
    assert result["stderr"].startswith("fatal: authentication failed")
    assert "truncated" in result["stderr"]


def test_failure_records_unknown_when_commits_behind_is_unknowable(fake_db):
    result = huv.record_failure(HOST, "fatal: whatever", behind=None)

    assert "commits_behind=unknown" in result["detail"]


# 3. ORCH_AUTO_PULL disabled emits the explicit once-per-day notice.
def test_auto_pull_disabled_emits_explicit_notice_once_per_day(fake_db):
    day = datetime.date(2026, 8, 6)

    first = huv.record_auto_pull_disabled(HOST, behind=40, today=day)
    second = huv.record_auto_pull_disabled(HOST, behind=41, today=day)

    assert first["emitted"] is True
    assert second["emitted"] is False, "must be at most once per host per day"
    assert len(fake_db.rows) == 1
    assert "auto-pull-disabled" in fake_db.rows[0]["detail"]
    assert "ORCH_AUTO_PULL" in fake_db.rows[0]["detail"]


def test_auto_pull_disabled_notice_repeats_the_next_day(fake_db):
    huv.record_auto_pull_disabled(HOST, today=datetime.date(2026, 8, 6))
    again = huv.record_auto_pull_disabled(HOST, today=datetime.date(2026, 8, 7))

    assert again["emitted"] is True
    assert len(fake_db.rows) == 2


def test_auto_pull_disabled_is_distinguishable_from_just_updated(fake_db):
    """The whole point: 'never going to update' must not look like 'just updated'."""
    huv.record_auto_pull_disabled(HOST, today=datetime.date(2026, 8, 6))
    disabled_detail = fake_db.rows[-1]["detail"]
    huv.record_success("OtherHost.local", "aaaaaaaa", "bbbbbbbb")
    success_detail = fake_db.rows[-1]["detail"]

    assert "outcome=disabled" in disabled_detail
    assert "outcome=success" in success_detail
    assert disabled_detail != success_detail


# 4. N consecutive failures escalate to an unresolved runner_alerts row, deduped.
def test_consecutive_failures_escalate_once_and_dedupe(fake_db):
    for _ in range(3):
        huv.record_failure(HOST, "fatal: Not logged in", escalate_after=3)

    unresolved = fake_db.unresolved()
    assert len(unresolved) == 1, "escalation must be deduped, not repeated every cycle"
    assert "ESCALATED" in unresolved[0]["detail"]
    assert "consecutive=3" in unresolved[0]["detail"]

    for _ in range(5):
        huv.record_failure(HOST, "fatal: Not logged in", escalate_after=3)

    assert len(fake_db.unresolved()) == 1


def test_below_threshold_does_not_escalate(fake_db):
    result = huv.record_failure(HOST, "fatal: Not logged in", escalate_after=3)

    assert result["escalated"] is False
    assert fake_db.unresolved() == []
    assert fake_db.rows, "still recorded, just not escalated"


def test_success_clears_the_streak(fake_db):
    huv.record_failure(HOST, "fatal: boom", escalate_after=3)
    huv.record_failure(HOST, "fatal: boom", escalate_after=3)
    huv.record_success(HOST, "aaaaaaaa", "bbbbbbbb")
    result = huv.record_failure(HOST, "fatal: boom", escalate_after=3)

    assert result["consecutive"] == 1


def test_escalation_threshold_is_configurable_via_env(fake_db, monkeypatch):
    monkeypatch.setenv("ORCH_HOST_UPDATE_ESCALATE_AFTER", "1")

    result = huv.record_failure(HOST, "fatal: boom")

    assert result["consecutive"] == 1
    assert result["escalated"] is True
    assert len(fake_db.unresolved()) == 1


# 5. Resume-after-verify: a host whose sha still differs from origin is NOT resumed.
def test_resume_refused_when_sha_still_stale():
    allowed, reason = huv.resume_allowed("10d9e408aaaa", "03f59545bbbb")

    assert allowed is False
    assert "stale" in reason
    assert "10d9e408" in reason and "03f59545" in reason


def test_resume_allowed_only_when_sha_matches_origin():
    allowed, reason = huv.resume_allowed("03f59545bbbb", "03f59545bbbb")

    assert allowed is True
    assert "verified" in reason


@pytest.mark.parametrize("local,origin", [
    (None, "03f59545"), ("10d9e408", None), (None, None), ("", ""),
])
def test_resume_refused_when_verification_is_impossible(local, origin):
    """An unverifiable resume is the exact cowork-pull-attempt failure. Fail closed."""
    allowed, reason = huv.resume_allowed(local, origin)

    assert allowed is False
    assert "cannot verify" in reason


# 6. commits_behind is present and correct in the heartbeat payload.
def test_commits_behind_reads_rev_list_count(monkeypatch):
    calls = []

    def fake_git(repo, *args, timeout=30):
        calls.append(args)
        return types.SimpleNamespace(returncode=0, stdout="40\n", stderr="")

    monkeypatch.setattr(huv, "_git", fake_git)

    assert huv.commits_behind(repo="/tmp/repo", default_branch="master") == 40
    assert ("rev-list", "--count", "HEAD..origin/master") in calls


def test_commits_behind_is_none_when_git_fails(monkeypatch):
    monkeypatch.setattr(huv, "_git", lambda *a, **k: types.SimpleNamespace(
        returncode=128, stdout="", stderr="fatal: bad revision"))

    assert huv.commits_behind(repo="/tmp/repo") is None


def test_heartbeat_fields_carries_commits_behind(monkeypatch):
    monkeypatch.setattr(huv, "commits_behind", lambda **kw: 40)

    assert huv.heartbeat_fields() == {"commits_behind": 40}


def test_heartbeat_fields_omits_unknown_rather_than_lying(monkeypatch):
    """Omitted, not zero. commits_behind=0 means 'current'; it must not mean 'no idea'."""
    monkeypatch.setattr(huv, "commits_behind", lambda **kw: None)

    assert huv.heartbeat_fields() == {}


def test_heartbeat_fields_reports_zero_for_a_current_host(monkeypatch):
    monkeypatch.setattr(huv, "commits_behind", lambda **kw: 0)

    assert huv.heartbeat_fields() == {"commits_behind": 0}


# 7. A trust-dialog stderr is classified as trust-dialog, not as a generic git error.
def test_trust_dialog_is_named_not_generic():
    stderr = ("Error: this workspace has not been trusted. Please open Claude Code "
              "and accept the trust prompt for /Users/mandypasch/Documents/apparently")

    code, explanation = huv.classify_pull_failure(stderr)

    assert code == "trust-dialog"
    assert code != "git-error"
    assert "keyboard" in explanation.lower(), "must say a human is required on the host"


@pytest.mark.parametrize("stderr,expected", [
    ("Not logged in · Please run /login", "not-logged-in"),
    ("fatal: could not read Username for 'https://github.com'", "not-logged-in"),
    ("error: Your local changes to the following files would be overwritten by merge",
     "dirty-checkout"),
    ("fatal: Not possible to fast-forward, aborting.", "diverged"),
    ("fatal: unable to access 'https://github.com/': Could not resolve host: github.com",
     "network"),
    ("error: pathspec 'weird' did not match anything", "git-error"),
])
def test_each_known_cause_is_named(stderr, expected):
    code, explanation = huv.classify_pull_failure(stderr)

    assert code == expected
    assert explanation, "every diagnosis must carry an actionable explanation"


def test_empty_stderr_is_unknown_not_a_false_diagnosis():
    code, explanation = huv.classify_pull_failure("")

    assert code == "unknown"
    assert "manually" in explanation


def test_named_diagnosis_reaches_the_recorded_alert(fake_db):
    huv.record_failure(HOST, "this workspace has not been trusted", escalate_after=1)

    detail = fake_db.unresolved()[0]["detail"]
    assert "diagnosis=trust-dialog" in detail
    assert "cause:" in detail


def test_disabled_diagnosis_names_the_env_var():
    code, explanation = huv.classify_disabled()

    assert code == "auto-pull-disabled"
    assert "ORCH_AUTO_PULL" in explanation


# --- fail-soft: observability must never wedge the runner ---------------------------
def test_recording_survives_a_dead_database(monkeypatch):
    class DeadDB:
        def insert(self, *a, **k):
            raise RuntimeError("supabase unreachable")

        def select(self, *a, **k):
            raise RuntimeError("supabase unreachable")

        def update(self, *a, **k):
            raise RuntimeError("supabase unreachable")

    monkeypatch.setattr(huv, "db", DeadDB())
    huv.reset_state()

    assert huv.record_failure(HOST, "fatal: boom")["outcome"] == "failure"
    assert huv.record_success(HOST, "a" * 8, "b" * 8)["outcome"] == "success"
    assert huv.record_auto_pull_disabled(HOST)["emitted"] is True
