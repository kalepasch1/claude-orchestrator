import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import design_sources


class DesignSourcesTest(unittest.TestCase):
    def setUp(self):
        self.repo = tempfile.mkdtemp()
        subprocess.run(["git", "init", "-q"], cwd=self.repo, check=True)

    def write(self, path, text):
        absolute = os.path.join(self.repo, path)
        os.makedirs(os.path.dirname(absolute), exist_ok=True)
        with open(absolute, "w", encoding="utf-8") as handle:
            handle.write(text)
        subprocess.run(["git", "add", path], cwd=self.repo, check=True)

    def test_inventory_finds_all_design_filename_classes(self):
        self.write("SPEC.md", "# Main Spec\n- Runtime must stay green.\n")
        self.write("docs/widget-design.md", "# Widget Design\n## Acceptance Criteria\n- Works.\n")
        self.write("docs/decisions/ADR-1.md", "# Decision\n## Decision\nUse one path.\n")
        self.write("README.md", "# Read me\n")
        paths = {source.path for source in design_sources.inventory(self.repo)}
        self.assertEqual(paths, {"SPEC.md", "docs/widget-design.md", "docs/decisions/ADR-1.md"})

    def test_proposed_source_is_advisory_not_active(self):
        self.write("BLUEPRINT-next.md", "# Next\n**Status:** Proposed\n- Add a future engine.\n")
        result = design_sources.contract(self.repo)
        self.assertEqual(result["paths"], [])
        self.assertIn("Advisory/proposed", result["text"])

    def test_contract_contains_requirements_and_paths(self):
        self.write("product-requirements.md", "# Product\n- API must authenticate requests.\n")
        result = design_sources.contract(self.repo)
        self.assertIn("API must authenticate", result["text"])
        self.assertEqual(result["paths"], ["product-requirements.md"])

    def test_fingerprint_changes_with_design_content(self):
        self.write("SPEC.md", "# Spec\n- First.\n")
        first = design_sources.fingerprint(self.repo)
        self.write("SPEC.md", "# Spec\n- Second.\n")
        self.assertNotEqual(first, design_sources.fingerprint(self.repo))

    def test_completion_rejects_unassembled_active_source(self):
        self.write("SPEC.md", "# Spec\n- Implement it.\n")
        result = design_sources.completion_check(self.repo, ["runner/a.py"], [])
        self.assertFalse(result["pass"])
        self.assertIn("absent from assembled prompt", result["notes"])

    def test_completion_rejects_design_only_diff(self):
        self.write("SPEC.md", "# Spec\n- Implement it.\n")
        result = design_sources.completion_check(self.repo, ["SPEC.md"], ["SPEC.md"])
        self.assertFalse(result["pass"])
        self.assertIn("without implementation", result["notes"])

    def test_completion_accepts_design_and_runtime_diff(self):
        self.write("SPEC.md", "# Spec\n- Implement it.\n")
        result = design_sources.completion_check(
            self.repo, ["SPEC.md", "runner/feature.py"], ["SPEC.md"]
        )
        self.assertTrue(result["pass"])

    def test_audit_reports_pending_active_source_only(self):
        self.write("system-design.md", "# Design\nPending implementation.\n")
        self.write("BLUEPRINT-later.md", "# Later\n**Status:** Proposed\nPending implementation.\n")
        result = design_sources.audit(self.repo)
        self.assertEqual(result["pending"], ["system-design.md"])


if __name__ == "__main__":
    unittest.main()
