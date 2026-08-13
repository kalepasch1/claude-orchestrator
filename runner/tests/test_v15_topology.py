import os
import sys
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import hivemind_v15 as v15
import v15_topology as topo

T = 1_000_000.0


def teacher(q):
    return {"answer": sorted(q.items()) if isinstance(q, dict) else q}


def build(**kw):
    kw.setdefault("formation_threshold", 2)
    t = topo.Topology(**kw)
    t.authorize("tomorrow", "galop")
    return t


def form(t, app="tomorrow", query=None, **kw):
    query = query if query is not None else {"kind": "q", "n": 1}
    cluster = None
    for _ in range(t.threshold):
        cluster = t.observe(app, query, teacher, now=T, **kw)
    return cluster


class TestUnboundedCardinality(unittest.TestCase):
    """The leak this module closes."""

    def test_base_topology_never_prunes_its_counters(self):
        base = v15.QueryTopology(ttl_seconds=0)
        for i in range(2000):
            base.observe("tomorrow", {f"k{i}": 1}, teacher)
        base.dissolve(now=1e12)
        self.assertEqual(len(base.clusters), 0)
        self.assertEqual(len(base.counts), 2000)   # every counter survives

    def test_pattern_counting_is_hard_capped(self):
        t = build(max_patterns=64)
        for i in range(2000):
            t.observe("tomorrow", {f"k{i}": 1}, teacher, now=T)
        self.assertLessEqual(len(t.counts), 64)
        self.assertGreater(t.counts.evicted, 0)
        self.assertLessEqual(t.state()["tracked_patterns"], 64)

    def test_forming_a_cluster_releases_its_counter(self):
        t = build()
        before = len(t.counts)
        form(t)
        self.assertLessEqual(len(t.counts), before)

    def test_cluster_count_is_capped(self):
        t = build(max_clusters=2)
        for i in range(10):
            q = {f"shape{i}": 1}
            for _ in range(t.threshold):
                t.observe("tomorrow", q, teacher, now=T)
        self.assertLessEqual(len(t.clusters), 2)
        self.assertGreater(t.metrics["formation_refused_capacity"], 0)

    def test_zero_cap_is_refused(self):
        with self.assertRaises(ValueError):
            topo.BoundedPatternCounter(max_patterns=0)


class TestAuthorizationAndKeys(unittest.TestCase):
    def test_unauthorized_app_cannot_form_a_cluster(self):
        t = topo.Topology()
        with self.assertRaises(topo.NotAuthorized):
            t.observe("tomorrow", {"a": 1}, teacher, now=T)

    def test_authorized_app_forms_normally(self):
        t = build()
        self.assertIsNotNone(form(t))

    def test_a_printable_separator_would_collide(self):
        """Why the separator is NUL: a printable one is forgeable.

        With ':' the pairs ('a:b', 'c') and ('a', 'b:c') produce the same key,
        so one tenant can address another's cluster by naming its pattern
        carefully.
        """
        naive = lambda app, pattern: f"{app}:{pattern}"
        self.assertEqual(naive("a:b", "c"), naive("a", "b:c"))

    def test_the_reserved_separator_makes_that_forgery_impossible(self):
        # The only way to collide is to smuggle the separator into a component,
        # and a component containing it is refused outright.
        with self.assertRaises(ValueError):
            topo.tenant_key("tomorrow", f"b{topo.KEY_SEPARATOR}c")
        # Distinct patterns therefore always produce distinct keys.
        self.assertNotEqual(topo.tenant_key("tomorrow", "b:c"),
                            topo.tenant_key("tomorrow", "b"))

    def test_reserved_separator_is_refused_in_a_key_component(self):
        with self.assertRaises(ValueError):
            topo.tenant_key("tomorrow", f"pat{topo.KEY_SEPARATOR}tern")

    def test_two_apps_with_the_same_query_get_separate_clusters(self):
        t = build()
        q = {"kind": "shared"}
        form(t, "tomorrow", q)
        form(t, "galop", q)
        self.assertEqual(len(t.clusters), 2)


class TestPlanLifecycle(unittest.TestCase):
    def test_stale_plan_falls_back_and_dissolves(self):
        t = build()
        form(t, query={"k": 1}, plan_source={"v": 1})
        out = t.execute("tomorrow", {"k": 1}, generic=teacher, plan_source={"v": 2}, now=T)
        self.assertEqual(out["source"], "generic_after_stale_plan")
        self.assertEqual(len(t.clusters), 0)
        self.assertEqual(t.metrics["stale_plan"], 1)

    def test_matching_plan_serves_from_the_cluster(self):
        t = build()
        form(t, query={"k": 1}, plan_source={"v": 1})
        out = t.execute("tomorrow", {"k": 1}, generic=teacher, plan_source={"v": 1}, now=T)
        self.assertEqual(out["source"], "cluster")

    def test_plan_fingerprint_is_order_independent(self):
        self.assertEqual(topo.plan_fingerprint({"a": 1, "b": 2}),
                         topo.plan_fingerprint({"b": 2, "a": 1}))


