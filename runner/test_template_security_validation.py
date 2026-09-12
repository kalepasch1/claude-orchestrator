#!/usr/bin/env python3
"""
test_template_security_validation.py — access control on stored patch templates.

WHAT THIS FILE TESTS, AND WHAT IT USED TO
-----------------------------------------
There is no `template_security` module in this repo, and no role/allowlist auth
layer for templates anywhere in it: no `check_template_authorization`, no
`get_user_role`, no per-role template allowlist. The generated suite that used to
live here invented that API, patched it by bare name — `patch("get_template")`,
which unittest.mock rejects because it is not an importable target — and defined
its own stub `get_template()` (returning None unconditionally) at the bottom of
the file. All 38 failures were `Need a valid target to patch` / "not enough
values to unpack"; the five that passed asserted things about local dicts. The
file tested itself and never imported product code at all.

The real owner of "resolve stored template data from a template id" is
`runner/patch_templates.py`:

  * `lookup(template_id)` — the only id-gated read. The gate is the id itself and
    the effective allowlist is the set of ids actually stored (local JSONL store,
    then the knowledge table); anything else resolves to `{}`.
  * `find_template(slug)` — the same resolution keyed by task slug, used by
    dependency recovery, which additionally decides whether a hit is APPLICABLE
    (carries a `diff`).

So the original themes map onto real behaviour: (A/H) id gating and isolation
from unlisted templates, (C) a growing store not widening access, (D) preserved
resolution behaviour, (E) fail-soft on missing/corrupt/unreadable stores and DB
outages, (F) a denied lookup disclosing nothing, (G) concurrent resolution, and
(I) null/empty/traversal inputs. The role/authorization framing has no product
behind it and could not survive; each substitution is named on the test.

This complements `runner/test_patch_templates_security.py`, which covers id
generation, build(), _store(), inject_prompt() and pre_claim_hook() but never
exercises the resolution path tested here.

No test here touches the network: `db.select`/`db.insert` are patched in setUp to
raise, and the JSONL store is redirected to a temp directory.
"""
import contextlib
import json
import logging
import os
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import patch_templates


class _RecordCollector(logging.Handler):
    """Keeps every record a logger emits, for no_logs() below."""

    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.records = []

    def emit(self, record):
        self.records.append(record)


@contextlib.contextmanager
def no_logs(logger_name, level="DEBUG"):
    """Assert the named logger emits nothing at LEVEL or above. Py3.9-safe.

    `unittest.TestCase.assertNoLogs` landed in Python 3.10. This repo runs on
    3.9 — the interpreter the suite is invoked with — so the one test that
    reached for it did not fail an assertion, it raised AttributeError on the
    TestCase itself, and had done so on every interpreter this project has ever
    used. The behaviour under test (a denied lookup must not narrate the store)
    is real and worth keeping, so capture the records directly instead: same
    check, no version floor.
    """
    logger = logging.getLogger(logger_name)
    collector = _RecordCollector()
    prior_level = logger.level
    logger.addHandler(collector)
    logger.setLevel(getattr(logging, level))
    try:
        yield collector
    finally:
        logger.removeHandler(collector)
        logger.setLevel(prior_level)
    if collector.records:
        raise AssertionError(
            "%s emitted %d record(s) at %s or above, expected none: %s"
            % (logger_name, len(collector.records), level,
               [r.getMessage() for r in collector.records])
        )


def _body_for(tid, note="scaffold"):
    """A stored template body in the real format build() writes."""
    return f"PATCH TEMPLATE {tid}\nIntent: {note}\nAcceptance: preserve existing behavior."


