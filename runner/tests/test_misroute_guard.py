"""Regression: the July 27-28 provider/model misroute (13x `openai 404: claude-haiku-...`).

The hole was `provider or _provider_for_model(model)` — resolution ran only when the caller
passed NO provider, so an explicit wrong provider sailed to the wrong vendor API. The guard
(`_reconcile_provider_model`) now runs unconditionally. These tests pin the contract:
model name wins on a confident mismatch; empty provider resolves as before; matched pairs are
untouched; a mismatch whose true provider has no key swaps the model instead (a coherent call
always leaves the process)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import swarm_executor as se


def test_exact_historical_404_pair_reroutes(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    p, m, note = se._reconcile_provider_model("openai", "claude-haiku-4-5-20251001")
    assert p == "claude"
    assert m == "claude-haiku-4-5-20251001"
    assert "misroute-guard" in note


def test_empty_provider_resolves_by_model():
    p, m, note = se._reconcile_provider_model("", "gpt-5.4-mini")
    assert p == "openai" and m == "gpt-5.4-mini" and note == ""


def test_matched_pair_untouched():
    p, m, note = se._reconcile_provider_model("deepseek", "deepseek-v4-flash")
    assert (p, m, note) == ("deepseek", "deepseek-v4-flash", "")


def test_true_provider_key_absent_swaps_model(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    p, m, note = se._reconcile_provider_model("openai", "gemini-3-flash")
    assert p == "openai"
    assert m in se.PROVIDERS["openai"]["models"].values()
    assert "swapped" in note


def test_sonnet_pair_reroutes(monkeypatch):
    """The second model name from the same log burst."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    p, m, _ = se._reconcile_provider_model("openai", "claude-sonnet-4-6")
    assert p == "claude"
