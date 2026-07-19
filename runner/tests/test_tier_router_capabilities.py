import os
import sys
from unittest.mock import patch


RUNNER = os.path.dirname(os.path.dirname(__file__))
if RUNNER not in sys.path:
    sys.path.insert(0, RUNNER)

import tier_router


def test_cowork_only_capability_precedes_generic_claude_calibration():
    task = {"kind": "build", "prompt": "Open the browser and verify https://example.com visually"}
    with patch.object(tier_router._router, "_kill_switch_paused", return_value=False):
        decision = tier_router.route(task)

    assert decision["coder"] == "cowork-skill"
    assert "browser_automation" in decision["skill_types"]


def test_api_fallback_requires_every_detected_capability(monkeypatch):
    required = {"code_generation", "vision"}
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test")
    monkeypatch.setenv("GEMINI_API_KEY", "test")
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    with patch("vendor_capabilities.detect_required_capabilities", return_value=required), \
         patch("vendor_capabilities.suggest_model", return_value=("gemini-2.5-flash", "tier=mid")), \
         patch("provider_failover_sla.is_demoted", return_value=False), \
         patch("qpd_bandit.best_for_capabilities", return_value=(None, None, "no signal")):
        decision = tier_router._router._pick_api({"kind": "build"}, "mid", "test")

    # DeepSeek is cheaper but lacks vision; capability-complete routing must skip it.
    assert decision["provider"] == "gemini"
    assert decision["model"] == "gemini-2.5-flash"


def test_learned_google_alias_is_validated_against_gemini_capabilities(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test")
    required = {"code_generation", "vision"}
    with patch("vendor_capabilities.detect_required_capabilities", return_value=required), \
         patch("qpd_bandit.best_for_capabilities",
               return_value=("google", "gemini-3.5-flash", "learned winner")):
        decision = tier_router._router._pick_api({"kind": "build"}, "mid", "test")

    assert decision["provider"] == "gemini"
    assert decision["model"] == "gemini-3.5-flash"
