"""Security and metadata handling tests for pricing grid reconstruction.

This module tests the critical security requirement: sensitive data (template IDs)
must not be exposed through serialization by default. These tests verify:

1. Template ID containment: sensitive metadata is stored internally but never
   serialized unless explicitly requested
2. Cross-grid isolation: metadata from one grid cannot leak into another
3. Tier-level access control: each tier's metadata is protected
4. Grid-level access control: grids respect the include_metadata flag
5. Authorization boundaries: only explicit include_metadata=True allows access
"""
import os
import sys
import pytest
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from pricing_grid_reconstruction import (
    PricingTier, PricingGrid, PricingGridReconstructionUtil,
)


class TestTemplateIDSecurity:
    """Verify that template IDs and sensitive metadata are properly contained."""

    def test_tier_template_id_stored_internally_not_exposed_default(self):
        """Template ID must be internally stored but never exposed by default."""
        tier = PricingTier(
            name="secure_tier",
            min_units=1,
            max_units=100,
            unit_price=10.0,
            metadata={"template_id": "tpl-secret-abc123"}
        )

        # Internal access should work
        assert tier.metadata["template_id"] == "tpl-secret-abc123"

        # Default serialization must NOT include metadata
        tier_dict = tier.to_dict(include_metadata=False)
        assert "metadata" not in tier_dict
        assert "template_id" not in tier_dict
        assert "tpl-secret-abc123" not in json.dumps(tier_dict)

    def test_tier_template_id_accessible_only_with_explicit_flag(self):
        """Template ID must only be accessible when include_metadata=True."""
        tier = PricingTier(
            name="premium",
            min_units=100,
            max_units=None,
            unit_price=5.0,
            metadata={
                "template_id": "tpl-enterprise-xyz",
                "region": "us-west-2"
            }
        )

        # Explicit request required for metadata access
        tier_with_meta = tier.to_dict(include_metadata=True)
        assert "metadata" in tier_with_meta
        assert tier_with_meta["metadata"]["template_id"] == "tpl-enterprise-xyz"

    def test_grid_template_ids_isolated_in_each_tier(self):
        """Template IDs in different tiers must remain isolated."""
        grid = PricingGrid(
            product_id="secure-product",
            tiers=[
                PricingTier(
                    "tier1", 1, 50, 10.0,
                    metadata={"template_id": "tpl-001", "tier_name": "basic"}
                ),
                PricingTier(
                    "tier2", 51, 100, 5.0,
                    metadata={"template_id": "tpl-002", "tier_name": "pro"}
                ),
            ]
        )

        # Default serialization should not include any template IDs
        serialized = grid.to_dict(include_metadata=False)
        full_json = json.dumps(serialized)
        assert "tpl-001" not in full_json
        assert "tpl-002" not in full_json
        assert "template_id" not in full_json

        # Each tier's metadata should be isolated when explicitly requested
        serialized_full = grid.to_dict(include_metadata=True)
        assert serialized_full["tiers"][0]["metadata"]["template_id"] == "tpl-001"
        assert serialized_full["tiers"][1]["metadata"]["template_id"] == "tpl-002"

    def test_grid_serialization_respects_include_metadata_flag(self):
        """Grid.to_dict() must respect include_metadata flag for all tiers."""
        raw = [
            {
                "name": "basic",
                "min_units": 1,
                "max_units": 50,
                "unit_price": 2.0,
                "metadata": {"template_id": "secret-1", "notes": "public"}
            },
            {
                "name": "pro",
                "min_units": 51,
                "max_units": None,
                "unit_price": 1.0,
                "metadata": {"template_id": "secret-2", "notes": "public"}
            }
        ]
        grid = PricingGridReconstructionUtil.from_raw_tiers("secure", raw)

        # Without include_metadata
        safe = grid.to_dict(include_metadata=False)
        for tier_dict in safe["tiers"]:
            assert "metadata" not in tier_dict
            assert "template_id" not in tier_dict
            assert "secret-1" not in json.dumps(tier_dict)
            assert "secret-2" not in json.dumps(tier_dict)

        # With include_metadata
        full = grid.to_dict(include_metadata=True)
        assert full["tiers"][0]["metadata"]["template_id"] == "secret-1"
        assert full["tiers"][1]["metadata"]["template_id"] == "secret-2"

    def test_multiple_sensitive_fields_in_metadata(self):
        """Multiple sensitive fields must all be protected by include_metadata."""
        tier = PricingTier(
            "multi-secret",
            min_units=1,
            max_units=100,
            unit_price=5.0,
            metadata={
                "template_id": "tpl-xyz",
                "api_key": "sk-secret-key-123",
                "webhook_url": "https://internal.example.com/hook",
                "public_tag": "visible",
            }
        )

        # Default serialization must exclude all fields in metadata
        safe = tier.to_dict(include_metadata=False)
        assert "metadata" not in safe
        safe_json = json.dumps(safe)
        assert "template_id" not in safe_json
        assert "api_key" not in safe_json
        assert "webhook_url" not in safe_json
        assert "sk-secret-key-123" not in safe_json
        # Note: public_tag should also not be exposed by default
        # (metadata containment, not field-level filtering)

        # Explicit request provides access to all fields
        full = tier.to_dict(include_metadata=True)
        assert full["metadata"]["template_id"] == "tpl-xyz"
        assert full["metadata"]["api_key"] == "sk-secret-key-123"
        assert full["metadata"]["public_tag"] == "visible"


