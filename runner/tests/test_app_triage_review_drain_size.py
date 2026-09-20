#!/usr/bin/env python3
"""The free-telemetry drain must be capable of draining.

Measured 2026-09-20 on the live table: 930,056 unscored operations against
125,675 scored; FIFO at 40 rows/30min loses ground every run (the module's own
log line says so). In the default model-free mode a score costs one row write,
so the batch is the drain size; the model-judged mode keeps its 40-row sample
because it spends a call per row.
"""
import os
import sys
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class _Db:
    def __init__(self, n_null):
        self.rows = [{"id": i, "app": "a", "operation": "op", "task_class": "mechanical",
                      "provider": "local", "model": "m", "ok": True, "latency_ms": 10,
                      "cost_usd": 0.0, "quality_score": None, "created_at": "2026-09-20"} for i in range(n_null)]
        self.updates = 0

    def select(self, table, params=None):
        params = params or {}
        if table == "app_operations" and params.get("quality_score") == "is.null":
            return self.rows[: int(params.get("limit", "40"))]
        if table == "app_operations" and params.get("quality_score") == "not.is.null":
            return []
        return []

    def update(self, table, where, patch_):
        self.updates += 1
        return []

    def insert(self, table, row, **kw):
        return []

    def count(self, table, params=None):
        return len(self.rows)


def _load(db, env):
    import importlib
    mod = importlib.import_module("app_triage_review")
    with patch.dict(sys.modules, {"db": db, "judge": types.SimpleNamespace(review=lambda *a, **k: {"score": 7, "verdict": "pass"})}):
        with patch.dict(os.environ, env, clear=False):
            if "ORCH_APP_REVIEW_USE_MODEL" not in env:
                os.environ.pop("ORCH_APP_REVIEW_USE_MODEL", None)
            # module-level constants are read at import — env must be set before the reload
            importlib.reload(mod)
            out = mod.run()
    return mod, out


class DrainSizeTests(unittest.TestCase):
    def test_model_free_mode_uses_the_drain_size(self):
        db = _Db(300)  # > 40, < 5000: the old cap would leave 260 unscored
        mod, out = _load(db, {})
        self.assertEqual(out["scored"], 300)
        self.assertEqual(db.updates, 300)

    def test_model_mode_keeps_the_sample_size(self):
        db = _Db(300)
        mod, out = _load(db, {"ORCH_APP_REVIEW_USE_MODEL": "true"})
        self.assertLessEqual(out["scored"], mod.SAMPLE)
        self.assertGreater(len(db.rows), out["scored"])

    def test_env_overrides_drain_size(self):
        db = _Db(300)
        mod, out = _load(db, {"APP_REVIEW_SAMPLE_MODEL_FREE": "120"})
        self.assertEqual(out["scored"], 120)


if __name__ == "__main__":
    unittest.main()