class TemplateStoreCase(unittest.TestCase):
    """Base case: hermetic JSONL store, no DB, no network."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store_path = os.path.join(self._tmp.name, "patch_templates.jsonl")

        self._start(patch.object(patch_templates, "_fallback_path", lambda: self.store_path))

        # Offline by default; individual tests opt into a fake DB response.
        self.select = self._start(
            patch.object(patch_templates.db, "select",
                         side_effect=RuntimeError("db unavailable in tests"))
        )
        self.insert = self._start(
            patch.object(patch_templates.db, "insert",
                         side_effect=RuntimeError("db unavailable in tests"))
        )

    def _start(self, patcher):
        """Start a patcher and guarantee its own removal (never patch.stopall,
        which would also tear down patchers this case did not start)."""
        mocked = patcher.start()
        self.addCleanup(patcher.stop)
        return mocked

    def store(self, *rows):
        """Append rows to the JSONL template store, oldest first."""
        with open(self.store_path, "a") as handle:
            for row in rows:
                handle.write(json.dumps(row) + "\n")

    def store_template(self, tid, task=None, body=None):
        self.store({"ts": 1.0, "task": task or f"task-{tid}", "template_id": tid,
                    "body": body if body is not None else _body_for(tid)})


class TestTemplateIdGatesResolution(TemplateStoreCase):
    """A) The template id is the gate; H) unlisted ids get nothing."""

    def test_stored_id_resolves_to_its_own_template(self):
        self.store_template("aaaaaaaaaaaa")
        result = patch_templates.lookup("aaaaaaaaaaaa")
        self.assertEqual(result["template_id"], "aaaaaaaaaaaa")
        self.assertIn("PATCH TEMPLATE aaaaaaaaaaaa", result["body"])

    def test_id_that_was_never_stored_resolves_to_nothing(self):
        """Substitution for the removed 'guest role has empty allowlist': the
        stored id set IS the allowlist, so an unlisted id is the denial case."""
        self.store_template("aaaaaaaaaaaa")
        self.assertEqual(patch_templates.lookup("bbbbbbbbbbbb"), {})

    def test_none_id_is_denied(self):
        self.assertEqual(patch_templates.lookup(None), {})

    def test_empty_and_whitespace_ids_are_denied_without_reading_the_store(self):
        with patch("builtins.open", side_effect=AssertionError("store must not be opened")):
            for value in ("", "   ", "\t\n"):
                self.assertEqual(patch_templates.lookup(value), {}, repr(value))

    def test_non_string_ids_are_denied(self):
        self.store_template("aaaaaaaaaaaa")
        for value in (0, [], {}, False):
            self.assertEqual(patch_templates.lookup(value), {}, repr(value))

    def test_traversal_id_reads_only_the_fixed_store_path(self):
        """A hostile id must not steer the read: the store path is fixed."""
        self.store_template("aaaaaaaaaaaa")
        opened = []
        real_open = open

        def recording_open(path, *args, **kwargs):
            opened.append(path)
            return real_open(path, *args, **kwargs)

        with patch("builtins.open", recording_open):
            result = patch_templates.lookup("../../../etc/passwd")

        self.assertEqual(result, {})
        self.assertEqual(opened, [self.store_path])

    def test_lookup_strips_surrounding_whitespace_from_the_id(self):
        self.store_template("aaaaaaaaaaaa")
        self.assertEqual(patch_templates.lookup("  aaaaaaaaaaaa  ")["template_id"], "aaaaaaaaaaaa")


class TestNoCrossTemplateLeak(TemplateStoreCase):
    """H) Resolving id A must never hand back template B."""

    def test_jsonl_store_matches_ids_exactly_not_by_prefix(self):
        self.store_template("aaaaaaaaaaaabbbb")
        self.assertEqual(patch_templates.lookup("aaaaaaaaaaaa"), {})

    def test_db_row_for_another_template_is_not_returned_for_a_prefix_id(self):
        """Regression: `lookup` confirmed the DB hit with `tid in body`, and the
        query itself is a prefix filter, so a truncated id came back carrying a
        different task's template body relabelled with the id that was asked for.
        """
        self.select.side_effect = None
        self.select.return_value = [{"title": "patch template other",
                                     "body": _body_for("aaaaaaaaaaaabbbb", note="other task")}]
        self.assertEqual(patch_templates.lookup("aaaaaaaaaaaa"), {})

    def test_db_row_whose_header_names_the_requested_id_is_returned(self):
        self.select.side_effect = None
        self.select.return_value = [{"title": "patch template demo",
                                     "body": _body_for("aaaaaaaaaaaa")}]
        result = patch_templates.lookup("aaaaaaaaaaaa")
        self.assertEqual(result["template_id"], "aaaaaaaaaaaa")
        self.assertEqual(result["source"], "db")

    def test_id_mentioned_only_in_the_body_text_does_not_match(self):
        """The id must be declared in the header line, not merely mentioned."""
        self.select.side_effect = None
        self.select.return_value = [{
            "title": "patch template other",
            "body": _body_for("cccccccccccc", note="supersedes aaaaaaaaaaaa"),
        }]
        self.assertEqual(patch_templates.lookup("aaaaaaaaaaaa"), {})

    def test_newest_stored_entry_wins_for_a_repeated_id(self):
        self.store_template("aaaaaaaaaaaa", body=_body_for("aaaaaaaaaaaa", note="first"))
        self.store_template("aaaaaaaaaaaa", body=_body_for("aaaaaaaaaaaa", note="second"))
        self.assertIn("second", patch_templates.lookup("aaaaaaaaaaaa")["body"])

    def test_local_store_is_preferred_over_the_database(self):
        self.store_template("aaaaaaaaaaaa", body=_body_for("aaaaaaaaaaaa", note="local"))
        self.select.side_effect = None
        self.select.return_value = [{"title": "db", "body": _body_for("aaaaaaaaaaaa", note="remote")}]
        result = patch_templates.lookup("aaaaaaaaaaaa")
        self.assertIn("local", result["body"])
        self.assertNotIn("source", result)  # JSONL rows are returned verbatim


class TestStoreGrowthPreservesIsolation(TemplateStoreCase):
    """C) Adding template files must not widen what any other id can reach."""

    def test_appending_a_template_exposes_only_that_id(self):
        self.store_template("aaaaaaaaaaaa")
        before = {tid: patch_templates.lookup(tid) for tid in ("bbbbbbbbbbbb", "cccccccccccc")}
        self.assertEqual(before, {"bbbbbbbbbbbb": {}, "cccccccccccc": {}})

        self.store_template("bbbbbbbbbbbb")

        self.assertEqual(patch_templates.lookup("bbbbbbbbbbbb")["template_id"], "bbbbbbbbbbbb")
        self.assertEqual(patch_templates.lookup("cccccccccccc"), {})

    def test_existing_templates_still_resolve_after_the_store_grows(self):
        self.store_template("aaaaaaaaaaaa")
        first = patch_templates.lookup("aaaaaaaaaaaa")
        for tid in ("bbbbbbbbbbbb", "cccccccccccc", "dddddddddddd"):
            self.store_template(tid)
        self.assertEqual(patch_templates.lookup("aaaaaaaaaaaa"), first)

    def test_a_stored_row_without_an_id_is_never_reachable(self):
        self.store({"ts": 1.0, "task": "orphan", "body": _body_for("aaaaaaaaaaaa")})
        self.assertEqual(patch_templates.lookup("aaaaaaaaaaaa"), {})
        self.assertEqual(patch_templates.lookup(None), {})


class TestFailSoftOnMissingOrCorruptStore(TemplateStoreCase):
    """E) Missing/corrupt/unreadable stores and DB outages must not wedge."""

    def test_missing_store_file_resolves_to_nothing(self):
        self.assertFalse(os.path.exists(self.store_path))
        self.assertEqual(patch_templates.lookup("aaaaaaaaaaaa"), {})

    def test_corrupt_lines_are_skipped_and_valid_rows_still_resolve(self):
        with open(self.store_path, "w") as handle:
            handle.write("{not json at all\n")
            handle.write(json.dumps({"template_id": "aaaaaaaaaaaa",
                                     "body": _body_for("aaaaaaaaaaaa")}) + "\n")
            handle.write("]]truncated\n")
        self.assertEqual(patch_templates.lookup("aaaaaaaaaaaa")["template_id"], "aaaaaaaaaaaa")

    def test_non_object_rows_are_ignored(self):
        self.store([1, 2, 3], "aaaaaaaaaaaa", 42)
        self.store_template("aaaaaaaaaaaa")
        self.assertEqual(patch_templates.lookup("aaaaaaaaaaaa")["template_id"], "aaaaaaaaaaaa")

    def test_unreadable_store_resolves_to_nothing(self):
        self.store_template("aaaaaaaaaaaa")
        with patch("builtins.open", side_effect=PermissionError("denied")):
            self.assertEqual(patch_templates.lookup("aaaaaaaaaaaa"), {})

    def test_database_outage_resolves_to_nothing(self):
        self.select.side_effect = RuntimeError("control plane down")
        self.assertEqual(patch_templates.lookup("aaaaaaaaaaaa"), {})
        self.assertTrue(self.select.called)

    def test_malformed_database_rows_resolve_to_nothing(self):
        self.select.side_effect = None
        self.select.return_value = [None, {}, {"body": None}, {"body": 12345}]
        self.assertEqual(patch_templates.lookup("aaaaaaaaaaaa"), {})

    def test_hostile_ids_always_resolve_to_an_empty_mapping(self):
        self.store_template("aaaaaaaaaaaa")
        hostile = [
            "../../../etc/passwd",
            "aaaaaaaaaaaa\x00bbbb",
            "%2e%2e%2f",
            "*",
            "a" * 10000,
            "'; DROP TABLE knowledge; --",
            "aaaaaaaaaaaa,bbbbbbbbbbbb",
        ]
        for value in hostile:
            self.assertEqual(patch_templates.lookup(value), {}, repr(value[:40]))


class TestDeniedLookupDisclosesNothing(TemplateStoreCase):
    """F) A miss must return no content and must not narrate the store."""

    def test_denied_lookup_returns_no_body_and_logs_nothing(self):
        self.store_template("aaaaaaaaaaaa", body=_body_for("aaaaaaaaaaaa", note="secret intent"))
        with no_logs(patch_templates.log.name, level="DEBUG"):
            result = patch_templates.lookup("bbbbbbbbbbbb")
        self.assertEqual(result, {})

    def test_find_template_db_failure_logs_the_slug_but_no_template_content(self):
        """The one log line on this path names the slug (already in the task row)
        and must not carry the stored diff or body."""
        self.store({"ts": 1.0, "task": "widget-slug", "template_id": "aaaaaaaaaaaa",
                    "body": _body_for("aaaaaaaaaaaa", note="secret intent")})
        self.select.side_effect = RuntimeError("control plane down")

        with self.assertLogs(patch_templates.log.name, level="DEBUG") as captured:
            result = patch_templates.find_template("widget-slug")

        emitted = "\n".join(captured.output)
        self.assertIn("widget-slug", emitted)
        self.assertNotIn("secret intent", emitted)
        self.assertNotIn("PATCH TEMPLATE", emitted)
        # The JSONL fallback still answers the caller.
        self.assertEqual(result["template_id"], "aaaaaaaaaaaa")


class TestFindTemplateBySlug(TemplateStoreCase):
    """D) Slug-keyed resolution keeps its documented applicability contract."""

    def test_merged_diff_hit_is_applicable_and_carries_the_diff(self):
        self.select.side_effect = None
        self.select.return_value = [{"slug": "widget-slug", "project": "proj",
                                     "diff": "--- a\n+++ b\n", "files": ["a.py"]}]
        result = patch_templates.find_template("widget-slug")
        self.assertEqual(result["source"], "merged_diffs")
        self.assertEqual(result["diff"], "--- a\n+++ b\n")
        self.assertEqual(result["files"], ["a.py"])

    def test_merged_diff_row_with_an_empty_diff_is_not_applicable(self):
        """A row with no diff must fall through rather than hand callers a
        template whose `template.get("diff")` would `git apply` nothing."""
        self.select.side_effect = None
        self.select.return_value = [{"slug": "widget-slug", "diff": "   "}]
        self.assertEqual(patch_templates.find_template("widget-slug"), {})

    def test_jsonl_hit_carries_no_diff_key_so_callers_no_op(self):
        self.store({"ts": 1.0, "task": "widget-slug", "template_id": "aaaaaaaaaaaa",
                    "body": _body_for("aaaaaaaaaaaa")})
        result = patch_templates.find_template("widget-slug")
        self.assertEqual(result["source"], "jsonl")
        self.assertNotIn("diff", result)
        self.assertEqual(result["template_id"], "aaaaaaaaaaaa")

    def test_unknown_slug_resolves_to_nothing(self):
        self.store({"ts": 1.0, "task": "widget-slug", "template_id": "aaaaaaaaaaaa",
                    "body": _body_for("aaaaaaaaaaaa")})
        self.assertEqual(patch_templates.find_template("other-slug"), {})

    def test_empty_slug_is_denied_without_querying_anything(self):
        for value in (None, "", "   "):
            self.assertEqual(patch_templates.find_template(value), {}, repr(value))
        self.assertFalse(self.select.called)

    def test_slug_lookup_does_not_expose_another_slugs_template(self):
        self.store({"ts": 1.0, "task": "widget-slug", "template_id": "aaaaaaaaaaaa",
                    "body": _body_for("aaaaaaaaaaaa", note="widget intent")})
        self.store({"ts": 2.0, "task": "gadget-slug", "template_id": "bbbbbbbbbbbb",
                    "body": _body_for("bbbbbbbbbbbb", note="gadget intent")})
        self.assertIn("gadget intent", patch_templates.find_template("gadget-slug")["body"])
        self.assertIn("widget intent", patch_templates.find_template("widget-slug")["body"])


class TestConcurrentResolution(TemplateStoreCase):
    """G) Concurrent reads stay isolated and consistent."""

    def test_concurrent_lookups_each_get_their_own_template(self):
        ids = [f"{i:012d}" for i in range(10)]
        for tid in ids:
            self.store_template(tid, body=_body_for(tid, note=f"intent-{tid}"))

        results = {}
        lock = threading.Lock()

        def resolve(tid):
            row = patch_templates.lookup(tid)
            with lock:
                results[tid] = row

        threads = [threading.Thread(target=resolve, args=(tid,)) for tid in ids]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(len(results), len(ids))
        for tid in ids:
            self.assertEqual(results[tid]["template_id"], tid)
            self.assertIn(f"intent-{tid}", results[tid]["body"])

    def test_concurrent_unknown_ids_are_all_denied(self):
        self.store_template("aaaaaaaaaaaa")
        results = []
        lock = threading.Lock()

        def resolve(tid):
            row = patch_templates.lookup(tid)
            with lock:
                results.append(row)

        threads = [threading.Thread(target=resolve, args=(f"missing-{i}",)) for i in range(10)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(results, [{}] * 10)

    def test_readers_never_observe_a_partially_written_row(self):
        """Appends happen while readers scan; a torn last line must be skipped,
        never returned as a half-parsed template."""
        self.store_template("aaaaaaaaaaaa")
        stop = threading.Event()
        seen = []
        lock = threading.Lock()

        def writer():
            for i in range(50):
                if stop.is_set():
                    return
                with open(self.store_path, "a") as handle:
                    handle.write(json.dumps({"template_id": f"{i:012d}",
                                             "body": _body_for(f"{i:012d}")}))
                    handle.flush()
                    handle.write("\n")

        def reader():
            for _ in range(50):
                row = patch_templates.lookup("aaaaaaaaaaaa")
                with lock:
                    seen.append(row)

        writer_thread = threading.Thread(target=writer)
        reader_threads = [threading.Thread(target=reader) for _ in range(3)]
        writer_thread.start()
        for thread in reader_threads:
            thread.start()
        for thread in reader_threads:
            thread.join()
        stop.set()
        writer_thread.join()

        self.assertTrue(seen)
        for row in seen:
            self.assertEqual(row["template_id"], "aaaaaaaaaaaa")
            self.assertIn("PATCH TEMPLATE aaaaaaaaaaaa", row["body"])


class TestStoredTemplateRoundTrip(TemplateStoreCase):
    """D) What build()/_store() writes is exactly what lookup() gives back."""

    def test_stored_template_is_returned_unchanged(self):
        task = {"slug": "fix-auth-timeout", "project_id": "proj",
                "prompt": "Fix the authentication timeout in the session broker"}
        tid, body = patch_templates.build(task)
        patch_templates._store(task, tid, body)  # db.insert raises -> JSONL fallback

        result = patch_templates.lookup(tid)
        self.assertEqual(result["template_id"], tid)
        self.assertEqual(result["body"], body)
        self.assertEqual(result["task"], "fix-auth-timeout")

    def test_marker_id_in_the_injected_prompt_resolves_to_that_template(self):
        task = {"slug": "fix-auth-timeout",
                "prompt": "Fix the authentication timeout in the session broker"}
        tid, body = patch_templates.build(task)
        patch_templates._store(task, tid, body)

        prompt = patch_templates.inject_prompt(task)["prompt"]
        marked = prompt.split(patch_templates.MARK, 1)[1].split("]", 1)[0]
        self.assertEqual(marked, tid)
        self.assertEqual(patch_templates.lookup(marked)["body"], body)

    def test_a_different_task_does_not_resolve_to_the_stored_template(self):
        task = {"slug": "fix-auth-timeout",
                "prompt": "Fix the authentication timeout in the session broker"}
        tid, body = patch_templates.build(task)
        patch_templates._store(task, tid, body)

        other_tid, _ = patch_templates.build(
            {"slug": "unrelated-slug", "prompt": "Rewrite the billing export job"}
        )
        self.assertNotEqual(other_tid, tid)
        self.assertEqual(patch_templates.lookup(other_tid), {})


if __name__ == "__main__":
    unittest.main()