class TestMetadataAccessControl:
    """Test that metadata access is properly gated by authorization flags."""

    def test_unauthorized_serialization_fails_no_default_leakage(self):
        """Default serialization (implicit unauthorized) must not expose metadata."""
        # Simulate unauthorized caller - no include_metadata flag
        tier = PricingTier(
            "protected",
            1, 100, 1.0,
            metadata={"template_id": "protected-value"}
        )

        # Without explicit authorization flag
        result = tier.to_dict()  # No include_metadata parameter
        assert "metadata" not in result

    def test_grid_unauthorized_serialization_blocks_all_tier_metadata(self):
        """Grid default serialization must block metadata in all tiers."""
        grid = PricingGrid(
            "multi-tier-secure",
            tiers=[
                PricingTier("t1", 1, 50, 1.0, metadata={"secret": "s1"}),
                PricingTier("t2", 51, 100, 0.5, metadata={"secret": "s2"}),
                PricingTier("t3", 101, None, 0.1, metadata={"secret": "s3"}),
            ]
        )

        result = grid.to_dict()  # No authorization
        for tier_dict in result["tiers"]:
            assert "metadata" not in tier_dict

    def test_explicit_include_metadata_false_blocks_access(self):
        """Explicit include_metadata=False must block metadata access."""
        tier = PricingTier(
            "explicit-deny",
            1, 100, 1.0,
            metadata={"sensitive": "data"}
        )

        # Explicitly False should block
        result = tier.to_dict(include_metadata=False)
        assert "metadata" not in result
        assert "sensitive" not in json.dumps(result)

    def test_explicit_include_metadata_true_grants_access(self):
        """Explicit include_metadata=True must grant metadata access."""
        tier = PricingTier(
            "explicit-grant",
            1, 100, 1.0,
            metadata={"data": "exposed"}
        )

        result = tier.to_dict(include_metadata=True)
        assert "metadata" in result
        assert result["metadata"]["data"] == "exposed"


