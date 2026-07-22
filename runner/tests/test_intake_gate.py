"""
test_intake_gate.py — EV rejection and semantic dedup safety for intake_gate.

A) Material tasks always pass regardless of value or dedup.
B) Tasks with explicit value_usd < threshold are rejected.
C) Short-prompt tasks with no MRR project are rejected (value=0.0).
D) Tasks with project MRR compute value from log10(1+mrr)*0.1; pass/reject at threshold.
E) Tasks with sufficient default value pass.
F) Semantic dedup rejects similar active tasks when INTAKE_EMBEDDING_DEDUP=1.
G) Semantic dedup fails open when embedding service raises.
H) DRY_RUN mode passes all tasks but still logs rejection reasons.
I) Rejection events are written to resource_events; DB errors are swallowed.
"""
import os, sys, unittest, math
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import intake_gate


def _task(**kw):
    base = {"slug": "test-slug", "prompt": "Implement the missing feature with full tests.", "material": False}
    base.update(kw)
    return base


def _proj(**kw):
    base = {"id": "proj-1", "name": "myapp"}
    base.update(kw)
    return base


class TestEstimateValue(unittest.TestCase):

    def test_explicit_value_usd_wins(self):
        self.assertAlmostEqual(intake_gate.estimate_value(_task(value_usd=0.75), _proj()), 0.75)

    def test_material_returns_one(self):
        self.assertAlmostEqual(intake_gate.estimate_value(_task(material=True), _proj()), 1.0)

    def test_mrr_in_proj_dict(self):
        val = intake_gate.estimate_value(_task(), _proj(mrr_usd=100.0))
        expected = math.log10(1 + 100.0) * 0.1
        self.assertAlmostEqual(val, expected)

    def test_short_prompt_no_mrr_is_zero(self):
        val = intake_gate.estimate_value(_task(prompt="fix"), None)
        self.assertAlmostEqual(val, 0.0)

    def test_default_value_for_substantive_prompt(self):
        val = intake_gate.estimate_value(_task(), None)  # no proj → no MRR → heuristic
        self.assertAlmostEqual(val, intake_gate._DEFAULT_VALUE)

    def test_mrr_db_lookup_used_when_not_in_proj(self):
        mock_db = MagicMock()
        mock_db.select.return_value = [{"mrr_usd": 500.0}]
        with patch.object(intake_gate, "db", mock_db):
            val = intake_gate.estimate_value(_task(), _proj())  # proj has no mrr_usd key
        expected = math.log10(1 + 500.0) * 0.1
        self.assertAlmostEqual(val, expected)

    def test_db_error_falls_back_to_heuristic(self):
        mock_db = MagicMock()
        mock_db.select.side_effect = RuntimeError("db down")
        with patch.object(intake_gate, "db", mock_db):
            val = intake_gate.estimate_value(_task(), _proj())
        self.assertAlmostEqual(val, intake_gate._DEFAULT_VALUE)


class TestShouldQueue(unittest.TestCase):

    def setUp(self):
        self.inserts = []
        self.mock_db = MagicMock()
        self.mock_db.insert.side_effect = lambda table, row, **kw: self.inserts.append((table, row))

    def _gate(self, task, proj, env=None):
        env = env or {}
        patches = {
            "VALUE_THRESHOLD": float(env.get("INTAKE_VALUE_THRESHOLD", "0.10")),
            "EMBEDDING_DEDUP": env.get("INTAKE_EMBEDDING_DEDUP", "").lower() in ("1", "true", "yes"),
            "DRY_RUN": env.get("INTAKE_DRY_RUN", "").lower() in ("1", "true", "yes"),
        }
        with patch.object(intake_gate, "db", self.mock_db):
            with patch.multiple(intake_gate, **patches):
                return intake_gate.should_queue(task, proj)

    # A) Material always passes
    def test_material_always_passes(self):
        ok, reason = self._gate(_task(material=True, value_usd=0.0), _proj())
        self.assertTrue(ok)
        self.assertEqual(reason, "material")

    # B) Explicit low value_usd → rejected
    def test_low_explicit_value_rejected(self):
        ok, reason = self._gate(_task(value_usd=0.05), _proj())
        self.assertFalse(ok)
        self.assertIn("ev-rejection", reason)

    # C) Short prompt + no MRR → rejected
    def test_short_prompt_no_mrr_rejected(self):
        self.mock_db.select.return_value = []  # no app_revenue rows
        ok, reason = self._gate(_task(prompt="x"), _proj())
        self.assertFalse(ok)
        self.assertIn("ev-rejection", reason)

    # D) Sufficient project MRR → passes
    def test_high_mrr_proj_passes(self):
        ok, reason = self._gate(_task(), _proj(mrr_usd=1000.0))
        self.assertTrue(ok)
        self.assertEqual(reason, "ok")

    # E) Default value (substantive prompt, no MRR) passes at default threshold
    def test_default_value_passes_threshold(self):
        self.mock_db.select.return_value = []
        ok, reason = self._gate(_task(), None)
        self.assertTrue(ok)

    # F) Rejection event written to resource_events
    def test_rejection_logged_to_resource_events(self):
        self._gate(_task(value_usd=0.0), _proj())
        tables = [t for t, _ in self.inserts]
        self.assertIn("resource_events", tables)

    # G) DB insert error on logging is swallowed
    def test_log_db_error_swallowed(self):
        self.mock_db.insert.side_effect = RuntimeError("db down")
        try:
            ok, _ = self._gate(_task(value_usd=0.0), _proj())
        except Exception:
            self.fail("DB error during logging must not propagate")
        self.assertFalse(ok)

    # H) DRY_RUN: low-value task still gets ok=True but reason explains rejection
    def test_dry_run_passes_but_notes_reason(self):
        ok, reason = self._gate(_task(value_usd=0.0), _proj(),
                                env={"INTAKE_DRY_RUN": "1"})
        self.assertTrue(ok)
        self.assertIn("ev-rejection", reason)

    # I) Semantic dedup rejects near-duplicate
    def test_embedding_dedup_rejects_similar_task(self):
        dummy_vec = [1.0, 0.0, 0.0]
        mock_ctx = MagicMock()
        mock_ctx.ENABLED = True
        mock_ctx._batch_embed.return_value = [dummy_vec]

        self.mock_db.select.return_value = [
            {"id": "existing", "prompt": "Implement the missing feature with full tests."}
        ]

        with patch.object(intake_gate, "db", self.mock_db):
            with patch.dict("sys.modules", {"context_embed": mock_ctx}):
                with patch.multiple(intake_gate, EMBEDDING_DEDUP=True, VALUE_THRESHOLD=0.0,
                                    _DEFAULT_VALUE=1.0):
                    ok, reason = intake_gate.should_queue(_task(), _proj())

        self.assertFalse(ok)
        self.assertIn("dedup", reason)

    # J) Embedding dedup fails open when embedding raises
    def test_embedding_dedup_fails_open_on_error(self):
        mock_ctx = MagicMock()
        mock_ctx.ENABLED = True
        mock_ctx._batch_embed.side_effect = RuntimeError("embed service down")

        with patch.object(intake_gate, "db", self.mock_db):
            with patch.dict("sys.modules", {"context_embed": mock_ctx}):
                with patch.multiple(intake_gate, EMBEDDING_DEDUP=True, VALUE_THRESHOLD=0.0,
                                    _DEFAULT_VALUE=1.0):
                    ok, reason = intake_gate.should_queue(_task(), _proj())

        self.assertTrue(ok)


if __name__ == "__main__":
    unittest.main(verbosity=2)
