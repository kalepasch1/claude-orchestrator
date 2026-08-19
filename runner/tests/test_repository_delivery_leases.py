"""Tests for repository/role delivery leases and their fencing token.

These do not mock `db.rpc` to return canned booleans. A canned True proves only that
the caller passed the arguments it meant to pass; it cannot show that a timed-out
predecessor is actually unable to write after takeover, which is the entire claim being
made. So the suite runs against `FakeLeaseStore` — an in-memory transcription of
002_repository_delivery_leases.sql, with a controllable clock and a real lock — and
exercises the concurrency properties directly.

Proof: python3 -m unittest runner.tests.test_repository_delivery_leases -v
"""

import os
import sys
import threading
import unittest
import uuid
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import delivery_lease


class FakeLeaseStore:
    """In-memory model of the lease table + its four RPCs.

    Mirrors the SQL exactly, including the parts that are easy to get wrong:
      * fence increments ONLY on a change of holder, never on self-renewal;
      * renew/verify/release match on (owner, token, fence, generation) together;
      * expiry is evaluated against the store's clock, not the caller's.
    """

    def __init__(self, now: float = 1_000_000.0):
        self.now = now
        self.rows: dict[tuple[str, str], dict] = {}
        self.lock = threading.Lock()
        self.calls: list[str] = []

    def tick(self, seconds: float) -> None:
        self.now += seconds

    def rpc(self, fn, args):
        with self.lock:
            self.calls.append(fn)
            return getattr(self, fn)(args)

    # ── RPC bodies ───────────────────────────────────────────────────────────
    def acquire_delivery_lease(self, a):
        key = (a["p_repo_key"], a["p_role"])
        ttl = max(60, int(a.get("p_ttl_seconds") or 900))
        row = self.rows.get(key)
        if row is None:
            row = {"repo_key": key[0], "role": key[1], "owner": a["p_owner"],
                   "runner_generation": a.get("p_generation") or "",
                   "lease_token": a["p_token"], "fence": 1,
                   "expires_at": self.now + ttl, "released_at": None}
            self.rows[key] = row
            return dict(row)
        # Same holder (owner + generation) re-acquiring: renewal, fence AND token kept.
        if (row["owner"] == a["p_owner"] and row["released_at"] is None
                and row["runner_generation"] == (a.get("p_generation") or "")):
            row["expires_at"] = self.now + ttl
            return dict(row)
        # Still live under another holder: contended.
        if row["released_at"] is None and row["expires_at"] > self.now:
            return None
        # Takeover: the fence moves, invalidating anything still in flight.
        row.update(owner=a["p_owner"], runner_generation=a.get("p_generation") or "",
                   lease_token=a["p_token"], fence=row["fence"] + 1,
                   expires_at=self.now + ttl, released_at=None)
        return dict(row)

    def _match(self, a):
        row = self.rows.get((a["p_repo_key"], a["p_role"]))
        if not row or row["released_at"] is not None:
            return None
        if (row["owner"] != a["p_owner"] or row["lease_token"] != a["p_token"]
                or row["fence"] != a["p_fence"]
                or row["runner_generation"] != (a.get("p_generation") or "")):
            return None
        return row

    def renew_delivery_lease(self, a):
        row = self._match(a)
        if row is None:
            return False
        row["expires_at"] = self.now + max(60, int(a.get("p_ttl_seconds") or 900))
        return True

    def verify_delivery_fence(self, a):
        row = self._match(a)
        return bool(row and row["expires_at"] > self.now)

    def release_delivery_lease(self, a):
        row = self._match(a)
        if row is None:
            return False
        row["released_at"] = self.now
        return True


REPO = "beethoven"
ROLE = delivery_lease.ROLE_RELEASER


