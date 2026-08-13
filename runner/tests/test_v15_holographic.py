import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import hivemind_v15 as v15
import v15_holographic as hg


class TestScopePolicy(unittest.TestCase):
    """Federation is the base contract; isolation is an explicit opt-in.

    ``HolographicMemory`` deliberately shares entries across apps -- one app
    stores a signal and another reads it back as ``federated_memory``.  Three
    tests in ``test_hivemind_v15`` assert exactly that, so a wrapper must not
    quietly take it away.  What was missing is the *choice*, which ``Scope``
    now makes explicit.
    """

    def test_fleet_scope_preserves_federation(self):
        mem = hg.VersionedMemory(scope=hg.Scope.FLEET)
        mem.put("tomorrow", {"query": "risk 42"}, {"answer": 7})
        hit = mem.get("smarter", {"query": "risk 42"})
        self.assertIsNotNone(hit)
        self.assertEqual(hit.value, {"answer": 7})

    def test_fleet_scope_is_the_default(self):
        self.assertEqual(hg.VersionedMemory().scope, hg.Scope.FLEET)

    def test_tenant_scope_keeps_a_signal_private(self):
        mem = hg.VersionedMemory(scope=hg.Scope.TENANT)
        mem.put("tomorrow", {"customer": "acme", "detail": "private"}, "TOMORROW-ONLY")
        self.assertIsNone(mem.get("galop", {"customer": "acme", "detail": "private"}))

    def test_tenant_scope_still_serves_the_owner(self):
        mem = hg.VersionedMemory(scope=hg.Scope.TENANT)
        mem.put("tomorrow", {"customer": "acme"}, "TOMORROW-ONLY")
        hit = mem.get("tomorrow", {"customer": "acme"})
        self.assertIsNotNone(hit)
        self.assertEqual(hit.value, "TOMORROW-ONLY")
        self.assertTrue(hit.exact)

    def test_tenant_backing_memories_are_distinct_objects(self):
        mem = hg.VersionedMemory(scope=hg.Scope.TENANT)
        self.assertIsNot(mem.backing("tomorrow"), mem.backing("galop"))
        self.assertIs(mem.backing("tomorrow"), mem.backing("tomorrow"))

    def test_fleet_backing_is_the_single_shared_memory(self):
        mem = hg.VersionedMemory(scope=hg.Scope.FLEET)
        self.assertIs(mem.backing("tomorrow"), mem.backing("galop"))
        self.assertIs(mem.backing("tomorrow"), mem.memory)

    def test_unknown_scope_is_refused(self):
        with self.assertRaises(ValueError):
            hg.VersionedMemory(scope="everyone")


class TestVersionedKeys(unittest.TestCase):
    def test_key_round_trips(self):
        enc = v15.FractalEncoder()
        key = hg.VersionedKey.build("tomorrow", enc.encode({"a": 1}), enc)
        self.assertEqual(hg.VersionedKey.parse(key.encode()), key)
        self.assertTrue(key.compatible_with(enc))

    def test_changed_encoder_parameters_are_detected_not_guessed(self):
        enc = v15.FractalEncoder(scales=6, keep_per_scale=4)
        other = v15.FractalEncoder(scales=3, keep_per_scale=2)
        key = hg.VersionedKey.build("tomorrow", enc.encode({"a": 1}), enc)
        self.assertTrue(key.compatible_with(enc))
        self.assertFalse(key.compatible_with(other))

    def test_malformed_key_is_rejected(self):
        for bad in ("", "nope", "hk.1.aa.bb", "zz.1.a.b.c", "hk.x.a.b.c"):
            with self.assertRaises(ValueError):
                hg.VersionedKey.parse(bad)

    def test_migration_retires_incompatible_records(self):
        mem = hg.VersionedMemory()
        key = mem.put("tomorrow", {"a": 1}, "value")
        report = mem.migrate(v15.FractalEncoder(scales=3, keep_per_scale=2))
        self.assertIn(key, report["retired"])
        self.assertEqual(report["retained"], [])
        with self.assertRaises(KeyError):
            mem.read_record(key)

    def test_migration_keeps_compatible_records(self):
        mem = hg.VersionedMemory()
        key = mem.put("tomorrow", {"a": 1}, "value")
        report = mem.migrate(v15.FractalEncoder())  # same parameters
        self.assertEqual(report["retired"], [])
        self.assertIn(key, report["retained"])
        self.assertEqual(mem.read_record(key).value, "value")


