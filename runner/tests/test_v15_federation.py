import os
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import hivemind_v15 as v15
import v15_federation as fed


def open_federation(slots=8, **kw):
    f = fed.GovernedFederation(slots=slots, **kw)
    for app in v15.FLEET_APPS:
        f.grant(app, shares_with=("*",))
    return f


class TestLifetimeSafety(unittest.TestCase):
    """The defect this module exists to close.

    ``ZeroCopyFederation`` hands back a read-only memoryview into a ring that
    wraps.  Once the slot is recycled the SAME view starts returning a different
    app's bytes, silently -- there is no error and no way for the borrower to
    notice.  A lease with a generation counter makes recycling detectable.
    """

    def test_base_ring_view_mutates_silently_when_the_ring_wraps(self):
        memory = v15.HolographicMemory()
        base = v15.ZeroCopyFederation(memory, slots=2)
        view = base.publish_key(memory.encoder.encode({"a": 1}))
        snapshot = bytes(view)
        for i in range(2):
            base.publish_key(memory.encoder.encode({"z": i}))
        self.assertNotEqual(bytes(view), snapshot)  # documented, not hypothetical

    def test_governed_lease_detects_recycling_instead_of_returning_wrong_bytes(self):
        f = open_federation(slots=2)
        lease = f.publish("tomorrow", {"a": 1})
        self.assertEqual(f.read("tomorrow", lease)["body"], {"a": 1})
        for i in range(2):
            f.publish("galop", {"z": i})
        with self.assertRaises(fed.StaleLease):
            f.read("tomorrow", lease)
        self.assertEqual(f.telemetry.stale_reads, 1)

    def test_a_fresh_lease_on_the_same_slot_is_valid(self):
        f = open_federation(slots=1)
        f.publish("tomorrow", {"a": 1})
        second = f.publish("tomorrow", {"a": 2})
        self.assertEqual(f.read("tomorrow", second)["body"], {"a": 2})

    def test_view_is_readonly_and_does_not_copy(self):
        f = open_federation()
        lease = f.publish("tomorrow", {"a": 1})
        with f.view("tomorrow", lease) as v:
            self.assertIsInstance(v, memoryview)
            self.assertTrue(v.readonly)
        self.assertEqual(f.telemetry.copies_made, 0)   # a view is not a copy
        self.assertGreater(f.telemetry.bytes_viewed, 0)


class TestCapabilitiesAndConsent(unittest.TestCase):
    def test_all_ten_fleet_identities_can_participate(self):
        f = open_federation(slots=32)
        for app in v15.FLEET_APPS:
            lease = f.publish(app, {"from": app})
            self.assertEqual(f.read(app, lease)["app"], app)
        self.assertEqual(len(v15.FLEET_APPS), 10)

    def test_ungranted_app_is_denied(self):
        f = fed.GovernedFederation()
        with self.assertRaises(fed.AclDenied):
            f.publish("tomorrow", {"a": 1})

    def test_missing_capability_is_denied(self):
        f = fed.GovernedFederation()
        f.grant("tomorrow", capabilities=(fed.Capability.QUERY,))
        with self.assertRaises(fed.AclDenied):
            f.publish("tomorrow", {"a": 1})

    def test_unknown_capability_is_refused_at_grant_time(self):
        f = fed.GovernedFederation()
        with self.assertRaises(ValueError):
            f.grant("tomorrow", capabilities=("root",))

    def test_reading_without_consent_is_denied(self):
        f = fed.GovernedFederation()
        f.grant("tomorrow")                      # shares with nobody
        f.grant("galop")
        lease = f.publish("tomorrow", {"secret": 1})
        with self.assertRaises(fed.AclDenied):
            f.read("galop", lease)
        # The owner can always read its own.
        self.assertEqual(f.read("tomorrow", lease)["body"], {"secret": 1})

    def test_explicit_consent_permits_exactly_the_named_reader(self):
        f = fed.GovernedFederation()
        f.grant("tomorrow", shares_with=("galop",))
        f.grant("galop")
        f.grant("vigil")
        lease = f.publish("tomorrow", {"shared": 1})
        self.assertEqual(f.read("galop", lease)["body"], {"shared": 1})
        with self.assertRaises(fed.AclDenied):
            f.read("vigil", lease)


class TestRedactionAndQuota(unittest.TestCase):
    def test_redacted_fields_never_reach_the_shared_buffer(self):
        f = fed.GovernedFederation()
        f.grant("tomorrow", shares_with=("*",), redact_fields=("ssn",))
        lease = f.publish("tomorrow", {"name": "acme", "ssn": "123-45-6789"})
        body = f.read("tomorrow", lease)["body"]
        self.assertEqual(body["ssn"], "[redacted]")
        # And not merely hidden on read -- the raw bytes must not contain it.
        with f.view("tomorrow", lease) as v:
            self.assertNotIn(b"123-45-6789", bytes(v))

    def test_quota_is_enforced_per_app(self):
        f = fed.GovernedFederation()
        f.grant("tomorrow", shares_with=("*",), publish_quota=2)
        f.grant("galop", shares_with=("*",), publish_quota=2)
        f.publish("tomorrow", {"i": 1})
        f.publish("tomorrow", {"i": 2})
        with self.assertRaises(fed.QuotaExceeded):
            f.publish("tomorrow", {"i": 3})
        f.publish("galop", {"i": 1})     # separate budget
        self.assertEqual(f.quota_state()["tomorrow"]["used"], 2)

    def test_oversized_envelope_is_refused_not_truncated(self):
        f = open_federation(slot_size=256)
        with self.assertRaises(ValueError):
            f.publish("tomorrow", {"blob": "x" * 4096})