class DeliveryLeaseTestBase(unittest.TestCase):
    def setUp(self):
        self.store = FakeLeaseStore()
        delivery_lease._active.clear()
        delivery_lease._available = True
        patcher = mock.patch.object(delivery_lease.db, "rpc", side_effect=self.store.rpc)
        self.rpc = patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(lambda: setattr(delivery_lease, "_available", None))
        self.addCleanup(lambda: setattr(delivery_lease, "_probed_at", 0.0))
        # ORCH_DELIVERY_LEASE_REQUIRED is process-global. A test in here closes the
        # compatibility window and never reopens it, so every LATER test in the same
        # pytest process saw require(None, ...) raise — including the release canary's
        # push tests, which then failed only when the two files shared a process. Restore
        # whatever the process started with.
        _saved_required = os.environ.get("ORCH_DELIVERY_LEASE_REQUIRED")
        self.addCleanup(
            lambda: os.environ.__setitem__("ORCH_DELIVERY_LEASE_REQUIRED", _saved_required)
            if _saved_required is not None
            else os.environ.pop("ORCH_DELIVERY_LEASE_REQUIRED", None))

    def acquire_as(self, owner, *, role=ROLE, generation=None, ttl=900):
        """Acquire as a named host. `generation` simulates a distinct process."""
        gen = generation or f"{owner}:gen1"
        with mock.patch.object(delivery_lease, "GENERATION", gen):
            return delivery_lease.acquire(REPO, role, owner=owner, ttl=ttl)


class AcquireAndFenceTest(DeliveryLeaseTestBase):
    def test_first_acquire_starts_at_fence_one(self):
        lease = self.acquire_as("mac1")
        self.assertIsNotNone(lease)
        self.assertEqual(lease.fence, 1)
        self.assertEqual(lease.repo_key, REPO)

    def test_second_host_is_refused_while_lease_is_live(self):
        self.assertIsNotNone(self.acquire_as("mac1"))
        self.assertIsNone(self.acquire_as("mac2"))

    def test_roles_are_independent(self):
        """A long merge-train pass must not block an unrelated release."""
        integ = self.acquire_as("mac1", role=delivery_lease.ROLE_INTEGRATOR)
        rel = self.acquire_as("mac2", role=delivery_lease.ROLE_RELEASER)
        self.assertIsNotNone(integ)
        self.assertIsNotNone(rel)

    def test_unknown_role_is_rejected(self):
        with self.assertRaises(ValueError):
            delivery_lease.acquire(REPO, "deployer")

    def test_self_reacquire_does_not_advance_the_fence(self):
        """A holder must never fence out its own in-flight work."""
        lease = self.acquire_as("mac1")
        again = self.acquire_as("mac1")          # same owner, same generation
        self.assertIsNotNone(again, "a holder must not deadlock against its own lease")
        self.assertEqual(again.fence, lease.fence)
        self.assertEqual(again.token, lease.token)
        # The handle already held by in-flight work still authorises writes.
        delivery_lease.require(lease, "push")

    def test_same_host_different_generation_is_a_takeover_not_a_renewal(self):
        """A restart is a new holder, even from the same hostname."""
        first = self.acquire_as("mac1", generation="mac1:gen1", ttl=60)
        self.store.tick(61)
        restarted = self.acquire_as("mac1", generation="mac1:gen2", ttl=60)
        self.assertIsNotNone(restarted)
        self.assertEqual(restarted.fence, first.fence + 1)
        with self.assertRaises(delivery_lease.LeaseLost):
            delivery_lease.require(first, "push")


