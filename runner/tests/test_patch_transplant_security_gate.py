#!/usr/bin/env python3
"""The transplant security gate must refuse, not `pass`.

`adapt_patch` rewrites a prior diff's file headers so a proven patch can land on
a different file. Before this change it also contained:

    if "ORCH_PIPELINE_SECURITY_GATE" in adapted and ...:
        pass

— a check that parsed, evaluated, and did nothing. Every security-sensitive
patch was transplanted exactly as if the check were absent, onto a file it had
never been reviewed against.

The gate is fail-CLOSED: it returns None rather than degrading, because a
silently relocated security change is worse than no transplant at all.
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import patch_transplant as pt

CLEAN = (
    "--- a/runner/thing.py\n"
    "+++ b/runner/thing.py\n"
    "@@ -1,2 +1,4 @@\n"
    "+def helper(x):\n"
    "+    return x + 1\n"
)

GATE_PATCH = (
    "--- a/runner/gate.py\n"
    "+++ b/runner/gate.py\n"
    "@@ -1,2 +1,3 @@\n"
    '+ORCH_PIPELINE_SECURITY_GATE = "off"\n'
)


class TestSecurityFindings(unittest.TestCase):
    def test_clean_patch_has_no_findings(self):
        self.assertEqual(pt.security_findings(CLEAN), [])

    def test_the_gate_variable_this_check_was_written_for(self):
        self.assertEqual(pt.security_findings(GATE_PATCH), ['ORCH_PIPELINE_SECURITY_GATE'])

    def test_credentials_and_privilege_escalation_are_caught(self):
        cases = {
            '+API_KEY = "sk-live-123"': 'API_KEY',
            '+access_token = fetch()': 'access_token',
            '+PASSWORD = "hunter2"': 'PASSWORD',
            '+-----BEGIN RSA PRIVATE KEY-----': 'BEGIN RSA PRIVATE KEY',
            '+    subprocess.run(["sudo", "rm"])': 'sudo',
            '+os.system("chmod 777 /tmp/x")': 'chmod 777',
            '+headers["Authorization"] = tok': 'Authorization',
        }
        for line, expected in cases.items():
            findings = pt.security_findings(f"--- a/x\n+++ b/x\n@@\n{line}\n")
            self.assertTrue(findings, line)
            self.assertEqual(findings[0].lower().replace('-', ' ').replace('_', ' '),
                             expected.lower().replace('-', ' ').replace('_', ' '), line)

    def test_only_added_lines_are_judged(self):
        """Removing a hardcoded secret is a patch worth transplanting."""
        removal = '--- a/x\n+++ b/x\n@@\n-API_KEY = "sk-live-123"\n+API_KEY = os.environ["K"]\n'
        # the added line references API_KEY too, so this one IS flagged;
        # a pure removal must not be.
        pure_removal = '--- a/x\n+++ b/x\n@@\n-PASSWORD = "hunter2"\n'
        self.assertEqual(pt.security_findings(pure_removal), [])
        self.assertTrue(pt.security_findings(removal))

    def test_file_headers_are_not_treated_as_added_lines(self):
        self.assertEqual(pt.security_findings("--- a/secret.py\n+++ b/secret.py\n"), [])

    def test_context_lines_are_ignored(self):
        self.assertEqual(pt.security_findings('--- a/x\n+++ b/x\n@@\n API_KEY = old\n'), [])

    def test_findings_are_deduplicated_and_capped(self):
        body = "\n".join(f'+API_KEY = "k{i}"' for i in range(20))
        self.assertEqual(pt.security_findings(f"--- a/x\n+++ b/x\n@@\n{body}\n"), ['API_KEY'])

    def test_accepts_bytes(self):
        self.assertEqual(pt.security_findings(GATE_PATCH.encode()), ['ORCH_PIPELINE_SECURITY_GATE'])

    def test_fail_soft_on_bad_input(self):
        for bad in (None, "", 0, b"", [], {}):
            self.assertEqual(pt.security_findings(bad), [])


class TestAdaptPatchGate(unittest.TestCase):
    def test_a_clean_patch_is_still_adapted(self):
        result = pt.adapt_patch(CLEAN, {"slug": "s"}, target_files=["runner/other.py"])
        self.assertIsNotNone(result)
        self.assertIn("--- a/runner/other.py", result)
        self.assertIn("+++ b/runner/other.py", result)

    def test_a_security_patch_is_refused(self):
        self.assertIsNone(pt.adapt_patch(GATE_PATCH, {"slug": "s"}, target_files=["runner/other.py"]))

    def test_refusal_survives_header_rewriting(self):
        """The gate runs AFTER the rewrite — relocation is the hazard."""
        self.assertIsNone(pt.adapt_patch(GATE_PATCH, {"slug": "s"}, target_files=["totally/unrelated.py"]))

    def test_refusal_is_logged_with_the_offending_token(self):
        with patch.object(pt.log, "warning") as warn:
            pt.adapt_patch(GATE_PATCH, {"slug": "s"})
        warn.assert_called_once()
        self.assertIn("ORCH_PIPELINE_SECURITY_GATE", str(warn.call_args))

    def test_bytes_in_bytes_out_for_a_clean_patch(self):
        result = pt.adapt_patch(CLEAN.encode(), {"slug": "s"})
        self.assertIsInstance(result, bytes)

    def test_bytes_security_patch_is_refused_too(self):
        self.assertIsNone(pt.adapt_patch(GATE_PATCH.encode(), {"slug": "s"}))

    def test_empty_input_still_returns_none(self):
        self.assertIsNone(pt.adapt_patch("", {"slug": "s"}))
        self.assertIsNone(pt.adapt_patch(None, {"slug": "s"}))


class TestBroadCatchesAreLogged(unittest.TestCase):
    """CLAUDE.md: a broad catch is the convention; a SILENT one is the defect."""

    def test_transplant_source_lookup_logs_before_swallowing(self):
        with patch.object(pt.db, "select", side_effect=RuntimeError("db down")), \
             patch.object(pt.log, "debug") as dbg:
            self.assertIsNone(pt.find_transplant_source({"slug": "s"}))
        dbg.assert_called()

    def test_pre_claim_hook_logs_before_returning_the_task(self):
        task = {"id": "1", "slug": "s", "prompt": "p"}
        with patch.object(pt, "hint", side_effect=RuntimeError("boom")), \
             patch.object(pt.log, "debug") as dbg:
            self.assertEqual(pt.pre_claim_hook(task), task)
        dbg.assert_called()


if __name__ == "__main__":
    unittest.main()