class TestCrossGridMetadataIsolation:
    """Test that metadata from one grid cannot leak into another."""

    def test_merge_grids_does_not_cross_contaminate_metadata(self):
        """merge_grids must not mix metadata between source grids."""
        g1 = PricingGrid(
            "product-a",
            tiers=[
                PricingTier("t1", 1, 50, 10.0, metadata={"template_id": "tpl-a1"}),
            ]
        )
        g2 = PricingGrid(
            "product-a",
            tiers=[
                PricingTier("t1", 1, 50, 10.0, metadata={"template_id": "tpl-a1"}),
                PricingTier("t2", 51, None, 5.0, metadata={"template_id": "tpl-a2"}),
            ]
        )

        merged = PricingGridReconstructionUtil.merge_grids([g1, g2])

        # Merged grid's default serialization should not expose any template IDs
        safe_json = json.dumps(merged.to_dict(include_metadata=False))
        assert "tpl-a1" not in safe_json
        assert "tpl-a2" not in safe_json

    def test_multiple_grids_metadata_isolation(self):
        """Processing multiple grids must not allow metadata cross-leakage."""
        grids = [
            PricingGrid(
                f"product-{i}",
                tiers=[
                    PricingTier(
                        f"tier-{i}",
                        1, 100, float(i),
                        metadata={"template_id": f"tpl-secret-{i}"}
                    )
                ]
            )
            for i in range(3)
        ]

        # Each grid's default serialization must be isolated
        for grid in grids:
            safe = grid.to_dict(include_metadata=False)
            safe_str = json.dumps(safe)

            # This grid's secret should not be present
            for i in range(3):
                assert f"tpl-secret-{i}" not in safe_str


class TestMetadataPreservationWithSecurityGating:
    """Test that metadata is preserved but securely gated."""

    def test_metadata_preserved_internally_accessible_when_authorized(self):
        """Metadata must be preserved internally and accessible when authorized."""
        raw = [
            {
                "name": "tier",
                "min_units": 1,
                "max_units": 100,
                "unit_price": 5.0,
                "metadata": {
                    "template_id": "internal-tpl-001",
                    "version": "2.0",
                    "region": "us-east-1",
                }
            }
        ]
        grid = PricingGridReconstructionUtil.from_raw_tiers("test", raw)

        # Internal access works
        tier = grid.tiers[0]
        assert tier.metadata["template_id"] == "internal-tpl-001"
        assert tier.metadata["version"] == "2.0"

        # Default serialization blocks
        default = tier.to_dict(include_metadata=False)
        assert "metadata" not in default

        # Authorized serialization grants access
        authorized = tier.to_dict(include_metadata=True)
        assert authorized["metadata"]["template_id"] == "internal-tpl-001"
        assert authorized["metadata"]["version"] == "2.0"

    def test_empty_metadata_safe_handling(self):
        """Empty or missing metadata must be safely handled."""
        tier1 = PricingTier("no-meta", 1, 100, 1.0)  # No metadata provided
        tier2 = PricingTier("empty-meta", 1, 100, 1.0, metadata={})

        # Both should serialize safely
        result1 = tier1.to_dict(include_metadata=False)
        assert "metadata" not in result1

        result2 = tier2.to_dict(include_metadata=False)
        assert "metadata" not in result2

        # Authorized access should handle empty gracefully
        result1_auth = tier1.to_dict(include_metadata=True)
        assert result1_auth["metadata"] == {}

        result2_auth = tier2.to_dict(include_metadata=True)
        assert result2_auth["metadata"] == {}


class TestBoundarySecurityScenarios:
    """Test security at system boundaries."""

    def test_json_serialization_no_leakage_through_standard_library(self):
        """json.dumps() of default serialization must not contain template IDs."""
        tier = PricingTier(
            "boundary-test",
            1, 100, 5.0,
            metadata={"template_id": "secret-xyz-123"}
        )

        unsafe_json = json.dumps(tier.to_dict(include_metadata=False))
        safe_json = json.dumps(tier.to_dict(include_metadata=True))

        assert "secret-xyz-123" not in unsafe_json
        assert "secret-xyz-123" in safe_json

    def test_grid_api_boundary_metadata_gating(self):
        """Grid.to_dict() at API boundary must gate metadata properly."""
        grid = PricingGrid(
            "api-test",
            tiers=[
                PricingTier("api-tier", 1, 100, 5.0,
                           metadata={"api_token": "sk-live-123456"})
            ]
        )

        # Simulate API response (default serialization)
        api_response = grid.to_dict(include_metadata=False)
        api_json = json.dumps(api_response)

        # API response must not leak credentials
        assert "sk-live-123456" not in api_json
        assert "api_token" not in api_json

    def test_internal_to_external_conversion_maintains_security(self):
        """Converting internal representation to external format maintains security."""
        # Internal representation with sensitive data
        internal = PricingGrid(
            "internal-product",
            tiers=[
                PricingTier(
                    "secure-tier",
                    1, 100, 10.0,
                    metadata={
                        "template_id": "internal-tpl",
                        "db_connection": "postgresql://...",
                        "billing_secret": "bs-secret"
                    }
                )
            ]
        )

        # External representation (default, unauthorized)
        external = internal.to_dict(include_metadata=False)

        # Verify no secrets in external form
        ext_str = json.dumps(external)
        assert "internal-tpl" not in ext_str
        assert "postgresql" not in ext_str
        assert "bs-secret" not in ext_str

        # Public fields should still be available
        assert external["product_id"] == "internal-product"
        assert external["tiers"][0]["name"] == "secure-tier"
        assert external["tiers"][0]["unit_price"] == 10.0