class TestCacheIntegrity(unittest.TestCase):
    def test_cache_entries_are_stamped_with_the_plan_that_made_them(self):
        t = build()
        cluster = form(t, query={"k": 1})
        t.execute("tomorrow", {"k": 1}, generic=teacher, now=T)
        entry = next(iter(cluster.cache.values()))
        self.assertEqual(entry.plan_fingerprint, cluster.plan.fingerprint)

    def test_an_entry_written_under_another_plan_is_not_served(self):
        t = build()
        cluster = form(t, query={"k": 1})
        t.execute("tomorrow", {"k": 1}, generic=teacher, now=T)
        # Simulate a poisoned/legacy entry under a different plan.
        key = next(iter(cluster.cache))
        cluster.cache[key] = topo.CacheEntry("POISONED", "some-other-plan", T)
        out = t.execute("tomorrow", {"k": 1}, generic=teacher, now=T)
        self.assertNotEqual(out["result"], "POISONED")

    def test_warming_uses_the_clusters_own_node_not_caller_values(self):
        t = build()
        cluster = form(t, query={"kind": "warm", "n": 1})
        warmed = t.warm("tomorrow", [{"kind": "warm", "n": 1}], now=T)
        self.assertEqual(warmed, 1)
        entry = next(iter(cluster.cache.values()))
        self.assertEqual(entry.value, teacher({"kind": "warm", "n": 1}))

    def test_warm_is_idempotent(self):
        t = build()
        form(t, query={"kind": "warm", "n": 1})
        q = [{"kind": "warm", "n": 1}]
        self.assertEqual(t.warm("tomorrow", q, now=T), 1)
        self.assertEqual(t.warm("tomorrow", q, now=T), 0)


class TestBudgetAndStarvation(unittest.TestCase):
    def test_exhausted_budget_degrades_to_generic(self):
        t = build(cluster_budget=2)
        form(t, query={"k": 1})
        for _ in range(2):
            t.execute("tomorrow", {"k": 1}, generic=teacher, now=T)
        out = t.execute("tomorrow", {"k": 1}, generic=teacher, now=T)
        self.assertEqual(out["source"], "generic_budget_exhausted")

    def test_admission_keeps_a_starvation_reserve(self):
        t = build(cluster_budget=10, reserve_fraction=.5)
        form(t, query={"k": 1})
        for _ in range(5):
            t.admit("tomorrow", {"k": 1})
        with self.assertRaises(topo.AdmissionRefused):
            t.admit("tomorrow", {"k": 1})

    def test_admission_on_an_unformed_pattern_is_a_noop(self):
        t = build()
        t.admit("tomorrow", {"never": "seen"})   # must not raise

    def test_invalid_reserve_fraction_is_refused(self):
        with self.assertRaises(ValueError):
            topo.Topology(reserve_fraction=1.0)


class TestParityAndFallback(unittest.TestCase):
    def test_cluster_result_is_identical_to_the_generic_path(self):
        t = build()
        queries = [{"kind": "q", "n": i} for i in range(5)]
        for q in queries:
            form(t, query=q)
        for q in queries:
            out = t.execute("tomorrow", q, generic=teacher, now=T)
            self.assertEqual(out["result"], teacher(q))

    def test_generic_path_always_available_before_formation(self):
        t = build()
        out = t.execute("tomorrow", {"never": "clustered"}, generic=teacher, now=T)
        self.assertEqual(out["source"], "generic")
        self.assertEqual(out["result"], teacher({"never": "clustered"}))

    def test_generic_path_survives_dissolution(self):
        t = build(ttl_seconds=10)
        form(t, query={"k": 1})
        self.assertEqual(t.dissolve(now=T + 100), list(t.metrics and []) or
                         [topo.tenant_key("tomorrow", v15.pattern_key({"k": 1}))])
        out = t.execute("tomorrow", {"k": 1}, generic=teacher, now=T + 200)
        self.assertEqual(out["source"], "generic")


class TestDissolutionDeterminism(unittest.TestCase):
    def test_dissolution_is_sorted_and_repeatable(self):
        t = build(ttl_seconds=1)
        for i in range(5):
            form(t, query={f"s{i}": 1})
        dissolved = t.dissolve(now=T + 100)
        self.assertEqual(dissolved, sorted(dissolved))
        self.assertEqual(t.dissolve(now=T + 200), [])   # nothing left

    def test_dissolving_an_unknown_key_reports_false(self):
        t = build()
        self.assertFalse(t.dissolve_key("nope"))


class TestConcurrency(unittest.TestCase):
    def test_concurrent_observation_forms_one_cluster_not_many(self):
        t = build(formation_threshold=2)
        errors = []

        def worker():
            try:
                for _ in range(50):
                    t.observe("tomorrow", {"kind": "hot"}, teacher, now=T)
            except Exception as exc:          # surface, never swallow
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        [th.start() for th in threads]
        [th.join() for th in threads]
        self.assertEqual(errors, [])
        self.assertEqual(len(t.clusters), 1)

    def test_concurrent_execution_stays_within_budget(self):
        t = build(cluster_budget=20)
        form(t, query={"kind": "hot"})
        cluster = next(iter(t.clusters.values()))

        def worker():
            for _ in range(25):
                t.execute("tomorrow", {"kind": "hot"}, generic=teacher, now=T)

        threads = [threading.Thread(target=worker) for _ in range(4)]
        [th.start() for th in threads]
        [th.join() for th in threads]
        self.assertLessEqual(cluster.used, cluster.budget)


if __name__ == "__main__":
    unittest.main()
