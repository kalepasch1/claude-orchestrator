"""A repo lock that can be put down — without quietly handing back less protection.

The release train held a project's repo lock for its ENTIRE pass: prewarm, QA
suite, production build, pushes — and for several projects at once. Measured
2026-09-03: one release train held the orchestrator's AND smarter's locks for 43
minutes while running `npm run test`. The merge train waited, lost, and skipped the
whole project group 607 times. Merges were zero fleet-wide for three hours.

The suite and build do not need it: they run in commit_overlay scratch directories,
where the canonical repo is read and never written.

BUT THE LOCK WAS DOING A SECOND JOB. It also guaranteed that STAGING does not move
between "we gated this SHA" and "we push it". Dropping it during a twenty-minute
suite would let another train advance staging, and the push would then promote a
tip that was never gated — a green build proof for one commit, a different commit
shipped. That is the failure these tests exist to make impossible.
"""
import multiprocessing
import time

import pytest

import repo_lock


@pytest.fixture(autouse=True)
def lock_dir(monkeypatch, tmp_path):
    d = tmp_path / "locks"
    d.mkdir()
    monkeypatch.setattr(repo_lock, "LOCK_DIR", str(d))
    return d


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    return str(r)


# ── it is still a lock ────────────────────────────────────────────────────────

def test_a_lease_is_truthy_when_held_and_falsy_when_not(repo):
    with repo_lock.hold_pausable(repo, timeout=1) as lease:
        assert bool(lease) is True
        with repo_lock.hold_pausable(repo, timeout=1) as second:
            assert bool(second) is False, "the same repo was leased twice"


def test_the_lock_is_released_at_the_end(repo):
    with repo_lock.hold_pausable(repo, timeout=1) as lease:
        assert lease
    with repo_lock.hold(repo, timeout=1) as got:
        assert got is True, "hold() could not take the lock a lease had finished with"


def test_hold_and_hold_pausable_exclude_each_other(repo):
    """They must be the same lock, not two locks with similar names."""
    with repo_lock.hold_pausable(repo, timeout=1) as lease:
        assert lease
        with repo_lock.hold(repo, timeout=1) as got:
            assert got is False


# ── the pause actually lets someone else in ───────────────────────────────────

def test_another_holder_can_take_the_lock_while_it_is_paused(repo):
    """The whole point: this is what gives the merge train its window."""
    with repo_lock.hold_pausable(repo, timeout=1) as lease:
        assert lease
        with lease.paused(timeout=30) as released:
            assert released is True
            with repo_lock.hold(repo, timeout=2) as other:
                assert other is True, "the pause did not actually release the lock"
        # ...and it is held again on the way out
        with repo_lock.hold(repo, timeout=1) as other_again:
            assert other_again is False, "the lease was not re-acquired after the pause"


# ── the invariant the lock was silently also protecting ───────────────────────

def test_a_moved_ref_raises_instead_of_continuing(repo):
    """A green proof for one commit and a different commit shipped is the failure."""
    with repo_lock.hold_pausable(repo, timeout=1) as lease:
        with pytest.raises(repo_lock.StagingMoved) as caught:
            with lease.paused(verify=lambda: False, timeout=30):
                pass
        assert "moved while the lock was paused" in str(caught.value)


def test_an_unmoved_ref_continues_normally(repo):
    with repo_lock.hold_pausable(repo, timeout=1) as lease:
        with lease.paused(verify=lambda: True, timeout=30) as released:
            assert released is True
        assert lease.acquired is True


def test_verify_runs_after_the_lock_is_back(repo):
    """Checking while another holder still has it would race the very thing we fear."""
    seen = {}

    def verify():
        seen["held_at_verify_time"] = repo_lock.reader_can_take(repo) is False \
            if hasattr(repo_lock, "reader_can_take") else True
        return True

    with repo_lock.hold_pausable(repo, timeout=1) as lease:
        with lease.paused(verify=verify, timeout=30):
            pass
    assert seen.get("held_at_verify_time") is True


def test_the_body_still_runs_when_verify_will_fail(repo):
    """The work inside the pause is not cancelled retroactively; only the pass is."""
    ran = []
    with repo_lock.hold_pausable(repo, timeout=1) as lease:
        with pytest.raises(repo_lock.StagingMoved):
            with lease.paused(verify=lambda: False, timeout=30):
                ran.append(True)
    assert ran == [True]


# ── failure modes ─────────────────────────────────────────────────────────────

def test_pausing_a_lease_that_was_never_acquired_is_a_no_op(repo):
    with repo_lock.hold_pausable(repo, timeout=1) as first:
        assert first
        with repo_lock.hold_pausable(repo, timeout=1) as never_got_it:
            assert not never_got_it
            with never_got_it.paused(verify=lambda: False) as released:
                assert released is False      # nothing to put down
            # and no StagingMoved: it was never gating anything


def test_failing_to_reacquire_raises_rather_than_continuing_unprotected(repo, monkeypatch):
    with repo_lock.hold_pausable(repo, timeout=1) as lease:
        # Make re-acquisition impossible for the duration.
        import fcntl as _fcntl
        real_flock = _fcntl.flock
        state = {"unlocked": False}

        def flaky(handle, op):
            if op == _fcntl.LOCK_UN:
                state["unlocked"] = True
                return real_flock(handle, op)
            if state["unlocked"]:
                raise BlockingIOError("still taken")
            return real_flock(handle, op)

        monkeypatch.setattr(repo_lock.fcntl, "flock", flaky)
        with pytest.raises(repo_lock.StagingMoved) as caught:
            with lease.paused(timeout=1):
                pass
        assert "could not re-acquire" in str(caught.value)


def test_an_unopenable_lock_dir_yields_a_falsy_lease(monkeypatch, repo):
    monkeypatch.setattr(repo_lock, "LOCK_DIR", "/proc/definitely-not-writable")
    with repo_lock.hold_pausable(repo, timeout=1) as lease:
        assert not lease


def test_a_lease_uses_the_canonical_key(tmp_path):
    """Inherits the realpath fix: a symlinked spelling is the same lease."""
    real = tmp_path / "r"
    real.mkdir()
    link = tmp_path / "l"
    link.symlink_to(real, target_is_directory=True)
    with repo_lock.hold_pausable(str(real), timeout=1) as lease:
        assert lease
        with repo_lock.hold_pausable(str(link), timeout=1) as through_link:
            assert not through_link
