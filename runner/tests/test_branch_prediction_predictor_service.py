"""Unit tests for branch_prediction_predictor."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import branch_prediction_model_trainer as trainer
import branch_prediction_predictor as predictor


def _write_model(directory, weights, bias, threshold=0.5):
    path = os.path.join(directory, "model.json")
    with open(path, "w") as f:
        json.dump({
            "weights": weights,
            "bias": bias,
            "feature_names": ["a", "b", "c", "d", "e"],
            "threshold": threshold,
            "metrics": {},
        }, f)
    return path


class TestPredictorServiceLoadModel(unittest.TestCase):
    def test_load_returns_true_on_valid_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = _write_model(d, [0.1, -0.2, 0.3, 0.4, 0.0], 0.0)
            svc = predictor.PredictorService(model_path=path)
            self.assertTrue(svc.load_model())
            self.assertTrue(svc.is_loaded())

    def test_load_returns_false_on_missing_file(self):
        svc = predictor.PredictorService(model_path="/nonexistent/model.json")
        self.assertFalse(svc.load_model())
        self.assertFalse(svc.is_loaded())

    def test_load_returns_false_on_invalid_json(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "bad.json")
            with open(path, "w") as f:
                f.write("not json")
            svc = predictor.PredictorService(model_path=path)
            self.assertFalse(svc.load_model())


class TestPredictorServicePredictBranchStatus(unittest.TestCase):
    def _loaded_service(self, weights, bias, threshold=0.5):
        with tempfile.TemporaryDirectory() as d:
            path = _write_model(d, weights, bias, threshold)
            svc = predictor.PredictorService(model_path=path)
            svc.load_model()
        return svc

    def test_output_keys(self):
        svc = self._loaded_service([0.0] * 5, 0.0)
        result = svc.predict_branch_status()
        self.assertIn("probability", result)
        self.assertIn("decision", result)
        self.assertIn("loaded", result)

    def test_probability_in_0_1(self):
        svc = self._loaded_service([1.0, 1.0, 1.0, 1.0, 1.0], 0.0)
        result = svc.predict_branch_status(branch_age_days=50)
        self.assertGreaterEqual(result["probability"], 0.0)
        self.assertLessEqual(result["probability"], 1.0)

    def test_decision_is_needed_or_stale(self):
        svc = self._loaded_service([0.0] * 5, 0.0)
        result = svc.predict_branch_status()
        self.assertIn(result["decision"], ("needed", "stale"))

    def test_high_bias_predicts_needed(self):
        svc = self._loaded_service([0.0] * 5, 100.0)
        result = svc.predict_branch_status()
        self.assertEqual(result["decision"], "needed")
        self.assertGreater(result["probability"], 0.9)

    def test_low_bias_predicts_stale(self):
        svc = self._loaded_service([0.0] * 5, -100.0)
        result = svc.predict_branch_status()
        self.assertEqual(result["decision"], "stale")
        self.assertLess(result["probability"], 0.1)

    def test_loaded_flag_is_true_when_model_loaded(self):
        svc = self._loaded_service([0.0] * 5, 0.0)
        result = svc.predict_branch_status()
        self.assertTrue(result["loaded"])


class TestHeuristicFallback(unittest.TestCase):
    def setUp(self):
        self.svc = predictor.PredictorService(model_path="/nonexistent.json")

    def test_queued_task_is_needed(self):
        result = self.svc.predict_branch_status(task_state_queued=1)
        self.assertEqual(result["decision"], "needed")
        self.assertFalse(result["loaded"])

    def test_running_task_is_needed(self):
        result = self.svc.predict_branch_status(task_state_running=1)
        self.assertEqual(result["decision"], "needed")

    def test_very_old_branch_is_stale(self):
        result = self.svc.predict_branch_status(branch_age_days=90, days_since_activity=60)
        self.assertEqual(result["decision"], "stale")

    def test_inactive_branch_is_stale(self):
        result = self.svc.predict_branch_status(days_since_activity=40)
        self.assertEqual(result["decision"], "stale")


class TestModuleLevelPredict(unittest.TestCase):
    def test_returns_dict_without_raising(self):
        # module-level function must never raise even without a model file
        result = predictor.predict_branch_status(
            branch_age_days=5, days_since_activity=1, task_state_queued=1
        )
        self.assertIn("decision", result)
        self.assertIn("probability", result)

    def test_fresh_queued_is_needed_end_to_end(self):
        with tempfile.TemporaryDirectory() as d:
            from unittest.mock import patch
            with patch("branch_event_telemetry.get_historical_branch_events", return_value=[]):
                res = trainer.train_model_pipeline(use_synthetic_fallback=True,
                                                    model_path=os.path.join(d, "m.json"))
            svc = predictor.PredictorService(model_path=res["model_path"])
            svc.load_model()
        # Very fresh branch with a queued task should be "needed"
        result = svc.predict_branch_status(
            branch_age_days=1, days_since_activity=0.5,
            task_state_queued=1, task_state_running=0,
            project_queue_depth_norm=0.3,
        )
        self.assertEqual(result["decision"], "needed")

    def test_very_old_inactive_is_stale_end_to_end(self):
        with tempfile.TemporaryDirectory() as d:
            from unittest.mock import patch
            with patch("branch_event_telemetry.get_historical_branch_events", return_value=[]):
                res = trainer.train_model_pipeline(use_synthetic_fallback=True,
                                                    model_path=os.path.join(d, "m.json"))
            svc = predictor.PredictorService(model_path=res["model_path"])
            svc.load_model()
        # 80-day-old branch with no activity or active task should be "stale"
        result = svc.predict_branch_status(
            branch_age_days=80, days_since_activity=75,
            task_state_queued=0, task_state_running=0,
            project_queue_depth_norm=0.0,
        )
        self.assertEqual(result["decision"], "stale")


if __name__ == "__main__":
    unittest.main()