class TestCorruptionRecovery(unittest.TestCase):
    def test_tampered_record_is_detected_and_dropped(self):
        mem = hg.VersionedMemory()
        key = mem.put("tomorrow", {"a": 1}, "original")
        mem._records[key].value = "TAMPERED"
        with self.assertRaises(hg.CorruptRecord):
            mem.read_record(key)
        self.assertNotIn(key, mem._records)  # dropped, not merely reported

    def test_scrub_sweeps_every_corrupt_record(self):
        mem = hg.VersionedMemory()
        good = mem.put("tomorrow", {"a": 1}, "good")
        bad = mem.put("tomorrow", {"b": 2}, "bad")
        mem._records[bad].coefficients = ((0, 0, 9.9),)
        report = mem.scrub()
        self.assertEqual(report["dropped"], 1)
        self.assertEqual(report["keys"], [bad])
        self.assertEqual(mem.read_record(good).value, "good")

    def test_checksum_covers_app_so_a_record_cannot_be_reassigned(self):
        mem = hg.VersionedMemory()
        key = mem.put("tomorrow", {"a": 1}, "v")
        mem._records[key].app = "galop"
        self.assertFalse(mem._records[key].verify())


class TestRetentionAndQuota(unittest.TestCase):
    def test_ttl_evicts_independently_of_capacity(self):
        mem = hg.VersionedMemory(ttl_seconds=10)
        key = mem.put("tomorrow", {"a": 1}, "v")
        self.assertEqual(mem.expire(now=mem._records[key].stored_at + 5), 0)
        self.assertEqual(mem.expire(now=mem._records[key].stored_at + 11), 1)
        self.assertEqual(mem.app_usage().get("tomorrow", 0), 0)

    def test_no_ttl_means_no_expiry(self):
        mem = hg.VersionedMemory()
        mem.put("tomorrow", {"a": 1}, "v")
        self.assertEqual(mem.expire(now=1e12), 0)

    def test_per_app_quota_is_enforced_per_tenant(self):
        mem = hg.VersionedMemory(per_app_quota=2)
        mem.put("tomorrow", {"a": 1}, "v")
        mem.put("tomorrow", {"b": 2}, "v")
        with self.assertRaises(hg.QuotaExceeded):
            mem.put("tomorrow", {"c": 3}, "v")
        # A different tenant has its own budget.
        mem.put("galop", {"d": 4}, "v")
        self.assertEqual(mem.app_usage()["galop"], 1)

    def test_rewriting_an_existing_key_does_not_consume_quota(self):
        mem = hg.VersionedMemory(per_app_quota=1)
        mem.put("tomorrow", {"a": 1}, "first")
        mem.put("tomorrow", {"a": 1}, "second")  # same key, must not raise
        self.assertEqual(mem.app_usage()["tomorrow"], 1)


class TestMeasuredReports(unittest.TestCase):
    def test_compression_is_measured_not_asserted(self):
        enc = v15.FractalEncoder()
        signals = [{"kind": "task", "n": i, "body": f"payload-{i}" * 4} for i in range(20)]
        report = hg.compression_report(enc, signals)
        self.assertEqual(report["signals"], 20)
        self.assertGreater(report["coefficient_bytes"], 0)
        self.assertAlmostEqual(
            report["compression_ratio"],
            report["full_signal_bytes"] / report["coefficient_bytes"], places=6)

    def test_recall_is_measured_on_real_round_trips(self):
        mem = hg.VersionedMemory(v15.HolographicMemory(capacity=128))
        pairs = [({"kind": "t", "n": i}, f"value-{i}") for i in range(16)]
        report = hg.recall_report(mem, "tomorrow", pairs)
        self.assertEqual(report["stored"], 16)
        self.assertGreaterEqual(report["recall"], 0.0)
        self.assertLessEqual(report["recall"], 1.0)
        self.assertEqual(report["exact_recall"], report["exact"] / 16)

    def test_empty_input_is_refused_rather_than_reported_as_perfect(self):
        with self.assertRaises(ValueError):
            hg.compression_report(v15.FractalEncoder(), [])
        with self.assertRaises(ValueError):
            hg.recall_report(hg.VersionedMemory(), "tomorrow", [])

    def test_benchmark_runs_end_to_end(self):
        report = hg.benchmark(samples=12)
        self.assertIn("compression", report)
        self.assertIn("recall", report)
        self.assertEqual(report["recall"]["stored"], 12)

    def test_consolidate_reports_versioned_index_size(self):
        mem = hg.VersionedMemory()
        mem.put("tomorrow", {"a": 1}, "v")
        stats = mem.consolidate()
        self.assertEqual(stats["versioned_records"], 1)
        self.assertEqual(stats["tracked_apps"], 1)


if __name__ == "__main__":
    unittest.main()
