import os
import sys
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import public_copy_guard
import release_train


class FakeDB:
    def __init__(self):
        self.rows = {}
        self.inserts = []

    def select(self, table, params=None):
        return list(self.rows.get(table, []))

    def insert(self, table, row, **kwargs):
        self.inserts.append((table, row))
        return [row]


class TestPublicCopyGuard(unittest.TestCase):
    def test_general_marketing_abstraction_is_allowed(self):
        findings = public_copy_guard.scan_lines("pages/index.vue", [
            (12, "<p>Privacy-preserving workflows with enterprise-grade safeguards.</p>"),
            (13, "<p>Compliance-aware automation for sensitive teams.</p>"),
        ])
        self.assertEqual(findings, [])

    def test_specific_ip_mechanism_is_blocked(self):
        findings = public_copy_guard.scan_lines("components/Hero.tsx", [
            (8, "<p>Our CADE common brain uses model slashing and a merged-diff library.</p>"),
        ])
        self.assertEqual(findings[0]["rule"], "proprietary_mechanism")

    def test_specific_legal_strategy_is_blocked(self):
        findings = public_copy_guard.scan_lines("src/pages/legal.tsx", [
            (22, "<p>Our legal strategy avoids money transmission and legal advice.</p>"),
        ])
        self.assertEqual(findings[0]["rule"], "legal_strategy")

    def test_vendor_ip_partitioning_is_blocked(self):
        findings = public_copy_guard.scan_lines("content/security.md", [
            (5, "No single model sees the full IP, so vendors cannot replicate the app."),
        ])
        self.assertEqual(findings[0]["rule"], "vendor_ip_partitioning")

    def test_non_public_files_are_ignored(self):
        findings = public_copy_guard.scan_lines("runner/agent_market.py", [
            (5, "CADE common brain model slashing"),
        ])
        self.assertEqual(findings, [])

    def test_css_selectors_in_a_style_block_are_not_copy(self):
        # Two of the three findings that turned the gate RED on 24cfb48f were
        # CSS rules whose selector happened to be named after the engine.
        findings = public_copy_guard.scan_lines("web/components/LegoraLanding.vue", [
            (248, "<style scoped>"),
            (249, ".cade-rail{display:flex;flex-direction:column;padding:18px 14px}"),
            (250, ".cade-rail>header b{color:#24563e}.cade-rail h3{margin:8px 0}"),
            (251, "</style>"),
        ])
        self.assertEqual(findings, [])

    def test_class_attribute_is_a_selector_not_copy(self):
        findings = public_copy_guard.scan_lines("web/components/LegoraLanding.vue", [
            (34, '<aside class="cade-rail"><p>Clear decisions, prepared.</p></aside>'),
        ])
        self.assertEqual(findings, [])

    def test_rendered_text_beside_a_selector_is_still_blocked(self):
        # The exemption must not swallow the one real finding on that diff.
        findings = public_copy_guard.scan_lines("web/components/LegoraLanding.vue", [
            (38, '<aside class="cade-rail"><p>CADE shows the evidence, affected '
                 'systems, tradeoffs, and the exact action.</p></aside>'),
        ])
        self.assertEqual(findings[0]["rule"], "proprietary_mechanism")

    def test_script_block_strings_are_still_scanned(self):
        # <script> is not exempt: components keep user-facing copy in there.
        findings = public_copy_guard.scan_lines("web/components/LegoraLanding.vue", [
            (1, "<script setup lang=\"ts\">"),
            (2, "const panels = [{ title: 'CADE common brain', body: 'x' }]"),
            (3, "</script>"),
        ])
        self.assertEqual(findings[0]["rule"], "proprietary_mechanism")

    def test_unclosed_style_opener_outside_the_window_fails_open(self):
        # Only the supplied lines are tracked, so an orphan CSS line is scanned.
        findings = public_copy_guard.scan_lines("web/components/LegoraLanding.vue", [
            (300, ".cade-rail dt{color:#7b7d76}"),
        ])
        self.assertEqual(findings[0]["rule"], "proprietary_mechanism")


class TestReleaseTrainPublicCopyGate(unittest.TestCase):
    def test_public_copy_self_heal_queues_copyfix(self):
        fake = FakeDB()
        stub_contract = types.SimpleNamespace(wrap_prompt=lambda prompt, **kwargs: prompt)
        with patch.object(release_train, "db", fake), \
             patch.object(release_train, "_git") as git, \
             patch.dict(sys.modules, {"pipeline_contract": stub_contract}):
            git.return_value.stdout = "pages/index.vue | 2 +"
            release_train._self_heal_public_copy(
                {"id": "p1", "default_base": "main"},
                "app",
                "/repo",
                "orchestrator/dev",
                [{"file": "pages/index.vue", "line": 7, "rule": "legal_strategy",
                  "excerpt": "legal strategy avoids money transmission",
                  "guidance": "Use abstract marketing language."}],
            )
        self.assertTrue(any(t == "tasks" and r["slug"].startswith("copyfix-app-")
                            for t, r in fake.inserts))


if __name__ == "__main__":
    unittest.main()
