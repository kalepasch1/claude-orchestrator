"""Tests for adaptive_budget.py — adaptive token budget prediction.

Covers: predict_budget kind defaults, historical P90 path, template estimate,
record_output accumulation, history cap, headroom, fail-soft on missing DB.
"""
import importlib
import json
import os
import sys
import types
import unittest

# ---------------------------------------------------------------------------
# Stub db and config_consumer before importing
# ---------------------------------------------------------------------------
_controls_store: dict = {}


class _FakeDB:
    @staticmethod
    def select(table, params=None):
        if table == "controls":
            key = (params or {}).get("key", "").replace("eq.", "")
            if key in _controls_store:
                return [{"value": json.dumps(_controls_store[key])}]
        return []

    @staticmethod
    def upsert(table, payload):
        if table == "controls":
            _controls_store[payload["key"]] = json.loads(payload["value"])


sys.modules.setdefault("db", types.ModuleType("db"))
db_mod = sys.modules["db"]
db_mod.select = _FakeDB.select
db_mod.upsert = _FakeDB.upsert

# Stub config_consumer
cc = types.ModuleType("config_consumer")
cc.env_int = lambda key, default, minimum=None: max(minimum or 0, int(os.environ.get(key, default)))
cc.env_float = lambda key, default, minimum=None: max(minimum or 0.0, float(os.environ.get(key, default)))
sys.modules["config_consumer"] = cc

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import adaptive_budget as ab


class TestPredictBudgetKindDefaults(unittest.TestCase):
    """No history → falls back to kind-based defaults."""

    def setUp(self):
        _controls_store.clear()

    def test_mechanical_gets_2048(self):
        result = ab.predict_budget({"kind": "mechanical", "prompt": "fix typo"})
        self.assertEqual(result["max_tokens"], 2048)
        self.assertEqual(result["source"], "kind_default")

    def test_feature_gets_6144(self):
        result = ab.predict_budget({"kind": "feature", "prompt": "add login"})
        self.assertEqual(result["max_tokens"], 6144)

    def test_unknown_kind_gets_default(self):
        result = ab.predict_budget({"kind": "exotic", "prompt": "something"})
        self.assertEqual(result["max_tokens"], ab.DEFAULT_BUDGET)

    def test_config_gets_1536(self):
        result = ab.predict_budget({"kind": "config", "prompt": "update env"})
        self.assertEqual(result["max_tokens"], 1536)

    def test_confidence_is_low(self):
        result = ab.predict_budget({"kind": "mechanical", "prompt": "x"})
        self.assertLessEqual(result["confidence"], 0.3)


class TestPredictBudgetHistorical(unittest.TestCase):
    """With >=5 samples, uses P90 path."""

    def setUp(self):
        _controls_store.clear()
        _controls_store["token_budget_history"] = {
            "build:backend": {
                "kind": "build", "domain": "backend",
                "samples": 20, "total_tokens": 40000,
                "avg_tokens": 2000, "max_tokens": 3500,
                "min_tokens": 800, "p90_tokens": 3000,
                "recent": [2000] * 20,
                "last_updated": 1000,
            }
        }

    def test_uses_historical_source(self):
        result = ab.predict_budget({"kind": "build", "prompt": "fix"}, domain="backend")
        self.assertEqual(result["source"], "historical")

    def test_budget_includes_headroom(self):
        result = ab.predict_budget({"kind": "build", "prompt": "fix"}, domain="backend")
        expected = int(3000 * ab.BUDGET_HEADROOM)
        self.assertEqual(result["max_tokens"], max(ab.MIN_BUDGET, min(expected, ab.DEFAULT_BUDGET)))

    def test_confidence_scales_with_samples(self):
        result = ab.predict_budget({"kind": "build", "prompt": "fix"}, domain="backend")
        self.assertGreater(result["confidence"], 0.3)

    def test_savings_pct_present(self):
        result = ab.predict_budget({"kind": "build", "prompt": "fix"}, domain="backend")
        self.assertIn("savings_pct", result)


class TestPredictBudgetTemplate(unittest.TestCase):
    """With a diff_plan, uses template estimate."""

    def setUp(self):
        _controls_store.clear()

    def test_template_path(self):
        plan = {"has_plan": True, "confidence": 0.8, "estimated_lines": 30}
        result = ab.predict_budget({"kind": "build", "prompt": "x"}, diff_plan=plan)
        self.assertEqual(result["source"], "template_estimate")
        self.assertGreaterEqual(result["max_tokens"], ab.MIN_BUDGET)

    def test_low_confidence_plan_ignored(self):
        plan = {"has_plan": True, "confidence": 0.2, "estimated_lines": 30}
        result = ab.predict_budget({"kind": "mechanical", "prompt": "x"}, diff_plan=plan)
        self.assertEqual(result["source"], "kind_default")


class TestRecordOutput(unittest.TestCase):
    def setUp(self):
        _controls_store.clear()

    def test_first_record(self):
        entry = ab.record_output({"kind": "build"}, "backend", 2500)
        self.assertEqual(entry["samples"], 1)
        self.assertEqual(entry["max_tokens"], 2500)
        self.assertEqual(entry["min_tokens"], 2500)

    def test_accumulates(self):
        ab.record_output({"kind": "build"}, "backend", 2000)
        entry = ab.record_output({"kind": "build"}, "backend", 3000)
        self.assertEqual(entry["samples"], 2)
        self.assertEqual(entry["max_tokens"], 3000)
        self.assertEqual(entry["min_tokens"], 2000)
        self.assertEqual(entry["avg_tokens"], 2500)

    def test_recent_capped_at_50(self):
        for i in range(60):
            ab.record_output({"kind": "test"}, "frontend", 1000 + i)
        history = _controls_store.get("token_budget_history", {})
        entry = history.get("test:frontend", {})
        self.assertLessEqual(len(entry.get("recent", [])), 50)

    def test_p90_computed(self):
        for i in range(10):
            ab.record_output({"kind": "build"}, "api", 1000 + i * 100)
        history = _controls_store.get("token_budget_history", {})
        entry = history.get("build:api", {})
        self.assertGreater(entry.get("p90_tokens", 0), 0)


class TestHistoryCap(unittest.TestCase):
    def setUp(self):
        _controls_store.clear()

    def test_cap_at_200(self):
        big = {f"kind{i}:dom{i}": {"last_updated": i, "samples": 1} for i in range(250)}
        _controls_store["token_budget_history"] = big
        ab._save_history(big)
        saved = _controls_store.get("token_budget_history", {})
        self.assertLessEqual(len(saved), 200)


class TestResultShape(unittest.TestCase):
    def setUp(self):
        _controls_store.clear()

    def test_all_keys_present(self):
        result = ab.predict_budget({"kind": "build", "prompt": "test"})
        for key in ("max_tokens", "predicted_output", "confidence", "source", "savings_pct"):
            self.assertIn(key, result, f"missing key: {key}")

    def test_budget_never_below_minimum(self):
        result = ab.predict_budget({"kind": "mechanical", "prompt": "x"})
        self.assertGreaterEqual(result["max_tokens"], ab.MIN_BUDGET)


if __name__ == "__main__":
    unittest.main()
