#!/usr/bin/env python3
"""Tests for runner/bots/de_chancery.py — build + admit checks."""
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bots"))

# Stub db and model_gateway before importing the module
import types

_db_mod = types.ModuleType("db")
_db_mod.query = lambda *a, **kw: []
_db_mod.insert = lambda *a, **kw: None
sys.modules.setdefault("db", _db_mod)

_mg_mod = types.ModuleType("model_gateway")
_mg_mod.complete = lambda *a, **kw: {"text": '{"rfis":[],"overall_risk":"low","summary":"ok"}'}
sys.modules.setdefault("model_gateway", _mg_mod)

from bots import de_chancery


def test_corpus_filter_matches():
    assert de_chancery.corpus_filter("Delaware Court of Chancery opinion")
    assert de_chancery.corpus_filter("Del. Ch. ruling on fiduciary duty")
    assert de_chancery.corpus_filter("C.A. No. 12345")


def test_corpus_filter_rejects():
    assert not de_chancery.corpus_filter("contract dispute in Texas")
    assert not de_chancery.corpus_filter("")
    assert not de_chancery.corpus_filter(None)


def test_build():
    result = de_chancery.build()
    assert result["built"] is True
    assert result["role"] == "reviewer"
    assert result["target_app"] == "apparently"
    assert result["priors_tag"] == "de_chancery"


def test_admit_empty():
    result = de_chancery.admit("")
    assert result["admitted"] is False


def test_admit_non_chancery():
    result = de_chancery.admit("A Texas contract dispute")
    assert result["admitted"] is False


def test_admit_chancery():
    result = de_chancery.admit("Delaware Court of Chancery opinion on fiduciary duty")
    assert result["admitted"] is True


def test_score_rfi_recall_perfect():
    golden = [{"category": "fiduciary_duty"}, {"category": "entire_fairness"}]
    predicted = [{"category": "fiduciary_duty"}, {"category": "entire_fairness"}, {"category": "standing"}]
    assert de_chancery.score_rfi_recall(predicted, golden) == 1.0


def test_score_rfi_recall_partial():
    golden = [{"category": "fiduciary_duty"}, {"category": "entire_fairness"}]
    predicted = [{"category": "fiduciary_duty"}]
    assert de_chancery.score_rfi_recall(predicted, golden) == 0.5


def test_score_rfi_recall_empty_golden():
    assert de_chancery.score_rfi_recall([], []) == 1.0


def test_stats():
    s = de_chancery.stats()
    assert s["role"] == "reviewer"
    assert "rfi_categories" in s
    assert len(s["rfi_categories"]) > 0


def test_review_non_chancery():
    result = de_chancery.review("A Texas contract dispute")
    assert result["reviewed"] is False


def test_review_chancery():
    result = de_chancery.review("Delaware Court of Chancery opinion on merger")
    assert result["reviewed"] is True
    assert "response" in result
