"""Tests for runner.feature_map — cross-app critical feature map."""

import json
import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from feature_map import (
    FEATURE_MAP,
    KNOWN_APPS,
    PRIVACY_TIERS,
    REQUIRED_SURFACE_KEYS,
    apps_covered,
    export_json,
    get_feature_map,
    get_surface,
    surfaces_for_app,
    validate_map,
)


# ── Schema shape ────────────────────────────────────────────────────

class TestSchemaShape:
    """Every surface must have the required keys with correct types."""

    def test_all_surfaces_have_required_keys(self):
        for name, cfg in FEATURE_MAP.items():
            missing = REQUIRED_SURFACE_KEYS - set(cfg.keys())
            assert not missing, f"{name} missing {missing}"

    def test_owner_app_is_string(self):
        for name, cfg in FEATURE_MAP.items():
            assert isinstance(cfg["owner_app"], str), f"{name}.owner_app"

    def test_reusable_capabilities_is_list(self):
        for name, cfg in FEATURE_MAP.items():
            assert isinstance(cfg["reusable_capabilities"], list), f"{name}.reusable_capabilities"

    def test_proof_command_is_string(self):
        for name, cfg in FEATURE_MAP.items():
            assert isinstance(cfg["proof_command"], str), f"{name}.proof_command"

    def test_privacy_tier_is_string(self):
        for name, cfg in FEATURE_MAP.items():
            assert isinstance(cfg["privacy_tier"], str), f"{name}.privacy_tier"

    def test_propagation_eligible_is_bool(self):
        for name, cfg in FEATURE_MAP.items():
            assert isinstance(cfg["propagation_eligible"], bool), f"{name}.propagation_eligible"

    def test_validate_map_passes(self):
        errors = validate_map()
        assert errors == [], f"Validation errors: {errors}"


# ── Project coverage ────────────────────────────────────────────────

class TestProjectCoverage:
    """Every known app must own at least one surface."""
    def test_all_apps_covered(self):
        covered = apps_covered()
        for app in KNOWN_APPS:
            assert app in covered, f"App '{app}' has no surfaces"

    def test_at_least_15_surfaces(self):
        """The prompt lists 15 critical surfaces."""
        assert len(FEATURE_MAP) >= 15


# ── Privacy tier presence ───────────────────────────────────────────

class TestPrivacyTier:
    """Every surface declares a valid privacy tier."""

    def test_all_tiers_valid(self):
        for name, cfg in FEATURE_MAP.items():
            assert cfg["privacy_tier"] in PRIVACY_TIERS, (
                f"{name}: bad tier '{cfg['privacy_tier']}'"
            )

    def test_restricted_surfaces_not_propagation_eligible(self):
        """Restricted-tier surfaces should not be propagation-eligible."""
        for name, cfg in FEATURE_MAP.items():
            if cfg["privacy_tier"] == "restricted":
                assert not cfg["propagation_eligible"], (
                    f"{name}: restricted but propagation_eligible"
                )

# ── Unknown apps degrade without blocking ───────────────────────────

class TestUnknownAppDegradation:
    """Querying for an unknown app must return empty, not raise."""

    def test_surfaces_for_unknown_app_returns_empty(self):
        result = surfaces_for_app("nonexistent_app_xyz")
        assert result == {}

    def test_get_surface_unknown_returns_none(self):
        assert get_surface("totally_fake_surface") is None

    def test_validate_map_catches_unknown_owner(self):
        bad_map = {
            "test_surface": {
                "owner_app": "unknown_app",
                "reusable_capabilities": [],
                "proof_command": "true",
                "privacy_tier": "internal",
                "propagation_eligible": False,
            }
        }
        errors = validate_map(bad_map)
        assert any("unknown owner_app" in e for e in errors)


# ── Accessor sanity ─────────────────────────────────────────────────

class TestAccessors:
    def test_get_feature_map_returns_deep_copy(self):
        m1 = get_feature_map()
        m2 = get_feature_map()
        assert m1 == m2
        m1["deliberation_cade"]["owner_app"] = "MUTATED"
        assert FEATURE_MAP["deliberation_cade"]["owner_app"] != "MUTATED"

    def test_surfaces_for_orchestrator(self):
        surfs = surfaces_for_app("orchestrator")
        assert len(surfs) >= 3

    def test_export_json_valid(self):
        data = export_json()
        parsed = json.loads(data)
        assert len(parsed) == len(FEATURE_MAP)

    def test_export_json_to_file(self, tmp_path):
        out = str(tmp_path / "fmap.json")
        export_json(out)
        with open(out) as f:
            parsed = json.load(f)
        assert len(parsed) == len(FEATURE_MAP)