class TakeoverTest(DeliveryLeaseTestBase):
    def test_expired_lease_is_taken_over_at_a_higher_fence(self):
        first = self.acquire_as("mac1", ttl=60)
        self.store.tick(61)
        second = self.acquire_as("mac2", ttl=60)
        self.assertIsNotNone(second)
        self.assertEqual(second.fence, first.fence + 1)

    def test_timed_out_predecessor_cannot_write_after_takeover(self):
        """The headline guarantee."""
        first = self.acquire_as("mac1", ttl=60)
        self.store.tick(61)
        second = self.acquire_as("mac2", ttl=60)
        self.assertIsNotNone(second)

        # The predecessor is still running and still believes it owns the repo.
        with self.assertRaises(delivery_lease.LeaseLost):
            delivery_lease.require(first, "push staging -> prod")
        # The incumbent is unaffected.
        delivery_lease.require(second, "push staging -> prod")

    def test_predecessor_renew_reports_genuine_loss(self):
        first = self.acquire_as("mac1", ttl=60)
        self.store.tick(61)
        self.assertIsNotNone(self.acquire_as("mac2", ttl=60))
        self.assertFalse(delivery_lease.renew(first))

    def test_predecessor_cannot_release_the_incumbents_lease(self):
        first = self.acquire_as("mac1", ttl=60)
        self.store.tick(61)
        second = self.acquire_as("mac2", ttl=60)
        self.assertFalse(delivery_lease.release(first))
        self.assertTrue(delivery_lease.verify(second))

    def test_voluntary_release_hands_over_without_waiting_out_the_ttl(self):
        first = self.acquire_as("mac1", ttl=3600)
        self.assertTrue(delivery_lease.release(first))
        second = self.acquire_as("mac2", ttl=3600)
        self.assertIsNotNone(second)
        self.assertEqual(second.fence, first.fence + 1)

    def test_fence_never_regresses_across_repeated_takeovers(self):
        seen = []
        for i in range(5):
            lease = self.acquire_as(f"mac{i}", ttl=60)
            self.assertIsNotNone(lease)
            seen.append(lease.fence)
            self.store.tick(61)
        self.assertEqual(seen, sorted(seen))
        self.assertEqual(len(set(seen)), len(seen))


class ExpiryAndRenewalTest(DeliveryLeaseTestBase):
    def test_renewal_keeps_a_long_pass_alive(self):
        """A merge train doing rebase + full test + build outlives one TTL."""
        lease = self.acquire_as("mac1", ttl=60)
        for _ in range(10):
            self.store.tick(50)
            self.assertTrue(delivery_lease.renew(lease))
        delivery_lease.require(lease, "push")            # still authorised
        self.assertIsNone(self.acquire_as("mac2", ttl=60))

    def test_lapsed_lease_refuses_writes_even_with_no_successor(self):
        """Expiry alone must stop writes; a takeover is not required first."""
        lease = self.acquire_as("mac1", ttl=60)
        self.store.tick(61)
        with self.assertRaises(delivery_lease.LeaseLost):
            delivery_lease.require(lease, "push")

    def test_ttl_floor_is_enforced(self):
        lease = self.acquire_as("mac1", ttl=1)
        self.store.tick(59)
        self.assertTrue(delivery_lease.verify(lease))


class ClockSkewTest(DeliveryLeaseTestBase):
    def test_expiry_follows_the_store_clock_not_the_callers(self):
        """Two Macs with skewed clocks must agree, because only the DB clock counts.

        The lease carries no caller-supplied timestamp for exactly this reason: a Mac
        whose clock runs fast would otherwise expire its own live lease, and one running
        slow would keep writing past the end of its lease.
        """
        lease = self.acquire_as("mac1", ttl=300)
        # mac1's local clock races an hour ahead; the store has not moved.
        with mock.patch("time.time", return_value=self.store.now + 3600):
            self.assertTrue(delivery_lease.verify(lease))
            delivery_lease.require(lease, "push")
        # And when the STORE passes the deadline, a slow local clock does not save it.
        self.store.tick(301)
        with mock.patch("time.time", return_value=self.store.now - 3600):
            with self.assertRaises(delivery_lease.LeaseLost):
                delivery_lease.require(lease, "push")

    def test_takeover_is_decided_by_the_store_clock(self):
        first = self.acquire_as("mac1", ttl=60)
        with mock.patch("time.time", return_value=self.store.now + 86400):
            self.assertIsNone(self.acquire_as("mac2", ttl=60))
        self.store.tick(61)
        self.assertIsNotNone(self.acquire_as("mac2", ttl=60))
        self.assertIsNotNone(first)


