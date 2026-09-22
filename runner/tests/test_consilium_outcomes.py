"""Hermetic outcome receipts. These tests do not execute any Consilium job."""
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch

admission_spec = importlib.util.spec_from_file_location(
    "consilium_admission_test_harness", Path(__file__).with_name("test_consilium_resource_admission.py"))
admission_tests = importlib.util.module_from_spec(admission_spec)
admission_spec.loader.exec_module(admission_tests)

SOURCE = Path(__file__).resolve().parents[1] / "consilium_outcomes.py"
spec = importlib.util.spec_from_file_location("outcomes_under_test", SOURCE)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
classify = module.classify_outcome


class OutcomeParsingTest(unittest.TestCase):
    def test_zero_exit_is_not_proof_of_work_or_absorption(self):
        for job, stdout in (("new_job", '{"drafted":9}'), ("paper_drafter", "completed")):
            result = classify(job, stdout, 0)
            self.assertEqual(result["status"], "unverified")
            self.assertTrue(result["execution_success"])
            self.assertEqual(result["absorption"], "unverified")
            self.assertEqual(result["value"], "unverified")

    def test_all_known_job_summaries(self):
        examples = {
            "legal_docket": {"cards_minted": 1, "seeded": 0, "convened": 1},
            "publication_commission": {"reviewed": 1},
            "paper_drafter": {"drafted": 1, "candidates": 1},
            "expert_corps": {"claims": 1, "researched": 1},
            "corpus_forecaster": {"added": 1},
            "theory_lab": {"positions": {"resolved": 1, "groups": 1}, "claims": {"checked": 0}},
            "ambiguity_miner": {"docketed": 1, "docs": 1},
            "reg_opportunity_scan": {"opportunities": 1, "docketed": 0},
            "card_freshness": {"stale_marked": 1, "dry_run": False},
            "benchmark_ingest": {"ingested": 1, "considered": 1},
            "corpus_index": {"added": 1, "skipped": 0},
        }
        for job, summary in examples.items():
            with self.subTest(job=job):
                result = classify(job, "log before\n" + json.dumps(summary, indent=2), 0)
                self.assertIn(result["status"], ("produced", "work_done"))
                self.assertEqual(result["absorption"], "unverified")

    def test_skip_and_unavailability_are_deferred_even_at_zero_exit(self):
        for job, summary in (
            ("paper_drafter", {"drafted": 0, "skipped": "frontier unavailable"}),
            ("legal_docket", {"cards_minted": 1, "left_pending": 2}),
            ("theory_lab", {"positions": {"resolved": 0, "skipped": "frontier unavailable"}}),
            ("benchmark_ingest", {"ingested": 0, "skipped_budget": 1}),
            ("publication_commission", {"reviewed": 0, "deferred": 1}),
            ("ambiguity_miner", {"docs": 0, "status": "deferred"}),
            ("legal_docket", {"skipped": "legal_docket already running"}),
        ):
            result = classify(job, json.dumps(summary), 0)
            self.assertEqual(result["status"], "deferred")
            self.assertTrue(result["deferred"])
        self.assertTrue(classify("legal_docket", '{"cards_minted":1,"left_pending":2}', 0)["partial"])

    def test_reported_errors_are_not_hidden_by_zero_exit(self):
        for extra in ({"errors": ["corpus_read_failed"]}, {"error": "private content"}, {"status": "failed"}):
            result = classify("ambiguity_miner", json.dumps({"docs": 1, **extra}), 0)
            self.assertEqual(result["status"], "failed")
            self.assertTrue(result["deferred"])
            self.assertNotIn("private content", json.dumps(result))
        result = classify("publication_commission", '{"reviewed":1,"persist_failed":1}', 0)
        self.assertEqual(result["status"], "failed")
        self.assertTrue(result["deferred"])
        self.assertTrue(result["partial"])

    def test_genuine_no_work_and_dry_run_not_productive(self):
        for job, summary in (("paper_drafter", {"drafted": 0, "candidates": 0}),
                             ("reg_opportunity_scan", {"skipped": "already ran today"}),
                             ("card_freshness", {"stale_marked": 0, "scanned_cards": 10}),
                             ("card_freshness", {"stale_marked": 1, "dry_run": True})):
            self.assertEqual(classify(job, json.dumps(summary), 0)["status"], "no_work")
        self.assertEqual(classify("paper_drafter", '{"drafted":0,"candidates":2}', 0)["status"], "unverified")

    def test_bounds_invalid_counts_nested_payloads_and_private_data(self):
        for value in (True, -1, 1.5, "4", 1000000001):
            self.assertEqual(classify("paper_drafter", json.dumps({"drafted": value}), 0)["status"], "unverified")
        for stdout in ('{"results":[{"drafted":9}]}', 'log {"drafted":9}', '{"drafted":9',
                       '{"drafted":9}\n' + "x" * 70000):
            self.assertEqual(classify("paper_drafter", stdout, 0)["status"], "unverified")
        result = classify("paper_drafter", 'paper_drafter: {"drafted":1,"secret":"private text"}', 0)
        self.assertNotIn("private", json.dumps(result))
        self.assertEqual(classify("paper_drafter", '{"drafted":1}', 7)["status"], "failed")

    def test_last_summary_wins_without_counting_duplicates(self):
        result = classify("paper_drafter", 'paper_drafter: {"drafted":1}\n{"drafted":0,"candidates":0}', 0)
        self.assertEqual(result["status"], "no_work")
        self.assertEqual(result["counters"]["drafted"], 0)


class OutcomeScheduleTest(unittest.TestCase):
    setUp = admission_tests.ConsiliumResourceAdmissionTest.setUp
    load_tick = admission_tests.ConsiliumResourceAdmissionTest.load_tick

    def test_frontier_skip_preserves_due_and_previous_production(self):
        self.process.stdout = '{"drafted":0,"skipped":"frontier unavailable"}'
        self.t.JOBS = [("paper_drafter", "paper_drafter.py", [], 3600, 2400)]
        self.t._save({"paper_drafter": {"at": 1, "last_productive_at": 1}})
        self.assertIsNone(self.t.tick())
        row = self.t._load()["paper_drafter"]
        self.assertEqual(row["at"], 1)
        self.assertEqual(row["last_productive_at"], 1)
        self.assertEqual(row["latest_attempt"]["status"], "deferred")
        self.assertEqual(self.t.next_due({"paper_drafter": row}, now=row["last_attempt"]["retry_after"])[0], "paper_drafter")

    def test_no_work_and_unverified_never_advance_productive_timestamp(self):
        state = {}
        for now, stdout in ((100, '{"drafted":1}'), (200, '{"drafted":0,"candidates":0}'), (300, "completed")):
            result = classify("paper_drafter", stdout, 0)
            with patch.object(self.t.time, "time", return_value=now):
                self.t._record_result(state, "paper_drafter", {"rc": 0, **result})
            self.assertEqual(state["paper_drafter"]["last_productive_at"], 100)
            self.assertEqual(state["paper_drafter"]["latest_attempt"]["at"], now)
        self.assertEqual(state["paper_drafter"]["last_productive_outcome"]["absorption"], "unverified")


if __name__ == "__main__":
    unittest.main()