class TestSchemaAndExchange(unittest.TestCase):
    def test_version_mismatch_is_detected(self):
        f = open_federation()
        lease = f.publish("tomorrow", {"a": 1})
        original = fed.ENVELOPE_VERSION
        try:
            fed.ENVELOPE_VERSION = original + 1
            with self.assertRaises(fed.SchemaMismatch):
                f.read("tomorrow", lease)
        finally:
            fed.ENVELOPE_VERSION = original

    def test_correlated_result_round_trip(self):
        f = open_federation()
        f.submit_result("galop", "corr-1", {"answer": 42})
        got = f.await_result("tomorrow", "corr-1", timeout_s=.2)
        self.assertEqual(got["result"], {"answer": 42})
        self.assertEqual(got["app"], "galop")

    def test_missing_result_times_out_rather_than_hanging(self):
        f = open_federation()
        t0 = time.perf_counter()
        with self.assertRaises(fed.ExchangeTimeout):
            f.await_result("tomorrow", "never", timeout_s=.05)
        self.assertLess(time.perf_counter() - t0, 2.0)

    def test_result_delivered_late_is_still_picked_up(self):
        f = open_federation()

        def producer():
            time.sleep(.02)
            f.submit_result("galop", "corr-late", {"ok": True})

        threading.Thread(target=producer, daemon=True).start()
        self.assertEqual(f.await_result("tomorrow", "corr-late", timeout_s=1.0)["result"],
                         {"ok": True})

    def test_result_without_consent_is_denied(self):
        f = fed.GovernedFederation()
        f.grant("galop")                 # shares with nobody
        f.grant("tomorrow")
        f.submit_result("galop", "c", {"x": 1})
        with self.assertRaises(fed.AclDenied):
            f.await_result("tomorrow", "c", timeout_s=.05)


class TestCrashRecovery(unittest.TestCase):
    def test_clean_ring_reports_every_written_slot_intact(self):
        f = open_federation(slots=4)
        for i in range(3):
            f.publish("tomorrow", {"i": i})
        report = f.recover()
        self.assertEqual(report["intact"], 3)
        self.assertEqual(report["torn"], [])

    def test_torn_slot_is_discarded_not_parsed(self):
        f = open_federation(slots=4)
        lease = f.publish("tomorrow", {"i": 1})
        start = lease.slot * f.slot_size + fed.HEADER_SIZE
        f._ring[start + 2:start + 6] = b"\xff\xff\xff\xff"   # half-written body
        report = f.recover()
        self.assertEqual(len(report["torn"]), 1)
        self.assertEqual(report["torn"][0]["slot"], lease.slot)

    def test_recovery_invalidates_leases_on_discarded_slots(self):
        f = open_federation(slots=4)
        lease = f.publish("tomorrow", {"i": 1})
        start = lease.slot * f.slot_size + fed.HEADER_SIZE
        f._ring[start:start + 4] = b"\xff\xff\xff\xff"
        f.recover()
        with self.assertRaises(fed.StaleLease):
            f.read("tomorrow", lease)

    def test_impossible_length_is_discarded(self):
        f = open_federation(slots=2)
        lease = f.publish("tomorrow", {"i": 1})
        import struct as _s
        _s.pack_into(fed.HEADER, f._ring, lease.slot * f.slot_size,
                     f.slot_size * 10, lease.generation, 0)
        report = f.recover()
        self.assertEqual(report["torn"][0]["reason"], "impossible_length")


class TestTransportBoundary(unittest.TestCase):
    def test_cross_host_publish_without_secure_transport_is_refused(self):
        f = open_federation()
        with self.assertRaises(fed.InsecureTransport):
            fed.publish_remote(f, "tomorrow", {"a": 1}, host="other-host")

    def test_cross_host_publish_uses_the_supplied_transport(self):
        f = open_federation()
        sent = []
        result = fed.publish_remote(f, "tomorrow", {"a": 1}, host="other-host",
                                    transport=lambda h, b: sent.append((h, b)) or "sent")
        self.assertEqual(result, "sent")
        self.assertEqual(sent[0][0], "other-host")

    def test_remote_publish_still_redacts(self):
        f = fed.GovernedFederation()
        f.grant("tomorrow", redact_fields=("ssn",))
        captured = {}
        fed.publish_remote(f, "tomorrow", {"ssn": "123-45-6789"}, host="h",
                           transport=lambda h, b: captured.setdefault("b", b))
        self.assertNotIn(b"123-45-6789", captured["b"])


class TestTelemetry(unittest.TestCase):
    def test_copies_and_views_are_counted_separately(self):
        f = open_federation()
        lease = f.publish("tomorrow", {"a": 1})
        with f.view("tomorrow", lease):
            pass
        f.read("tomorrow", lease)
        stats = f.telemetry.as_dict()
        self.assertEqual(stats["views_handed_out"], 2)   # read() borrows too
        self.assertEqual(stats["copies_made"], 1)
        self.assertGreater(stats["bytes_copied"], 0)
        self.assertGreaterEqual(stats["mean_publish_us"], 0.0)

    def test_telemetry_reports_zero_publishes_without_dividing_by_zero(self):
        self.assertEqual(fed.Telemetry().as_dict()["mean_publish_us"], 0.0)


if __name__ == "__main__":
    unittest.main()