class ConcurrentTwoMacTest(DeliveryLeaseTestBase):
    def test_only_one_of_many_racing_hosts_acquires(self):
        results = []
        barrier = threading.Barrier(8)

        def contend(i):
            barrier.wait()
            results.append(self.acquire_as(f"mac{i}", ttl=600))

        threads = [threading.Thread(target=contend, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        winners = [r for r in results if r is not None]
        self.assertEqual(len(winners), 1, "exactly one host may hold the lease")
        self.assertEqual(winners[0].fence, 1)

    def test_racing_takeovers_after_expiry_yield_one_winner_at_one_fence(self):
        self.acquire_as("mac0", ttl=60)
        self.store.tick(61)

        results = []
        barrier = threading.Barrier(6)

        def contend(i):
            barrier.wait()
            results.append(self.acquire_as(f"mac{i}", ttl=600))

        threads = [threading.Thread(target=contend, args=(i,)) for i in range(1, 7)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        winners = [r for r in results if r is not None]
        self.assertEqual(len(winners), 1)
        self.assertEqual(winners[0].fence, 2)
        # And only the winner may write.
        self.assertTrue(delivery_lease.verify(winners[0]))


class RunnerGenerationTest(DeliveryLeaseTestBase):
    def test_a_restarted_runner_cannot_reuse_a_leaked_token(self):
        """Binding to generation is what stops a resurrected process, not the token.

        A hostname outlives a crash and a token can be persisted; the generation is
        minted per process incarnation, so a restarted runner replaying an old token is
        refused even though owner+token+fence all still match.
        """
        lease = self.acquire_as("mac1", generation="mac1:gen1", ttl=600)
        impostor = delivery_lease.Lease(
            repo_key=lease.repo_key, role=lease.role, owner=lease.owner,
            token=lease.token, fence=lease.fence, generation="mac1:gen2", ttl=600)
        self.assertFalse(delivery_lease.verify(impostor))
        self.assertFalse(delivery_lease.renew(impostor))
        with self.assertRaises(delivery_lease.LeaseLost):
            delivery_lease.require(impostor, "push")
        # The real holder is untouched.
        delivery_lease.require(lease, "push")


class InfraFailureTest(DeliveryLeaseTestBase):
    def test_acquire_fails_closed_on_rpc_outage(self):
        """Not acquiring costs a delayed pass; wrongly acquiring costs a push race."""
        with mock.patch.object(delivery_lease.db, "rpc",
                               side_effect=RuntimeError("control plane down")):
            self.assertIsNone(delivery_lease.acquire(REPO, ROLE, owner="mac1"))

    def test_write_gate_fails_closed_on_rpc_outage(self):
        lease = self.acquire_as("mac1", ttl=600)
        with mock.patch.object(delivery_lease.db, "rpc",
                               side_effect=RuntimeError("control plane down")):
            self.assertFalse(delivery_lease.verify(lease))
            with self.assertRaises(delivery_lease.LeaseLost):
                delivery_lease.require(lease, "push")

    def test_renew_fails_soft_on_rpc_outage(self):
        """A lease-infra blip must not mass-kill running passes — require() still gates."""
        lease = self.acquire_as("mac1", ttl=600)
        with mock.patch.object(delivery_lease.db, "rpc",
                               side_effect=RuntimeError("control plane down")):
            self.assertTrue(delivery_lease.renew(lease))


class RetryTest(DeliveryLeaseTestBase):
    def test_contended_host_acquires_on_a_later_retry(self):
        first = self.acquire_as("mac1", ttl=60)
        self.assertIsNone(self.acquire_as("mac2", ttl=60))     # attempt 1: contended
        self.store.tick(30)
        self.assertIsNone(self.acquire_as("mac2", ttl=60))     # attempt 2: still contended
        self.store.tick(31)
        second = self.acquire_as("mac2", ttl=60)               # attempt 3: lease lapsed
        self.assertIsNotNone(second)
        self.assertEqual(second.fence, first.fence + 1)

    def test_retrying_a_write_after_lease_loss_stays_refused(self):
        """A retry loop must not launder a lost lease into a successful push."""
        first = self.acquire_as("mac1", ttl=60)
        self.store.tick(61)
        self.acquire_as("mac2", ttl=600)
        for _ in range(3):
            with self.assertRaises(delivery_lease.LeaseLost):
                delivery_lease.require(first, "push attempt")


class CompatibilityWindowTest(DeliveryLeaseTestBase):
    def test_unfenced_write_allowed_while_rpcs_are_undeployed(self):
        """Un-migrated hosts fall back to the legacy election rather than stalling."""
        delivery_lease._available = False
        os.environ.pop("ORCH_DELIVERY_LEASE_REQUIRED", None)
        delivery_lease.require(None, "push")                   # must not raise

    def test_unfenced_write_refused_once_rpcs_are_deployed(self):
        delivery_lease._available = True
        delivery_lease.require(self.acquire_as("mac1"), "push")
        with self.assertRaises(delivery_lease.LeaseLost):
            delivery_lease.require(None, "push")

    def test_required_flag_closes_the_window_explicitly(self):
        delivery_lease._available = False
        os.environ["ORCH_DELIVERY_LEASE_REQUIRED"] = "true"
        self.assertTrue(delivery_lease.required())
        with self.assertRaises(delivery_lease.LeaseLost):
            delivery_lease.require(None, "push")

    def test_control_plane_outage_does_not_halt_delivery_fleet_wide(self):
        """An outage must not be mistaken for 'fencing is deployed'.

        Regression: available() once returned `not _missing_schema(exc)`, so an
        unrecognised error — bad credentials, a Supabase blip — reported the fencing
        plane AVAILABLE. Every unfenced call site then raised LeaseLost and merges and
        releases stopped on every host at once. Only a positive probe means available.
        """
        for outage in (RuntimeError("set SUPABASE_URL and SUPABASE_SERVICE_KEY"),
                       RuntimeError("connection reset by peer"),
                       RuntimeError("503 Service Unavailable")):
            delivery_lease._available = None
            delivery_lease._probed_at = 0.0
            with mock.patch.object(delivery_lease.db, "rpc", side_effect=outage):
                self.assertFalse(delivery_lease.available(), f"outage {outage} claimed available")
                delivery_lease.require(None, "push")        # must not raise

    def test_a_failed_probe_is_retried_rather_than_memoised_forever(self):
        delivery_lease._available = None
        delivery_lease._probed_at = 0.0
        with mock.patch.object(delivery_lease.db, "rpc", side_effect=RuntimeError("blip")):
            self.assertFalse(delivery_lease.available())
        # Credentials arrive later in the process' life; the window must be able to close.
        delivery_lease._probed_at -= (delivery_lease.PROBE_RETRY_S + 1)
        with mock.patch.object(delivery_lease.db, "rpc", return_value=False):
            self.assertTrue(delivery_lease.available())

    def test_outage_still_cannot_authorise_a_fenced_write(self):
        """Softening available() must not soften the actual enforcement point."""
        lease = self.acquire_as("mac1", ttl=600)
        with mock.patch.object(delivery_lease.db, "rpc", side_effect=RuntimeError("blip")):
            with self.assertRaises(delivery_lease.LeaseLost):
                delivery_lease.require(lease, "push")

    def test_missing_schema_is_distinguished_from_a_real_outage(self):
        self.assertTrue(delivery_lease._missing_schema(
            Exception("PGRST202 could not find function verify_delivery_fence")))
        self.assertTrue(delivery_lease._missing_schema(
            Exception('relation "repository_delivery_leases" does not exist')))
        self.assertFalse(delivery_lease._missing_schema(Exception("connection reset by peer")))
        self.assertFalse(delivery_lease._missing_schema(Exception("503 upstream timeout")))


if __name__ == "__main__":
    unittest.main(verbosity=2)
