"""Unit tests for branch_prediction_model_trainer."""
import json
import math
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import branch_prediction_data_pipeline as pipeline
import branch_prediction_model_trainer as trainer


class TestLogisticRegression(unittest.TestCase):
    def _separable_data(self):
        """Simple linearly separable dataset: large age=stale, small age=needed."""
        X = [[1.0, 1.0, 0.0, 0.0, 0.0]] * 50 + [[0.0, 0.0, 1.0, 0.0, 0.5]] * 50
        y = [0] * 50 + [1] * 50
        return X, y

    def test_weights_and_bias_shapes(self):
        X, y = self._separable_data()
        w, b = trainer.train_logistic_regression(X, y, lr=0.1, epochs=50, l2=0.0)
        self.assertEqual(len(w), 5)
        self.assertIsInstance(b, float)

    def test_converges_on_separable_data(self):
        X, y = self._separable_data()
        w, b = trainer.train_logistic_regression(X, y, lr=0.1, epochs=500, l2=0.0)
        metrics = trainer.compute_metrics(w, b, X, y)
        self.assertGreater(metrics["accuracy"], 0.9)

    def test_empty_input_returns_defaults(self):
        w, b = trainer.train_logistic_regression([], [], lr=0.1, epochs=10, l2=0.0)
        self.assertEqual(w, [])
        self.assertEqual(b, 0.0)


class TestComputeMetrics(unittest.TestCase):
    def _perfect_weights(self):
        # weight[0] = -10 → high age → prob near 0 (stale)
        # weight[0] = -10 → low age → prob near 0.5
        return [-10.0, 0.0, 10.0, 0.0, 0.0], 0.0

    def test_perfect_predictions_give_f1_1(self):
        # All positives: queued=1 → predict needed
        X = [[0.0, 0.0, 1.0, 0.0, 0.0]] * 10
        y = [1] * 10
        w, b = [0.0, 0.0, 20.0, 0.0, 0.0], 0.0
        m = trainer.compute_metrics(w, b, X, y)
        self.assertAlmostEqual(m["f1"], 1.0, places=3)
        self.assertAlmostEqual(m["precision"], 1.0, places=3)
        self.assertAlmostEqual(m["recall"], 1.0, places=3)

    def test_all_wrong_gives_f1_0_or_low(self):
        X = [[0.0, 0.0, 1.0, 0.0, 0.0]] * 10
        y = [0] * 10
        w, b = [0.0, 0.0, 20.0, 0.0, 0.0], 0.0
        m = trainer.compute_metrics(w, b, X, y)
        self.assertEqual(m["tp"], 0)
        self.assertEqual(m["fn"], 0)

    def test_empty_returns_zeros(self):
        m = trainer.compute_metrics([], 0.0, [], [])
        self.assertEqual(m["f1"], 0.0)
        self.assertEqual(m["accuracy"], 0.0)


class TestSaveLoadModel(unittest.TestCase):
    def test_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "model.json")
            weights = [1.0, -2.0, 0.5, 0.0, 0.3]
            bias = -0.1
            metrics = {"train": {"f1": 0.9}, "test": {"f1": 0.85}}
            trainer.save_model(weights, bias, metrics, path=path)
            w2, b2, thr = trainer.load_model(path=path)
            self.assertEqual(w2, weights)
            self.assertAlmostEqual(b2, bias)

    def test_saved_file_is_valid_json(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "model.json")
            trainer.save_model([1.0], 0.0, {}, path=path)
            with open(path) as f:
                obj = json.load(f)
            self.assertIn("weights", obj)
            self.assertIn("bias", obj)
            self.assertIn("feature_names", obj)


class TestTrainModelPipeline(unittest.TestCase):
    def test_synthetic_fallback_trains_successfully(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "model.json")
            with patch("branch_event_telemetry.get_historical_branch_events", return_value=[]):
                result = trainer.train_model_pipeline(
                    use_synthetic_fallback=True,
                    model_path=path,
                )
        self.assertNotIn("error", result)
        self.assertTrue(result.get("synthetic"))
        self.assertIn("model_path", result)
        self.assertIn("f1", result)

    def test_f1_meets_minimum_threshold_on_synthetic_data(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "model.json")
            with patch("branch_event_telemetry.get_historical_branch_events", return_value=[]):
                result = trainer.train_model_pipeline(
                    use_synthetic_fallback=True,
                    model_path=path,
                )
        self.assertTrue(result.get("meets_threshold"),
                        f"F1 {result.get('f1'):.3f} did not meet 0.7 threshold")
        self.assertGreaterEqual(result["f1"], 0.7)

    def test_no_fallback_returns_error_when_no_data(self):
        with patch("branch_event_telemetry.get_historical_branch_events", return_value=[]):
            result = trainer.train_model_pipeline(use_synthetic_fallback=False)
        self.assertIn("error", result)

    def test_model_file_is_written(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "model.json")
            with patch("branch_event_telemetry.get_historical_branch_events", return_value=[]):
                result = trainer.train_model_pipeline(
                    use_synthetic_fallback=True,
                    model_path=path,
                )
            self.assertTrue(os.path.isfile(path))

    def test_real_data_path(self):
        events = pipeline.generate_synthetic_data(n=100)
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "model.json")
            with patch("branch_event_telemetry.get_historical_branch_events", return_value=events):
                result = trainer.train_model_pipeline(model_path=path)
        self.assertNotIn("error", result)
        self.assertFalse(result.get("synthetic"))
        self.assertGreaterEqual(result["f1"], 0.7)


if __name__ == "__main__":
    unittest.main()
