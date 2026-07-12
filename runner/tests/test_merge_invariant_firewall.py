"""
test_merge_invariant_firewall.py - test pre-merge invariant checks:
  - A passing (clean) diff is allowed
  - Each invalidating pattern is blocked:
    * RLS policy weakening
    * Money-movement default flip
    * Token gate removal
  - With flag OFF, all diffs pass (behavior unchanged)
"""
import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import merge_invariant_firewall as fw


class TestFlagOff(unittest.TestCase):
    """When ORCH_MERGE_FIREWALL_ENABLED is false, nothing is blocked."""

    def setUp(self):
        self._orig = fw.ENABLED
        fw.ENABLED = False

    def tearDown(self):
        fw.ENABLED = self._orig

    def test_rls_drop_allowed_when_off(self):
        diff = "DROP POLICY user_rls ON public.accounts;"
        self.assertEqual(fw.check_diff(diff), [])
        self.assertFalse(fw.should_block(diff))

    def test_money_default_allowed_when_off(self):
        diff = "+SETTLEMENT_SWEEP_ENABLED = true"
        self.assertEqual(fw.check_diff(diff), [])


class TestCleanDiff(unittest.TestCase):
    """A normal diff with no dangerous patterns passes all checks."""

    def setUp(self):
        self._orig = fw.ENABLED
        fw.ENABLED = True

    def tearDown(self):
        fw.ENABLED = self._orig

    def test_clean_diff_passes(self):
        diff = """
diff --git a/runner/foo.py b/runner/foo.py
--- a/runner/foo.py
+++ b/runner/foo.py
@@ -1,3 +1,4 @@
+import os
 def hello():
     return "world"
"""
        allow, violations = fw.gate(diff)
        self.assertTrue(allow)
        self.assertEqual(violations, [])

    def test_empty_diff_passes(self):
        allow, violations = fw.gate("")
        self.assertTrue(allow)


class TestRLSWeakening(unittest.TestCase):

    def setUp(self):
        self._orig = fw.ENABLED
        fw.ENABLED = True

    def tearDown(self):
        fw.ENABLED = self._orig

    def test_drop_policy_blocked(self):
        diff = "DROP POLICY user_isolation ON public.accounts;"
        blocked, reason = fw.check_rls_weakening(diff)
        self.assertTrue(blocked)
        self.assertIn("RLS", reason)

    def test_disable_rls_blocked(self):
        diff = "ALTER TABLE public.accounts DISABLE ROW LEVEL SECURITY;"
        blocked, reason = fw.check_rls_weakening(diff)
        self.assertTrue(blocked)

    def test_permissive_true_blocked(self):
        diff = "ALTER POLICY open_all ON accounts USING (true);"
        blocked, reason = fw.check_rls_weakening(diff)
        self.assertTrue(blocked)

    def test_create_policy_not_blocked(self):
        diff = "CREATE POLICY read_own ON accounts USING (auth.uid() = user_id);"
        blocked, _ = fw.check_rls_weakening(diff)
        self.assertFalse(blocked)


class TestMoneyMovementDefault(unittest.TestCase):

    def setUp(self):
        self._orig = fw.ENABLED
        fw.ENABLED = True

    def tearDown(self):
        fw.ENABLED = self._orig

    def test_settlement_sweep_flip_blocked(self):
        diff = "+SETTLEMENT_SWEEP_ENABLED = true"
        blocked, reason = fw.check_money_movement_default(diff)
        self.assertTrue(blocked)
        self.assertIn("Money-movement", reason)

    def test_normal_config_not_blocked(self):
        diff = "+LOG_LEVEL = debug"
        blocked, _ = fw.check_money_movement_default(diff)
        self.assertFalse(blocked)


class TestTokenGateRemoval(unittest.TestCase):

    def setUp(self):
        self._orig = fw.ENABLED
        fw.ENABLED = True

    def tearDown(self):
        fw.ENABLED = self._orig

    def test_require_auth_removal_blocked(self):
        diff = "-    require_auth(request)"
        blocked, reason = fw.check_token_gate_removal(diff)
        self.assertTrue(blocked)
        self.assertIn("Token gate", reason)

    def test_verify_token_removal_blocked(self):
        diff = "-    verify_token(token)"
        blocked, reason = fw.check_token_gate_removal(diff)
        self.assertTrue(blocked)

    def test_adding_auth_not_blocked(self):
        diff = "+    require_auth(request)"
        blocked, _ = fw.check_token_gate_removal(diff)
        self.assertFalse(blocked)


class TestGateComposition(unittest.TestCase):

    def setUp(self):
        self._orig = fw.ENABLED
        fw.ENABLED = True

    def tearDown(self):
        fw.ENABLED = self._orig

    def test_multiple_violations(self):
        diff = "DROP POLICY x;\n+SETTLEMENT_SWEEP_ENABLED = true\n-    require_auth(r)"
        allow, violations = fw.gate(diff)
        self.assertFalse(allow)
        self.assertGreaterEqual(len(violations), 2)

    def test_should_block_convenience(self):
        self.assertTrue(fw.should_block("DROP POLICY x;"))
        self.assertFalse(fw.should_block("normal code change"))


if __name__ == "__main__":
    unittest.main()
