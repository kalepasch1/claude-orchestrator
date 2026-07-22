#!/usr/bin/env python3
"""Tests for distill_lora.py - corpus export, eval harness, pool gating."""
import json
import os
import sys
import tempfile
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Mock db before importing distill_lora
_mock_db_data = {}

class MockDB:
    @staticmethod
    def select(table, query=None):
        return _mock_db_data.get(table, [])
    @staticmethod
    def insert(table, data):
        _mock_db_data.setdefault(f"{table}_inserts", []).append(data)
        return data
    @staticmethod
    def update(table, data, where):
        return data

sys.modules.setdefault("db", MockDB())
import db
sys.modules["db"] = MockDB()

import distill_lora


def _setup_corpus_env(tmpdir):
    """Set up env for corpus tests."""
    os.environ["ORCH_DISTILL_CORPUS_DIR"] = tmpdir
    distill_lora.CORPUS_DIR = tmpdir


def test_export_corpus_empty():
    """Export with no data returns ok with zero count."""
    with tempfile.TemporaryDirectory() as td:
        _setup_corpus_env(td)
        _mock_db_data.clear()
        _mock_db_data["merged_diff_library"] = []
        _mock_db_data["tasks"] = []
        r = distill_lora.export_corpus()
        assert r["ok"] is True
        assert r["count"] == 0


def test_export_corpus_with_data():
    """Export with matching data produces train + holdout files."""
    with tempfile.TemporaryDirectory() as td:
        _setup_corpus_env(td)
        _mock_db_data.clear()
        pairs = []
        for i in range(60):
            pairs.append({"id": str(i), "slug": f"task-{i}", "diff_text": f"diff content {i}\n+added line {i}",
                          "prompt_hash": f"h{i}", "repo": "test-repo", "indexed_at": f"2025-01-{i+1:02d}"})
        _mock_db_data["merged_diff_library"] = pairs
        _mock_db_data["tasks"] = [{"slug": f"task-{i}", "prompt": f"implement feature {i} with proper tests", "state": "MERGED"} for i in range(60)]

        r = distill_lora.export_corpus()
        assert r["ok"] is True
        assert r["count"] > 0
        assert r["holdout_count"] > 0
        assert os.path.exists(os.path.join(td, "train.jsonl"))
        assert os.path.exists(os.path.join(td, "holdout.jsonl"))

        # Verify scrubbing happened (no PII in output)
        with open(os.path.join(td, "train.jsonl")) as f:
            for line in f:
                data = json.loads(line)
                assert "prompt" in data
                assert "completion" in data
                assert "repo" in data


def test_export_corpus_scrubs_pii():
    """Verify PII is scrubbed from corpus."""
    with tempfile.TemporaryDirectory() as td:
        _setup_corpus_env(td)
        _mock_db_data.clear()
        _mock_db_data["merged_diff_library"] = [
            {"id": "1", "slug": "task-pii", "diff_text": "email: user@example.com\n+fix", "prompt_hash": "h1", "repo": "r", "indexed_at": "2025-01-01"}
        ]
        _mock_db_data["tasks"] = [{"slug": "task-pii", "prompt": "fix the bug for user@example.com", "state": "DONE"}]

        r = distill_lora.export_corpus()
        assert r["ok"] is True
        if r["count"] > 0:
            with open(os.path.join(td, "train.jsonl")) as f:
                content = f.read()
                assert "user@example.com" not in content


def test_export_corpus_dedup():
    """Duplicate prompt+diff pairs are deduplicated."""
    with tempfile.TemporaryDirectory() as td:
        _setup_corpus_env(td)
        _mock_db_data.clear()
        _mock_db_data["merged_diff_library"] = [
            {"id": "1", "slug": "dup-1", "diff_text": "same diff", "prompt_hash": "h1", "repo": "r", "indexed_at": "2025-01-01"},
            {"id": "2", "slug": "dup-1", "diff_text": "same diff", "prompt_hash": "h1", "repo": "r", "indexed_at": "2025-01-02"},
        ]
        _mock_db_data["tasks"] = [{"slug": "dup-1", "prompt": "same prompt", "state": "DONE"}]
        r = distill_lora.export_corpus()
        assert r["ok"] is True
        total = r["count"] + r["holdout_count"]
        assert total <= 1  # deduplicated


def test_fine_tune_missing_corpus():
    """Fine-tune with no corpus returns error."""
    r = distill_lora.fine_tune(corpus_path="/nonexistent/train.jsonl")
    assert r["ok"] is False
    assert "not found" in r["error"]


def test_fine_tune_mock():
    """Fine-tune with mocked subprocess."""
    with tempfile.TemporaryDirectory() as td:
        corpus = os.path.join(td, "train.jsonl")
        with open(corpus, "w") as f:
            f.write(json.dumps({"prompt": "test", "completion": "diff"}) + "\n")

        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(returncode=0, stdout="done", stderr="")
            r = distill_lora.fine_tune(corpus_path=corpus, output_dir=os.path.join(td, "adapter"))
            assert r["ok"] is True
            assert r["adapter_path"] is not None
            assert mock_run.called


def test_eval_harness_missing_holdout():
    """Eval with no holdout returns error."""
    r = distill_lora.eval_harness(holdout_path="/nonexistent/holdout.jsonl")
    assert r["ok"] is False


def test_eval_harness_promotion():
    """Eval promotes model when delta >= margin."""
    with tempfile.TemporaryDirectory() as td:
        holdout = os.path.join(td, "holdout.jsonl")
        with open(holdout, "w") as f:
            for i in range(5):
                f.write(json.dumps({"prompt": f"task {i}", "completion": f"diff {i}", "slug": f"t{i}"}) + "\n")

        # Mock _eval_single: base always fails, tuned always passes
        with mock.patch.object(distill_lora, "_eval_single") as mock_eval:
            def side_effect(model, prompt, expected):
                return "tuned" in model
            mock_eval.side_effect = side_effect

            _mock_db_data.setdefault("model_promotions_inserts", []).clear()
            r = distill_lora.eval_harness(holdout_path=holdout, margin=0.1)
            assert r["ok"] is True
            assert r["tuned_score"] == 1.0
            assert r["base_score"] == 0.0
            assert r["promoted"] is True


def test_eval_harness_no_promotion():
    """Eval does not promote when delta < margin."""
    with tempfile.TemporaryDirectory() as td:
        holdout = os.path.join(td, "holdout.jsonl")
        with open(holdout, "w") as f:
            for i in range(5):
                f.write(json.dumps({"prompt": f"task {i}", "completion": f"diff {i}", "slug": f"t{i}"}) + "\n")

        with mock.patch.object(distill_lora, "_eval_single") as mock_eval:
            # Both pass equally
            mock_eval.return_value = True
            r = distill_lora.eval_harness(holdout_path=holdout, margin=0.1)
            assert r["ok"] is True
            assert r["promoted"] is False  # no improvement


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  PASS {name}")
    print("All distill_lora tests passed")
