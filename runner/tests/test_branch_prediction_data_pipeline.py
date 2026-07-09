"""Unit tests for branch_prediction_data_pipeline."""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import branch_prediction_config as config
import branch_prediction_data_pipeline as pipeline


class TestExtractFeatures(unittest.TestCase):
    def test_output_length_matches_feature_names(self):
        features = pipeline.extract_features({
            "branch_age_days": 10,
            "days_since_activity": 3,
            "task_state_queued": 1,
            "task_state_running": 0,
            "project_queue_depth_norm": 0.3,
        })
        self.assertEqual(len(features), len(config.FEATURE_NAMES))

    def test_features_are_normalized_0_to_1(self):
        features = pipeline.extract_features({
            "branch_age_days": config.MAX_AGE_DAYS,
            "days_since_activity": config.MAX_AGE_DAYS,
            "task_state_queued": 1,
            "task_state_running": 1,
            "project_queue_depth_norm": 1.0,
        })
        for f in features:
            self.assertGreaterEqual(f, 0.0)
            self.assertLessEqual(f, 1.0)

    def test_age_clips_at_max(self):
        features_max = pipeline.extract_features({"branch_age_days": 1000})
        features_90 = pipeline.extract_features({"branch_age_days": config.MAX_AGE_DAYS})
        self.assertAlmostEqual(features_max[0], features_90[0])

    def test_missing_fields_default_to_zero(self):
        features = pipeline.extract_features({})
        self.assertEqual(features, [0.0, 0.0, 0.0, 0.0, 0.0])

    def test_queued_flag_propagates(self):
        feat_q = pipeline.extract_features({"task_state_queued": 1})
        feat_nq = pipeline.extract_features({"task_state_queued": 0})
        self.assertEqual(feat_q[2], 1.0)
        self.assertEqual(feat_nq[2], 0.0)


class TestTrainTestSplit(unittest.TestCase):
    def _make_events(self, n):
        return [{"task_id": f"t{i}", "label": i % 2} for i in range(n)]

    def test_total_count_preserved(self):
        events = self._make_events(100)
        train, test = pipeline.train_test_split(events, holdout_frac=0.2)
        self.assertEqual(len(train) + len(test), 100)

    def test_split_ratio(self):
        events = self._make_events(100)
        train, test = pipeline.train_test_split(events, holdout_frac=0.2)
        self.assertEqual(len(test), 20)
        self.assertEqual(len(train), 80)

    def test_deterministic(self):
        events = self._make_events(50)
        train1, test1 = pipeline.train_test_split(events, holdout_frac=0.2)
        train2, test2 = pipeline.train_test_split(events, holdout_frac=0.2)
        self.assertEqual([e["task_id"] for e in train1], [e["task_id"] for e in train2])

    def test_empty_input(self):
        train, test = pipeline.train_test_split([])
        self.assertEqual(train, [])
        self.assertEqual(test, [])

    def test_single_event_goes_to_train(self):
        train, test = pipeline.train_test_split([{"task_id": "x"}])
        self.assertEqual(len(train), 1)
        self.assertEqual(len(test), 0)


class TestGenerateSyntheticData(unittest.TestCase):
    def test_returns_n_events(self):
        events = pipeline.generate_synthetic_data(n=50)
        self.assertEqual(len(events), 50)

    def test_balanced_classes(self):
        events = pipeline.generate_synthetic_data(n=100)
        labels = [e["label"] for e in events]
        self.assertEqual(labels.count(1), 50)
        self.assertEqual(labels.count(0), 50)

    def test_needed_events_are_fresh(self):
        events = pipeline.generate_synthetic_data(n=100)
        for e in events:
            if e["label"] == 1:
                self.assertLess(e["branch_age_days"], 10.0)
                self.assertLess(e["days_since_activity"], 10.0)

    def test_stale_events_are_old(self):
        events = pipeline.generate_synthetic_data(n=100)
        for e in events:
            if e["label"] == 0:
                self.assertGreater(e["branch_age_days"], 15.0)
                self.assertGreater(e["days_since_activity"], 15.0)

    def test_deterministic_with_same_seed(self):
        e1 = pipeline.generate_synthetic_data(n=20, seed=7)
        e2 = pipeline.generate_synthetic_data(n=20, seed=7)
        self.assertEqual([e["branch_age_days"] for e in e1],
                          [e["branch_age_days"] for e in e2])


class TestPrepareTrainingData(unittest.TestCase):
    def test_returns_four_lists(self):
        events = pipeline.generate_synthetic_data(n=50)
        with patch("branch_event_telemetry.get_historical_branch_events", return_value=events):
            result = pipeline.prepare_training_data()
        self.assertEqual(len(result), 4)
        X_train, y_train, X_test, y_test = result
        self.assertIsInstance(X_train, list)
        self.assertIsInstance(y_train, list)

    def test_feature_vectors_correct_length(self):
        events = pipeline.generate_synthetic_data(n=50)
        with patch("branch_event_telemetry.get_historical_branch_events", return_value=events):
            X_train, y_train, X_test, y_test = pipeline.prepare_training_data()
        for x in X_train + X_test:
            self.assertEqual(len(x), len(config.FEATURE_NAMES))

    def test_insufficient_data_returns_empty(self):
        with patch("branch_event_telemetry.get_historical_branch_events", return_value=[]):
            result = pipeline.prepare_training_data()
        self.assertEqual(result, ([], [], [], []))

    def test_labels_are_binary(self):
        events = pipeline.generate_synthetic_data(n=50)
        with patch("branch_event_telemetry.get_historical_branch_events", return_value=events):
            _, y_train, _, y_test = pipeline.prepare_training_data()
        for y in y_train + y_test:
            self.assertIn(y, (0, 1))


if __name__ == "__main__":
    unittest.main()
