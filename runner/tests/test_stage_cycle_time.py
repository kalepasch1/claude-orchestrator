#!/usr/bin/env python3
"""Tests for stage_cycle_time — percentile accuracy under a simulated load, and the
first-pass merge rate the routing rules are steered by."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import stage_cycle_time as sct


def _event(task, stage, at):
    return {"task_id": task, "stage": stage, "at": at}


class TestCoercion(unittest.TestCase):
    def test_canonical_stage_accepts_known_aliases(self):
        self.assertEqual(sct.canonical_stage("coder-done"), "coder_done")
        self.assertEqual(sct.canonical_stage("INTEGRATED"), "merged")
        self.assertEqual(sct.canonical_stage(" Running "), "claimed")

    def test_canonical_stage_maps_the_task_state_vocabulary(self):
        # These are the literal `workflow_outcome_contracts.to_state` values.
        self.assertEqual(sct.canonical_stage("QUEUED"), "queued")
        self.assertEqual(sct.canonical_stage("RUNNING"), "claimed")
        self.assertEqual(sct.canonical_stage("DONE"), "coder_done")
        self.assertEqual(sct.canonical_stage("TESTFAIL"), "qa")
        self.assertEqual(sct.canonical_stage("MERGED"), "merged")

    def test_canonical_stage_rejects_unknown_without_raising(self):
        for bad in ("nonsense", "", None, 7, [], {"a": 1}):
            self.assertEqual(sct.canonical_stage(bad), "")

    def test_parse_ts_handles_z_suffix_and_epoch(self):
        z = sct.parse_ts("2026-08-13T00:00:00Z")
        offset = sct.parse_ts("2026-08-13T00:00:00+00:00")
        self.assertIsNotNone(z)
        self.assertEqual(z, offset)
        self.assertEqual(sct.parse_ts(1700000000), 1700000000.0)

    def test_parse_ts_returns_none_for_junk(self):
        for bad in ("not-a-date", "", None, True, object()):
            self.assertIsNone(sct.parse_ts(bad))


class TestPercentile(unittest.TestCase):
    def test_nearest_rank_returns_an_observed_value(self):
        values = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
        self.assertIn(sct.percentile(values, 0.50), values)
        self.assertIn(sct.percentile(values, 0.90), values)

    def test_percentile_ordering_holds_under_simulated_load(self):
        # 1000 durations, heavy right tail — p50 must stay well under p90. 20% of the
        # sample is slow, so the p90 must land in the tail and the p50 must not.
        values = [1.0] * 800 + [600.0] * 200
        self.assertLess(sct.percentile(values, 0.50), sct.percentile(values, 0.90))
        self.assertEqual(sct.percentile(values, 0.50), 1.0)
        self.assertEqual(sct.percentile(values, 0.90), 600.0)

    def test_percentile_of_empty_sample_is_none(self):
        self.assertIsNone(sct.percentile([], 0.5))
        self.assertIsNone(sct.percentile([None, "x", True], 0.5))


class TestStageDurations(unittest.TestCase):
    def test_consecutive_stages_produce_transition_spans(self):
        events = [
            _event("t1", "queued", 0),
            _event("t1", "claimed", 10),
            _event("t1", "coder_done", 40),
            _event("t1", "qa", 50),
            _event("t1", "merged", 90),
            _event("t1", "released", 100),
        ]
        spans = sct.stage_durations(events)["t1"]
        self.assertEqual(spans["queued->claimed"], 10)
        self.assertEqual(spans["claimed->coder_done"], 30)
        self.assertEqual(spans["qa->merged"], 40)
        self.assertEqual(spans["merged->released"], 10)

    def test_missing_endpoint_is_absent_not_zero(self):
        spans = sct.stage_durations([_event("t1", "queued", 0), _event("t1", "qa", 50)])
        self.assertNotIn("queued->claimed", spans.get("t1", {}))

    def test_earliest_timestamp_wins_for_a_repeated_stage(self):
        events = [
            _event("t1", "queued", 0),
            _event("t1", "claimed", 30),
            _event("t1", "claimed", 5),  # retry recorded later, happened earlier
        ]
        self.assertEqual(sct.stage_durations(events)["t1"]["queued->claimed"], 5)

    def test_negative_span_from_clock_skew_is_dropped(self):
        events = [_event("t1", "queued", 100), _event("t1", "claimed", 10)]
        self.assertEqual(sct.stage_durations(events), {})

    def test_malformed_rows_never_raise(self):
        self.assertEqual(sct.stage_durations([None, 5, {}, {"stage": "qa"}]), {})
        self.assertEqual(sct.stage_durations(None), {})


class TestFirstPassMergeRate(unittest.TestCase):
    def test_counts_only_merges_on_the_first_attempt(self):
        rows = [{"integrated": True, "attempts": 1} for _ in range(3)]
        rows += [{"integrated": True, "attempts": 4} for _ in range(3)]
        rows += [{"integrated": False, "attempts": 1} for _ in range(4)]
        self.assertEqual(sct.first_pass_merge_rate(rows), 0.3)

    def test_denominator_includes_tasks_that_never_merged(self):
        # The "0/12 merged" shape: one merge, eleven failures. Must NOT read as 1.0.
        rows = [{"integrated": True, "attempts": 1}]
        rows += [{"integrated": False, "attempts": 3} for _ in range(11)]
        self.assertAlmostEqual(sct.first_pass_merge_rate(rows), 1 / 12, places=4)

    def test_thin_sample_reports_none_not_zero(self):
        self.assertIsNone(sct.first_pass_merge_rate([{"integrated": True, "attempts": 1}]))

    def test_merged_state_string_counts_as_merged(self):
        rows = [{"state": "MERGED", "attempts": 1} for _ in range(sct.MIN_SAMPLES)]
        self.assertEqual(sct.first_pass_merge_rate(rows), 1.0)


class TestReport(unittest.TestCase):
    def _rows(self, n, project, model, merged, attempts):
        return [{"task_id": "{}-{}-{}".format(project, model, i), "project": project,
                 "model": model, "integrated": merged, "attempts": attempts}
                for i in range(n)]

    def test_groups_by_project_and_by_route(self):
        rows = self._rows(6, "beethoven", "claude", True, 1)
        rows += self._rows(6, "tomorrow", "local:qwen", False, 3)
        rep = sct.report(rows)
        self.assertEqual(rep["by_project"]["beethoven"]["first_pass_merge_rate"], 1.0)
        self.assertEqual(rep["by_route"]["local:qwen"]["first_pass_merge_rate"], 0.0)
        self.assertEqual(rep["tasks_observed"], 12)

    def test_weak_route_is_distinguishable_from_strong_route(self):
        rows = self._rows(12, "beethoven", "claude", True, 1)
        rows += self._rows(12, "beethoven", "ollama", False, 4)
        rep = sct.report(rows)
        strong = rep["by_route"]["claude"]["first_pass_merge_rate"]
        weak = rep["by_route"]["ollama"]["first_pass_merge_rate"]
        self.assertGreater(strong, weak)

    def test_percentiles_appear_per_transition_when_events_supplied(self):
        rows = [{"task_id": "t%d" % i, "project": "beethoven", "model": "claude",
                 "integrated": True, "attempts": 1} for i in range(6)]
        events = []
        for i in range(6):
            events.append(_event("t%d" % i, "queued", 0))
            events.append(_event("t%d" % i, "claimed", 10 * (i + 1)))
        stages = sct.report(rows, events)["by_route"]["claude"]["stages"]
        self.assertEqual(stages["queued->claimed"]["n"], 6)
        self.assertIsNotNone(stages["queued->claimed"]["p50_s"])
        self.assertLessEqual(stages["queued->claimed"]["p50_s"],
                             stages["queued->claimed"]["p90_s"])

    def test_thin_stage_sample_reports_none_percentiles(self):
        rows = [{"task_id": "t1", "project": "p", "model": "m",
                 "integrated": True, "attempts": 1}]
        events = [_event("t1", "queued", 0), _event("t1", "claimed", 10)]
        stages = sct.report(rows, events)["by_route"]["m"]["stages"]
        self.assertEqual(stages["queued->claimed"]["n"], 1)
        self.assertIsNone(stages["queued->claimed"]["p50_s"])

    def test_report_is_total_on_garbage_input(self):
        rep = sct.report([None, 3, "x", {}])
        self.assertEqual(rep["tasks_observed"], 1)  # only {} is a dict
        self.assertIsNone(rep["first_pass_merge_rate"])
        self.assertEqual(sct.report(None)["tasks_observed"], 0)

    def test_transitions_cover_the_whole_pipeline(self):
        self.assertEqual(
            sct.report([])["transitions"],
            ["queued->claimed", "claimed->coder_done", "coder_done->qa",
             "qa->merged", "merged->released"],
        )


class _FakeDB:
    """Stands in for the `db` module so the recorder is testable without a live database."""

    def __init__(self, explode=False):
        self.rows = []
        self.explode = explode

    def insert(self, table, row, upsert=False):
        if self.explode:
            raise RuntimeError("simulated DB outage")
        self.rows.append((table, row))
        return row


class TestRecordTransition(unittest.TestCase):
    def setUp(self):
        self.fake = _FakeDB()
        self._real = sys.modules.get("db")
        sys.modules["db"] = self.fake

    def tearDown(self):
        if self._real is not None:
            sys.modules["db"] = self._real
        else:
            sys.modules.pop("db", None)

    def test_records_a_pipeline_state(self):
        self.assertTrue(sct.record_transition("task-1", "RUNNING", project_id="proj-1"))
        table, row = self.fake.rows[0]
        self.assertEqual(table, "workflow_outcome_contracts")
        self.assertEqual(row["to_state"], "RUNNING")
        self.assertEqual(row["stage"], "claimed")
        self.assertEqual(row["task_id"], "task-1")
        self.assertTrue(row["transition_key"].startswith("state:task-1:RUNNING:"))

    def test_ignores_states_outside_the_pipeline(self):
        self.assertFalse(sct.record_transition("task-1", "SUPERSEDED"))
        self.assertFalse(sct.record_transition("task-1", ""))
        self.assertFalse(sct.record_transition(None, "RUNNING"))
        self.assertEqual(self.fake.rows, [])

    def test_repeated_state_gets_a_distinct_key(self):
        sct.record_transition("task-1", "QUEUED")
        sct.record_transition("task-1", "QUEUED")
        keys = {row["transition_key"] for _, row in self.fake.rows}
        self.assertEqual(len(self.fake.rows), 2)
        self.assertEqual(len(keys), 2)

    def test_db_failure_is_swallowed(self):
        sys.modules["db"] = _FakeDB(explode=True)
        self.assertFalse(sct.record_transition("task-1", "MERGED"))

    def test_recorded_rows_feed_back_into_durations(self):
        # End to end on the pure side: what the recorder writes is what the reader parses.
        sct.record_transition("task-1", "QUEUED")
        sct.record_transition("task-1", "RUNNING")
        events = [{"task_id": r["task_id"], "stage": r["to_state"], "at": r["observed_at"]}
                  for _, r in self.fake.rows]
        spans = sct.stage_durations(events)
        self.assertIn("queued->claimed", spans["task-1"])
        self.assertGreaterEqual(spans["task-1"]["queued->claimed"], 0)


if __name__ == "__main__":
    unittest.main()
