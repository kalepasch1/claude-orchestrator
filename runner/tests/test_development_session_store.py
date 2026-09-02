#!/usr/bin/env python3
"""Durable development-session event + artifact store.

Proof command: python3 -m unittest runner.tests.test_development_session_store -v

The five cases the spec names are the five ways this kind of store is usually wrong:
concurrent append (a lost event that both writers report as written), duplicate delivery
(the same event twice because the transport is at-least-once), cursor replay (a page
boundary that drops or repeats a row), host loss (a stream nobody will ever append to
again that still looks live), and >1000 events (the PostgREST page cap turning a replay
into a silent truncation).

The fake store below ENFORCES the schema's unique constraints. That is the point: a fake
that accepts every insert would let the concurrency bug pass its own test, which is
exactly how this class of bug ships.
"""
import os
import sys
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import development_session_store as store_mod


class FakeStore:
    """In-memory store enforcing (session_id, seq) and (session_id, idempotency_key).

    Also honours the 1000-row response cap, so a test cannot pass by reading more rows
    in one page than the real database would ever return.
    """

    HARD_PAGE_CAP = 1000

    def __init__(self):
        self.tables = {store_mod.SESSIONS_TABLE: [], store_mod.EVENTS_TABLE: [],
                       store_mod.ARTIFACTS_TABLE: []}
        self.lock = threading.Lock()
        self.insert_conflicts = 0

    def insert(self, table, row):
        with self.lock:
            rows = self.tables.setdefault(table, [])
            if table == store_mod.EVENTS_TABLE:
                for existing in rows:
                    if existing["session_id"] != row["session_id"]:
                        continue
                    if existing["seq"] == row["seq"]:
                        self.insert_conflicts += 1
                        raise ValueError("duplicate key (session_id, seq)")
                    if existing["idempotency_key"] == row["idempotency_key"]:
                        self.insert_conflicts += 1
                        raise ValueError("duplicate key (session_id, idempotency_key)")
            if table == store_mod.ARTIFACTS_TABLE:
                for existing in rows:
                    if (existing["digest"] == row["digest"]
                            and existing["location"] == row["location"]):
                        raise ValueError("duplicate key (digest, location)")
            rows.append(dict(row))
            return [dict(row)]

    # -- PostgREST-shaped filtering -------------------------------------------------
    @staticmethod
    def _matches(row, key, expr):
        if not isinstance(expr, str) or "." not in expr:
            return True
        op, _, value = expr.partition(".")
        current = row.get(key)
        if op == "eq":
            return str(current) == value
        if op == "gt":
            return float(current or 0) > float(value)
        if op == "lt":
            return str(current or "") < value
        return True

    def select(self, table, params):
        with self.lock:
            rows = [dict(r) for r in self.tables.get(table, [])]
        for key, expr in (params or {}).items():
            if key in ("select", "order", "limit", "offset"):
                continue
            rows = [r for r in rows if self._matches(r, key, expr)]
        order = (params or {}).get("order")
        if order:
            field, _, direction = order.partition(".")
            rows.sort(key=lambda r: (r.get(field) is None, r.get(field)),
                      reverse=(direction == "desc"))
        limit = min(int((params or {}).get("limit") or self.HARD_PAGE_CAP),
                    self.HARD_PAGE_CAP)
        return rows[:limit]

    def update(self, table, match, patch):
        with self.lock:
            for row in self.tables.get(table, []):
                if all(str(row.get(k)) == str(v) for k, v in match.items()):
                    row.update(patch)
            return True

    def delete(self, table, match):
        with self.lock:
            before = len(self.tables.get(table, []))
            self.tables[table] = [
                r for r in self.tables.get(table, [])
                if not all(str(r.get(k)) == str(v) for k, v in match.items())]
            return before - len(self.tables[table])


