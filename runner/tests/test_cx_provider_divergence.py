"""Tests for cx_provider_divergence."""
import unittest


class TestProviderDivergence(unittest.TestCase):

    def test_verdicts_diverge_yes_no(self):
        from runner.cx_provider_divergence import _verdicts_diverge
        self.assertTrue(_verdicts_diverge("Yes, this is compliant", "No, this fails"))
        self.assertFalse(_verdicts_diverge("Yes, approved", "Yes, looks good"))

    def test_verdicts_diverge_empty(self):
        from runner.cx_provider_divergence import _verdicts_diverge
        self.assertTrue(_verdicts_diverge("Yes", None))
        self.assertTrue(_verdicts_diverge(None, "No"))
        self.assertTrue(_verdicts_diverge("", "No"))

    def test_pick_alternate_provider(self):
        from runner.cx_provider_divergence import _pick_alternate_provider
        alt = _pick_alternate_provider("claude-sonnet-4-6")
        self.assertNotIn("claude", alt.lower())
        alt2 = _pick_alternate_provider("openai:gpt-4o")
        self.assertNotIn("openai", alt2.lower())

    def test_syntax_check(self):
        import py_compile
        py_compile.compile("runner/cx_provider_divergence.py", doraise=True)


if __name__ == "__main__":
    unittest.main()