class TestSecurityWithPricingCalculations:
    """Ensure pricing calculations don't expose metadata."""

    def test_total_cost_calculation_independent_of_metadata(self):
        """Pricing calculations must work regardless of metadata presence/absence."""
        grid_with_meta = PricingGrid(
            "with-metadata",
            tiers=[
                PricingTier("t1", 1, 10, 10.0,
                           metadata={"template_id": "secret1"}),
                PricingTier("t2", 11, None, 5.0,
                           metadata={"template_id": "secret2"}),
            ]
        )

        grid_without_meta = PricingGrid(
            "without-metadata",
            tiers=[
                PricingTier("t1", 1, 10, 10.0),
                PricingTier("t2", 11, None, 5.0),
            ]
        )

        # Same pricing regardless of metadata
        assert grid_with_meta.total_cost(15) == grid_without_meta.total_cost(15)

    def test_tier_selection_independent_of_metadata(self):
        """Tier selection must work without exposing metadata."""
        tier = PricingTier(
            "selected",
            50, 100, 5.0,
            metadata={"template_id": "secret"}
        )

        # Selecting tier shouldn't expose its metadata
        grid = PricingGrid("test", tiers=[tier])
        selected = grid.tier_for_units(75)

        assert selected.name == "selected"
        assert selected.metadata["template_id"] == "secret"  # Internal access OK

        # But serialization respects the gate
        selected_dict = selected.to_dict(include_metadata=False)
        assert "metadata" not in selected_dict


class TestRegressionSecurityChecks:
    """Regression tests ensuring security isn't bypassed."""

    def test_no_metadata_in_tier_capacity_calculation(self):
        """_tier_capacity calculation must not expose metadata."""
        tier = PricingTier(
            "capacity-test",
            1, 100, 1.0,
            metadata={"secret_data": "should-not-appear"}
        )

        # Internal capacity calculation should work
        capacity = PricingTier._tier_capacity(tier)
        assert capacity == 100

        # But doesn't expose secrets
        assert tier.to_dict(include_metadata=False).get("metadata") is None

    def test_no_metadata_in_cost_calculation(self):
        """Cost calculations must not include metadata in results."""
        tier = PricingTier(
            "cost-test",
            1, 100, 5.0,
            flat_fee=10.0,
            metadata={"internal_id": "internal"}
        )

        cost = tier.cost_for_units(50)
        # Cost should be numeric, not a dict with metadata
        assert isinstance(cost, float)
        assert cost == 260.0  # 10.0 + (50 * 5.0)

    def test_validation_doesnt_expose_metadata(self):
        """validate_grid() must not expose metadata in validation results."""
        grid = PricingGrid(
            "validation-test",
            tiers=[
                PricingTier("tier1", 1, 50, 1.0,
                           metadata={"secret": "value"}),
            ]
        )

        valid, issues = PricingGridReconstructionUtil.validate_grid(grid)

        # Issues list should be clean strings, not containing metadata
        issues_str = " ".join(issues)
        assert "secret" not in issues_str
        assert "metadata" not in issues_str