class SessionTestCase(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()
        self.session = store_mod.start_session("slug-1", "mac-a", project="beethoven",
                                               store=self.store)
        self.sid = self.session["session_id"]


class TestConcurrentAppend(SessionTestCase):
    def test_parallel_appenders_lose_no_events_and_reuse_no_ordinal(self):
        """The failure this guards: two writers read last_seq=7 and both write 8.

        Both report success and one event is gone. The (session_id, seq) constraint makes
        the loser fail and retry, so the count is exact and the ordinals are dense.
        """
        errors = []

        def worker(n):
            try:
                for i in range(10):
                    store_mod.append_event(self.sid, "tick", {"w": n, "i": i},
                                           store=self.store)
            except Exception as exc:  # surfaced, never swallowed
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(n,)) for n in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [])
        events = self.store.tables[store_mod.EVENTS_TABLE]
        self.assertEqual(len(events), 60, "an event was lost or duplicated")
        seqs = sorted(e["seq"] for e in events)
        self.assertEqual(seqs, list(range(1, 61)), "ordinals must be dense and unique")

    def test_the_race_actually_happened(self):
        """The fake really does reject a duplicate ordinal — proven, not hoped for.

        This used to start four threads and assert insert_conflicts > 0. The
        intent is right: if the fake never rejects anything, the concurrency test
        above proves nothing. But whether two of those threads actually collide is
        up to the scheduler, and on a loaded machine they serialise — so the test
        passed on an idle box and failed in a full-suite run, which is the one
        environment where it needs to be trustworthy.

        The constraint is asserted directly instead: hand the store two rows with
        the same (session_id, seq) and require it to refuse the second. That is
        the property the sibling test depends on, and it holds regardless of
        timing.
        """
        row = {"session_id": self.sid, "seq": 1, "idempotency_key": "k-a",
               "kind": "tick", "payload": {}}
        self.store.insert(store_mod.EVENTS_TABLE, row)
        with self.assertRaises(ValueError):
            self.store.insert(store_mod.EVENTS_TABLE, dict(row, idempotency_key="k-b"))
        self.assertGreater(self.store.insert_conflicts, 0,
                           "the fake accepted a duplicate ordinal; the concurrency "
                           "test above would be vacuous")
        # The duplicate idempotency key is the other half of the same guarantee.
        with self.assertRaises(ValueError):
            self.store.insert(store_mod.EVENTS_TABLE, dict(row, seq=2))

    def test_contention_is_observed_when_the_scheduler_allows_it(self):
        """Best-effort observation of real interleaving. Never the only evidence.

        Kept because seeing genuine contention is worth something, but it cannot
        be asserted: four threads on a busy machine may run one after another and
        collide zero times. The deterministic guarantee lives in the test above.
        """
        threads = [
            threading.Thread(target=lambda n=n: [
                store_mod.append_event(self.sid, "tick", {"w": n, "i": i},
                                       store=self.store) for i in range(8)])
            for n in range(4)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
            self.assertFalse(t.is_alive(), "an appender thread never finished")

        events = self.store.tables[store_mod.EVENTS_TABLE]
        self.assertEqual(len(events), 32, "an event was lost or duplicated")
        self.assertEqual(sorted(e["seq"] for e in events), list(range(1, 33)),
                         "ordinals must be dense and unique whether or not threads raced")


class TestDuplicateDelivery(SessionTestCase):
    def test_same_idempotency_key_is_absorbed(self):
        first = store_mod.append_event(self.sid, "build", {"ok": True},
                                       idempotency_key="k-1", store=self.store)
        second = store_mod.append_event(self.sid, "build", {"ok": True},
                                        idempotency_key="k-1", store=self.store)
        self.assertEqual(first["event_id"], second["event_id"])
        self.assertEqual(len(self.store.tables[store_mod.EVENTS_TABLE]), 1)

    def test_identical_payloads_dedupe_without_an_explicit_key(self):
        # The default key is a content digest, so an at-least-once transport that
        # redelivers a byte-identical event does not append it twice.
        store_mod.append_event(self.sid, "build", {"ok": True}, store=self.store)
        store_mod.append_event(self.sid, "build", {"ok": True}, store=self.store)
        self.assertEqual(len(self.store.tables[store_mod.EVENTS_TABLE]), 1)

    def test_different_payloads_are_distinct_events(self):
        store_mod.append_event(self.sid, "build", {"ok": True}, store=self.store)
        store_mod.append_event(self.sid, "build", {"ok": False}, store=self.store)
        self.assertEqual(len(self.store.tables[store_mod.EVENTS_TABLE]), 2)

    def test_the_same_key_in_another_session_is_a_separate_event(self):
        other = store_mod.start_session("slug-2", "mac-a", store=self.store)
        store_mod.append_event(self.sid, "build", {"a": 1}, idempotency_key="k",
                               store=self.store)
        store_mod.append_event(other["session_id"], "build", {"a": 1},
                               idempotency_key="k", store=self.store)
        self.assertEqual(len(self.store.tables[store_mod.EVENTS_TABLE]), 2)


class TestCursorReplay(SessionTestCase):
    def _fill(self, n):
        for i in range(n):
            store_mod.append_event(self.sid, "tick", {"i": i}, store=self.store)

    def test_pages_are_contiguous_with_no_gap_or_overlap(self):
        self._fill(25)
        seen, cursor = [], 0
        while True:
            page = store_mod.read_events(self.sid, after_seq=cursor, limit=10,
                                         store=self.store)
            seen.extend(e["seq"] for e in page["events"])
            if not page["has_more"]:
                break
            cursor = page["next_cursor"]
        self.assertEqual(seen, list(range(1, 26)))

    def test_replay_yields_every_event_in_order(self):
        self._fill(30)
        self.assertEqual([e["seq"] for e in store_mod.replay(self.sid, store=self.store)],
                         list(range(1, 31)))

    def test_replay_can_start_after_a_cursor(self):
        self._fill(10)
        self.assertEqual([e["seq"] for e in store_mod.replay(self.sid, after_seq=7,
                                                             store=self.store)],
                         [8, 9, 10])

    def test_end_of_stream_reports_no_cursor(self):
        self._fill(3)
        page = store_mod.read_events(self.sid, after_seq=0, limit=10, store=self.store)
        self.assertFalse(page["has_more"])
        self.assertIsNone(page["next_cursor"])

    def test_empty_session_is_not_an_error(self):
        page = store_mod.read_events(self.sid, store=self.store)
        self.assertEqual(page["events"], [])
        self.assertIsNone(page["next_cursor"])


class TestLargeStream(SessionTestCase):
    def test_more_than_1000_events_replay_completely(self):
        """The PostgREST cap is 1000 rows per response regardless of `limit`.

        A replay that issues one big read silently stops at 1000 and looks complete. The
        fake enforces the same cap so this test can actually fail.
        """
        for i in range(1205):
            store_mod.append_event(self.sid, "tick", {"i": i}, store=self.store)
        seqs = [e["seq"] for e in store_mod.replay(self.sid, store=self.store)]
        self.assertEqual(len(seqs), 1205)
        self.assertEqual(seqs, list(range(1, 1206)))

    def test_a_single_page_cannot_exceed_the_cap(self):
        for i in range(1205):
            store_mod.append_event(self.sid, "tick", {"i": i}, store=self.store)
        page = store_mod.read_events(self.sid, limit=5000, store=self.store)
        self.assertLessEqual(len(page["events"]), FakeStore.HARD_PAGE_CAP)
        self.assertTrue(page["has_more"])


class TestHostLoss(SessionTestCase):
    def test_lost_host_sessions_are_reclaimed(self):
        store_mod.append_event(self.sid, "start", {}, store=self.store)
        reclaimed = store_mod.reclaim_lost_sessions("mac-a", store=self.store)
        self.assertIn(self.sid, reclaimed)
        self.assertEqual(store_mod.get_session(self.sid, store=self.store)["status"],
                         "abandoned")

    def test_another_hosts_sessions_are_untouched(self):
        other = store_mod.start_session("slug-3", "mac-b", store=self.store)
        store_mod.reclaim_lost_sessions("mac-a", store=self.store)
        self.assertEqual(
            store_mod.get_session(other["session_id"], store=self.store)["status"],
            "active")

    def test_resume_keeps_history_and_reports_where_to_continue(self):
        for i in range(5):
            store_mod.append_event(self.sid, "tick", {"i": i}, store=self.store)
        store_mod.reclaim_lost_sessions("mac-a", store=self.store)
        resumed = store_mod.resume(self.sid, "mac-b", generation=7, store=self.store)
        self.assertEqual(resumed["resume_after"], 5)
        self.assertEqual(resumed["session"]["status"], "active")
        self.assertEqual(resumed["session"]["host"], "mac-b")
        self.assertEqual(resumed["session"]["generation"], 7)
        # History survives, and the next append continues the ordinal.
        nxt = store_mod.append_event(self.sid, "tick", {"i": 99}, store=self.store)
        self.assertEqual(nxt["seq"], 6)

    def test_resume_of_an_unknown_session_is_loud(self):
        with self.assertRaises(store_mod.DurabilityError):
            store_mod.resume("no-such-session", "mac-b", store=self.store)


class TestDurableLocations(SessionTestCase):
    def test_local_paths_are_refused(self):
        for bad in ("/Users/kp/.runtime/artifacts/x.json", "./x.json",
                    "artifacts/x.json", "", "   "):
            with self.subTest(location=bad):
                with self.assertRaises(store_mod.DurabilityError):
                    store_mod.record_artifact("deadbeef", bad, store=self.store)

    def test_durable_locations_are_accepted_and_classified(self):
        cases = {"refs/artifacts/abc": "git_ref", "git:refs/x": "git_ref",
                 "s3://bucket/key": "object_store", "https://host/x": "url"}
        for location, kind in cases.items():
            with self.subTest(location=location):
                row = store_mod.record_artifact(
                    store_mod.digest_bytes(location.encode()), location,
                    store=self.store)
                self.assertEqual(row["location_kind"], kind)

    def test_provenance_is_recorded(self):
        row = store_mod.record_artifact(
            "d1", "refs/artifacts/d1", media_type="text/x-diff",
            session_id=self.sid, slug="slug-1", task_id="t-1", commit_sha="abc123",
            adapter="claude", runner_host="mac-a", generation=4, byte_size=42,
            store=self.store)
        for field, value in (("adapter", "claude"), ("runner_host", "mac-a"),
                             ("generation", 4), ("task_id", "t-1"),
                             ("commit_sha", "abc123"), ("media_type", "text/x-diff"),
                             ("byte_size", 42)):
            self.assertEqual(row[field], value)

    def test_redelivered_artifact_returns_the_existing_row(self):
        first = store_mod.record_artifact("d2", "refs/artifacts/d2", store=self.store)
        second = store_mod.record_artifact("d2", "refs/artifacts/d2", store=self.store)
        self.assertEqual(first["artifact_id"], second["artifact_id"])
        self.assertEqual(len(self.store.tables[store_mod.ARTIFACTS_TABLE]), 1)


class TestRedaction(SessionTestCase):
    def test_secrets_are_redacted_by_key_and_by_shape(self):
        event = store_mod.append_event(self.sid, "env", {
            "GITHUB_PAT": "ghp_" + "a" * 30,
            "note": "token is sk-" + "b" * 30,
            "safe": "hello",
        }, store=self.store)
        self.assertEqual(event["payload"]["GITHUB_PAT"], store_mod.REDACTED)
        self.assertEqual(event["payload"]["note"], store_mod.REDACTED)
        self.assertEqual(event["payload"]["safe"], "hello")
        self.assertTrue(event["redacted"])
        self.assertNotIn("ghp_", str(self.store.tables[store_mod.EVENTS_TABLE]))

    def test_nested_structures_are_redacted(self):
        out = store_mod.redact({"a": [{"api_key": "x"}, {"ok": 1}]})
        self.assertEqual(out["a"][0]["api_key"], store_mod.REDACTED)
        self.assertEqual(out["a"][1]["ok"], 1)

    def test_redaction_does_not_mutate_the_callers_payload(self):
        payload = {"TOKEN": "secret"}
        store_mod.redact(payload)
        self.assertEqual(payload["TOKEN"], "secret")

    def test_clean_payloads_are_not_marked_redacted(self):
        event = store_mod.append_event(self.sid, "ok", {"n": 1}, store=self.store)
        self.assertFalse(event["redacted"])


class TestRetention(SessionTestCase):
    def test_old_events_are_pruned_and_recent_ones_kept(self):
        store_mod.append_event(self.sid, "recent", {"i": 1}, store=self.store)
        old = dict(self.store.tables[store_mod.EVENTS_TABLE][0])
        old.update({"event_id": "old-1", "seq": 2, "idempotency_key": "old",
                    "created_at": "2000-01-01T00:00:00+00:00"})
        self.store.tables[store_mod.EVENTS_TABLE].append(old)
        self.assertEqual(store_mod.prune_events(older_than_days=30, store=self.store), 1)
        remaining = [e["event_id"] for e in self.store.tables[store_mod.EVENTS_TABLE]]
        self.assertNotIn("old-1", remaining)

    def test_zero_retention_is_a_no_op_not_a_purge(self):
        store_mod.append_event(self.sid, "x", {}, store=self.store)
        self.assertEqual(store_mod.prune_events(older_than_days=0, store=self.store), 0)
        self.assertEqual(len(self.store.tables[store_mod.EVENTS_TABLE]), 1)


class TestTaskArtifactsCompat(SessionTestCase):
    def test_published_ref_is_recorded_as_durable(self):
        result = store_mod.capture_compat("slug-1", {
            "artifact_ref": "refs/artifacts/task/1", "patch_id": "p1",
            "commit_sha": "abc", "patch_diff": "diff --git a b", "diff_bytes": 14,
        }, session_id=self.sid, host="mac-a", store=self.store)
        self.assertIsNone(result["skipped"])
        self.assertEqual(result["artifact"]["location"], "refs/artifacts/task/1")
        self.assertEqual(result["artifact"]["media_type"], "text/x-diff")

    def test_missing_ref_is_skipped_explicitly_not_silently(self):
        # The old store's failure mode was a write that reported success while landing
        # on local disk. "Nothing to record" must be distinguishable from "recorded".
        result = store_mod.capture_compat("slug-1", {"patch_diff": "x"},
                                          store=self.store)
        self.assertIsNone(result["artifact"])
        self.assertIn("artifact_ref", result["skipped"])


class TestNoSilentLocalFallback(SessionTestCase):
    def test_a_failing_store_raises_instead_of_writing_to_disk(self):
        """The defect this module was built to remove.

        task_artifacts catches the DB error and writes .runtime/artifacts/<slug>.json,
        then returns normally — so a release-critical record can exist on one sleeping
        laptop and every caller believes it is safe.
        """
        class Broken(FakeStore):
            def insert(self, table, row):
                raise RuntimeError("database unreachable")

        broken = Broken()
        with self.assertRaises(store_mod.DurabilityError):
            store_mod.start_session("slug-x", "mac-a", store=broken)
        with self.assertRaises(store_mod.DurabilityError):
            store_mod.record_artifact("d", "refs/artifacts/d", store=broken)

    def test_module_contains_no_local_write_path(self):
        """Structural, not textual: the module must not open a file for writing.

        Checked on the AST rather than the source text, because the docstring legitimately
        DISCUSSES `.runtime/artifacts` — grepping the text flags the explanation of the
        bug as if it were the bug.
        """
        import ast
        import inspect
        tree = ast.parse(inspect.getsource(store_mod))
        offenders = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if name == "open":
                offenders.append(f"open() at line {node.lineno}")
            if name in ("dump",) and getattr(
                    getattr(node.func, "value", None), "id", "") == "json":
                offenders.append(f"json.dump() at line {node.lineno}")
            if name in ("makedirs", "mkdir"):
                offenders.append(f"{name}() at line {node.lineno}")
        self.assertEqual(offenders, [],
                         f"module writes to local disk: {offenders}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
