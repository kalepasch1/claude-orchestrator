"""One root cause must file one task, not one per job.

A module-level failure crashes every scheduled job at once — they all import the
module before any job body runs — so a single `NameError: name 'run_editorial'
is not defined` appeared in every job's own .err and the detector filed one task
each. Measured on the live queue: 33 tasks under one detector fingerprint, in
just THREE traceback groups of 21, 10 and 2. Twenty-one agents would each spend a
full run rediscovering the same already-fixed line.

Per-signature dedupe alone was tried and reverted, and `state_key` records why:
with a job+signature slug, the first job wrote state[sig] and every OTHER job's
identical signature was reported "[deduplicated]" forever — 26 of 49 live
findings, including 2 of 3 CRITICAL dead modules, could never file a task.

Coalescing keeps both properties: one task per signature, and it NAMES every job
the signature killed, so nothing is suppressed — the jobs move into the body
instead of into separate tickets.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import crash_loop_detector as c


def _finding(job, sig="sigX", count=100, reasons=("repeating",), severity="high"):
    return {
        "job": job, "signature": sig, "count": count, "share": 0.5,
        "job_tracebacks": 200, "reasons": list(reasons), "transient": False,
        "severity": severity, "exception": "NameError: name 'run_editorial' is not defined",
        "last_frame": "periodic.py line 703", "traceback": "Traceback ...",
        "err_path": "/logs/%s.err" % job, "log_size": 10,
    }


class OneSignatureOneFinding(unittest.TestCase):
    def test_twenty_one_jobs_one_signature_collapse_to_one(self):
        findings = [_finding("job%d" % i, count=300 - i) for i in range(21)]
        merged = c.coalesce_by_signature(findings)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["job_count"], 21)

    def test_every_affected_job_is_named(self):
        findings = [_finding("job%d" % i) for i in range(5)]
        merged = c.coalesce_by_signature(findings)
        named = {j["job"] for j in merged[0]["jobs"]}
        self.assertEqual(named, {"job0", "job1", "job2", "job3", "job4"},
                         "nothing may be suppressed — the jobs move into the body")

    def test_distinct_signatures_stay_distinct(self):
        findings = [_finding("a", sig="s1"), _finding("b", sig="s2"), _finding("c", sig="s1")]
        merged = c.coalesce_by_signature(findings)
        self.assertEqual(len(merged), 2)
        self.assertEqual({m["signature"] for m in merged}, {"s1", "s2"})

    def test_counts_are_summed_across_jobs(self):
        findings = [_finding("a", count=10), _finding("b", count=32)]
        self.assertEqual(c.coalesce_by_signature(findings)[0]["count"], 42)

    def test_the_worst_severity_wins(self):
        findings = [
            _finding("a", reasons=("repeating",), severity="high"),
            _finding("b", reasons=("module_dead",), severity="critical"),
        ]
        merged = c.coalesce_by_signature(findings)
        self.assertEqual(merged[0]["severity"], "critical")
        self.assertIn("module_dead", merged[0]["reasons"],
                      "a dead module among crash-loopers is still a dead module")

    def test_the_representative_job_is_the_worst_hit(self):
        findings = [_finding("quiet", count=5), _finding("loudest", count=900)]
        self.assertEqual(c.coalesce_by_signature(findings)[0]["job"], "loudest")

    def test_a_single_job_signature_is_unchanged(self):
        merged = c.coalesce_by_signature([_finding("solo")])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["job_count"], 1)
        self.assertEqual(merged[0]["job"], "solo")

    def test_empty_and_malformed_input_do_not_throw(self):
        self.assertEqual(c.coalesce_by_signature([]), [])
        self.assertEqual(c.coalesce_by_signature(None), [])

    def test_classify_order_is_preserved(self):
        # classify() ranks by blast radius; coalescing must not reshuffle that.
        findings = [_finding("a", sig="big", count=900), _finding("b", sig="small", count=2)]
        merged = c.coalesce_by_signature(findings)
        self.assertEqual([m["signature"] for m in merged], ["big", "small"])


class DedupeCannotSilenceAJob(unittest.TestCase):
    def test_the_state_key_is_the_signature_once_coalesced(self):
        merged = c.coalesce_by_signature([_finding("a"), _finding("b")])
        self.assertEqual(c.state_key(merged[0]), "sigX")

    def test_an_uncoalesced_finding_still_keys_on_job_and_signature(self):
        # The old contract holds for any caller that skips coalescing.
        self.assertEqual(c.state_key(_finding("a")), "a|sigX")

    def test_upgrading_does_not_replay_every_historical_alert(self):
        """The first run after coalescing must not re-fire everything at once."""
        merged = c.coalesce_by_signature([_finding("a"), _finding("b")])
        state = {
            "a|sigX": {"last_alert": 1_000_000.0, "count_at_alert": 100, "job": "a"},
            "b|sigX": {"last_alert": 1_000_500.0, "count_at_alert": 100, "job": "b"},
        }
        fire, why = c._should_fire(merged[0], state, now=1_000_600.0)
        self.assertFalse(fire, "per-job state must be honoured once: %s" % why)

    def test_a_genuinely_new_signature_still_fires(self):
        merged = c.coalesce_by_signature([_finding("a", sig="brand-new")])
        fire, why = c._should_fire(merged[0], {}, now=1_000_000.0)
        self.assertTrue(fire)
        self.assertEqual(why, "new")

    def test_escalation_still_fires_through_the_coalesced_key(self):
        merged = c.coalesce_by_signature([_finding("a", count=10_000)])
        state = {"sigX": {"last_alert": 1_000_000.0, "count_at_alert": 10}}
        fire, _why = c._should_fire(merged[0], state, now=1_000_001.0)
        self.assertTrue(fire, "a 10x escalation must still be loud")


if __name__ == "__main__":
    unittest.main()
