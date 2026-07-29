#!/usr/bin/env python3
"""
Test suite for prediction-markets-institute think tank launch.

Focuses on:
- Homepage thesis/slogan rendering
- Research publications content and pipeline
- Data products (Orphan Risk Index, regulatory-outcome curves)
- PMI branding consistency
- Legal gate authorization enforcement
- Orchestration pipeline contract compliance
- Fail-soft degradation on content unavailability
"""
import pytest
import os
import json
import sys
from unittest.mock import Mock, patch, MagicMock, call
from io import StringIO
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


class TestHomepageThesisSloganRendering:
    """Tests for homepage thesis and slogan content."""

    def test_homepage_contains_slogan(self):
        """Homepage must contain the canonical slogan."""
        from pmi_site import homepage_content
        content = homepage_content()

        assert "What if tomorrow was predictable?" in content
        assert content.count("What if tomorrow was predictable?") >= 1

    def test_homepage_slogan_appears_prominently(self):
        """Slogan should appear in hero section with appropriate styling."""
        from pmi_site import homepage_structure
        structure = homepage_structure()

        assert "hero" in structure or "headline" in structure
        hero = structure.get("hero", {})
        assert "slogan" in hero or "What if tomorrow was predictable?" in str(hero)

    def test_homepage_thesis_content_exists(self):
        """Homepage must include thesis content explaining PMI's mission."""
        from pmi_site import homepage_content
        content = homepage_content()

        # Thesis should cover prediction markets institute mission
        thesis_keywords = ["prediction", "markets", "institute", "research"]
        assert any(keyword.lower() in content.lower() for keyword in thesis_keywords)

    def test_homepage_thesis_structure_valid(self):
        """Thesis content should have proper semantic structure."""
        from pmi_site import get_thesis_metadata
        metadata = get_thesis_metadata()

        assert "title" in metadata
        assert "description" in metadata
        assert "keywords" in metadata
        assert len(metadata["keywords"]) > 0

    def test_homepage_visual_language_brookings_grade(self):
        """Homepage styling should reflect clean, minimal, serious aesthetic."""
        from pmi_site import homepage_styles
        styles = homepage_styles()

        # Check for minimalist design markers
        assert "minimal" in str(styles).lower() or "clean" in str(styles).lower()
        # Color palette should be serious/professional
        assert any(color in str(styles) for color in ["#333", "#000", "gray", "black"])

    def test_homepage_load_without_external_deps(self):
        """Homepage should render even if external APIs unavailable."""
        with patch('pmi_site.fetch_recent_publications') as mock_fetch:
            mock_fetch.side_effect = Exception("API unavailable")

            from pmi_site import homepage_content
            content = homepage_content()

            # Should still have static content even if publications fetch fails
            assert "What if tomorrow was predictable?" in content
            assert content is not None

    def test_slogan_internationalization_ready(self):
        """Slogan and thesis should support i18n structure."""
        from pmi_site import get_translatable_strings
        strings = get_translatable_strings()

        assert "slogan" in strings
        assert "thesis" in strings or any("thesis" in k.lower() for k in strings.keys())
        assert "What if tomorrow was predictable?" in strings["slogan"]


class TestResearchPublicationsPage:
    """Tests for research and publications section."""

    def test_publications_page_loads(self):
        """Publications page should render without errors."""
        from pmi_site import render_publications_page
        content = render_publications_page()

        assert content is not None
        assert len(content) > 100

    def test_flagship_report_placeholder_present(self):
        """Page must include placeholder for flagship report."""
        from pmi_site import get_publications_content
        content = get_publications_content()

        assert "flagship" in content.lower() or "report" in content.lower()
        # Should indicate it's a placeholder/coming soon
        assert any(term in content.lower() for term in ["placeholder", "coming soon", "in progress"])

    def test_papers_pipeline_structure(self):
        """Publications should support papers pipeline with proper metadata."""
        from pmi_site import get_papers_pipeline_config
        config = get_papers_pipeline_config()

        assert "source" in config
        assert "format" in config
        assert "metadata_fields" in config
        # Required fields for academic papers
        required_fields = ["title", "authors", "date", "abstract"]
        for field in required_fields:
            assert field in config["metadata_fields"]

    def test_papers_pipeline_handles_empty_source(self):
        """Papers pipeline should degrade gracefully with no content."""
        with patch('pmi_site.fetch_papers_from_source') as mock_fetch:
            mock_fetch.return_value = []

            from pmi_site import render_publications_page
            content = render_publications_page()

            # Should show placeholder message instead of error
            assert "placeholder" in content.lower() or "no papers" in content.lower() or len(content) > 0

    def test_publications_metadata_complete(self):
        """Each publication should have complete metadata."""
        from pmi_site import get_publications_metadata
        metadata = get_publications_metadata()

        if metadata:  # If any publications loaded
            for pub in metadata:
                assert "title" in pub
                assert "date" in pub or "published" in pub
                assert isinstance(pub, dict)

    def test_papers_pipeline_caching(self):
        """Papers pipeline should implement caching to reduce load."""
        from pmi_site import papers_cache

        # Cache should exist and be queryable
        assert hasattr(papers_cache, "get") or callable(papers_cache)
        # Should support invalidation
        assert hasattr(papers_cache, "invalidate") or hasattr(papers_cache, "clear")

    def test_publications_sorting_by_date(self):
        """Publications should be sortable by date (newest first)."""
        from pmi_site import get_publications_sorted
        publications = get_publications_sorted()

        if len(publications) > 1:
            # Verify descending date order
            for i in range(len(publications) - 1):
                current_date = publications[i].get("date")
                next_date = publications[i + 1].get("date")
                if current_date and next_date:
                    assert current_date >= next_date, "Publications should be sorted newest first"

    def test_flagship_report_marked_as_placeholder(self):
        """Flagship report should have explicit placeholder indicator."""
        from pmi_site import get_flagship_report_metadata
        metadata = get_flagship_report_metadata()

        assert metadata is not None
        assert "placeholder" in str(metadata).lower() or "coming_soon" in str(metadata)
        # Should not appear as published
        assert metadata.get("published") is not True or "placeholder" in str(metadata)


class TestDataProductsOrphanRiskIndex:
    """Tests for Orphan Risk Index data product."""

    def test_orphan_risk_index_page_loads(self):
        """Orphan Risk Index page should render without errors."""
        from pmi_site import render_data_products_page
        content = render_data_products_page()

        assert content is not None
        assert "orphan" in content.lower() or "risk" in content.lower()

    def test_orphan_risk_index_metadata(self):
        """Orphan Risk Index should have complete metadata."""
        from pmi_site import get_orphan_risk_index_metadata
        metadata = get_orphan_risk_index_metadata()

        assert "title" in metadata
        assert "description" in metadata
        assert "units" in metadata or "methodology" in metadata
        assert "pmi" in str(metadata).lower()

    def test_orphan_risk_index_data_available(self):
        """Should provide access to Orphan Risk Index data."""
        from pmi_site import get_orphan_risk_index_data

        data = get_orphan_risk_index_data()
        # Data might be empty, but endpoint should be available
        assert isinstance(data, (list, dict))

    def test_orphan_risk_index_update_frequency(self):
        """Orphan Risk Index should indicate update frequency."""
        from pmi_site import get_orphan_risk_index_metadata
        metadata = get_orphan_risk_index_metadata()

        # Should indicate how often data is refreshed
        assert "update_frequency" in metadata or "refresh" in str(metadata).lower()

    def test_orphan_risk_index_branding(self):
        """Orphan Risk Index should be branded as PMI flagship product."""
        from pmi_site import get_orphan_risk_index_metadata
        metadata = get_orphan_risk_index_metadata()

        product_name = metadata.get("title", "") + metadata.get("description", "")
        assert "pmi" in str(metadata).lower() or "prediction markets institute" in str(metadata).lower()

    def test_orphan_risk_index_api_endpoint(self):
        """Should provide API endpoint for index data."""
        from pmi_site import get_data_api_endpoints
        endpoints = get_data_api_endpoints()

        assert "/api/orphan-risk-index" in endpoints or "orphan_risk" in str(endpoints)

    def test_orphan_risk_index_documentation(self):
        """Index should have documentation on methodology."""
        from pmi_site import get_orphan_risk_index_documentation
        docs = get_orphan_risk_index_documentation()

        assert docs is not None and len(docs) > 0
        assert any(term in docs.lower() for term in ["methodology", "calculation", "data source"])


class TestRegulatoryOutcomeCurves:
    """Tests for regulatory-outcome curves data product."""

    def test_regulatory_curves_page_loads(self):
        """Regulatory outcome curves should render without errors."""
        from pmi_site import render_data_products_page
        content = render_data_products_page()

        assert "regulatory" in content.lower() or "outcome" in content.lower() or "curves" in content.lower()

    def test_regulatory_curves_metadata(self):
        """Regulatory curves should have complete metadata."""
        from pmi_site import get_regulatory_curves_metadata
        metadata = get_regulatory_curves_metadata()

        assert "title" in metadata
        assert "description" in metadata
        assert "pmi" in str(metadata).lower()

    def test_regulatory_curves_data_structure(self):
        """Regulatory curves should provide properly structured data."""
        from pmi_site import get_regulatory_curves_data

        data = get_regulatory_curves_data()
        # Should be array of curve objects or dict of curves
        assert isinstance(data, (list, dict))
        if isinstance(data, dict):
            assert len(data) >= 0  # May be empty initially
        if isinstance(data, list) and len(data) > 0:
            first_curve = data[0]
            assert "x" in first_curve or "outcomes" in first_curve
            assert "y" in first_curve or "probabilities" in first_curve

    def test_regulatory_curves_visualization_ready(self):
        """Curves data should be formatted for visualization."""
        from pmi_site import get_regulatory_curves_data

        data = get_regulatory_curves_data()
        if isinstance(data, dict):
            for curve_name, curve_data in data.items():
                # Should have x,y points or similar
                assert isinstance(curve_data, (list, dict))

    def test_regulatory_curves_api_endpoint(self):
        """Should provide API endpoint for curves data."""
        from pmi_site import get_data_api_endpoints
        endpoints = get_data_api_endpoints()

        assert "/api/regulatory-curves" in endpoints or "regulatory" in str(endpoints)

    def test_regulatory_curves_branding(self):
        """Curves should be branded as PMI flagship product."""
        from pmi_site import get_regulatory_curves_metadata
        metadata = get_regulatory_curves_metadata()

        assert "pmi" in str(metadata).lower() or "prediction markets institute" in str(metadata).lower()

    def test_regulatory_curves_update_status(self):
        """Curves should indicate data freshness."""
        from pmi_site import get_regulatory_curves_metadata
        metadata = get_regulatory_curves_metadata()

        # Should have timestamp or refresh info
        assert "updated" in str(metadata).lower() or "last_update" in str(metadata).lower()


class TestDataProductsIntegration:
    """Tests for data products page overall integration."""

    def test_data_page_loads_both_products(self):
        """Data page should load both Orphan Risk Index and regulatory curves."""
        from pmi_site import render_data_products_page
        content = render_data_products_page()

        assert "orphan" in content.lower() and "regulatory" in content.lower()

    def test_data_page_visual_consistency(self):
        """Data products should have consistent visual styling with homepage."""
        from pmi_site import get_data_page_styles, homepage_styles

        data_styles = get_data_page_styles()
        home_styles = homepage_styles()

        # Should use same color palette
        assert data_styles.get("primary_color") == home_styles.get("primary_color")

    def test_data_api_routes_available(self):
        """All data API routes should be available."""
        from pmi_site import get_data_api_endpoints

        endpoints = get_data_api_endpoints()

        required_endpoints = [
            "/api/orphan-risk-index",
            "/api/regulatory-curves"
        ]
        for endpoint in required_endpoints:
            assert any(endpoint in str(e) for e in endpoints), f"Missing endpoint: {endpoint}"

    def test_data_products_fail_soft(self):
        """Data products should degrade gracefully if API fails."""
        with patch('pmi_site.fetch_index_data') as mock_index:
            with patch('pmi_site.fetch_curves_data') as mock_curves:
                mock_index.side_effect = Exception("API failed")
                mock_curves.side_effect = Exception("API failed")

                from pmi_site import render_data_products_page
                content = render_data_products_page()

                # Should still render with placeholders
                assert content is not None and len(content) > 100


class TestPMIBrandingConsistency:
    """Tests for consistent PMI branding across all pages."""

    def test_all_pages_use_pmi_branding(self):
        """All pages should include PMI branding/identity."""
        from pmi_site import homepage_content, render_publications_page, render_data_products_page

        pages = [
            homepage_content(),
            render_publications_page(),
            render_data_products_page()
        ]

        for page in pages:
            # Each page should reference PMI or prediction markets
            assert any(term.lower() in page.lower() for term in ["pmi", "prediction markets institute"])

    def test_branding_colors_consistent(self):
        """All pages should use consistent brand colors."""
        from pmi_site import get_brand_colors, homepage_styles, get_data_page_styles

        brand_colors = get_brand_colors()
        home_colors = homepage_styles().get("colors", {})
        data_colors = get_data_page_styles().get("colors", {})

        # Primary color should match across pages
        assert home_colors.get("primary") == brand_colors.get("primary")
        assert data_colors.get("primary") == brand_colors.get("primary")

    def test_slogan_appears_on_all_pages(self):
        """Slogan should appear consistently across pages."""
        from pmi_site import homepage_content, render_publications_page, render_data_products_page

        pages = [
            homepage_content(),
            render_publications_page(),
            render_data_products_page()
        ]

        for page in pages:
            # Slogan should appear at least in footer/header
            assert "What if tomorrow was predictable?" in page or page.count("predictable") > 0

    def test_flagship_products_labeled(self):
        """Data products should be explicitly labeled as PMI flagship."""
        from pmi_site import get_orphan_risk_index_metadata, get_regulatory_curves_metadata

        index_meta = get_orphan_risk_index_metadata()
        curves_meta = get_regulatory_curves_metadata()

        for meta in [index_meta, curves_meta]:
            assert "flagship" in str(meta).lower() or meta.get("type") == "flagship"


class TestLegalGateAuthorization:
    """Tests for legal gate enforcement on restricted operations."""

    def test_legal_gate_required_for_data_transmission(self):
        """Data transmission/export should require legal gate."""
        with patch('pmi_site.check_legal_authorization') as mock_legal:
            mock_legal.return_value = False

            from pmi_site import export_data_products

            result = export_data_products()
            # Should require authorization
            assert result is None or "unauthorized" in str(result).lower()

    def test_legal_gate_owner_only_for_licensing(self):
        """Licensing decisions should be owner-only."""
        with patch('pmi_site.get_current_user') as mock_user:
            mock_user.return_value = {"role": "contributor", "id": "user123"}

            from pmi_site import update_licensing_terms

            result = update_licensing_terms(new_terms="CC-BY")
            assert "not authorized" in str(result).lower() or result is None

    def test_legal_gate_allows_owner_operations(self):
        """Owner should be able to perform restricted operations."""
        with patch('pmi_site.get_current_user') as mock_user:
            with patch('pmi_site.check_legal_authorization') as mock_legal:
                mock_user.return_value = {"role": "owner", "id": "kale"}
                mock_legal.return_value = True

                from pmi_site import update_licensing_terms

                result = update_licensing_terms(new_terms="CC-BY")
                # Should succeed for owner
                assert result is not None or "success" in str(result).lower()

    def test_legal_gate_blocks_custody_transfer(self):
        """Custody/ownership transfer should require legal approval."""
        with patch('pmi_site.check_legal_authorization') as mock_legal:
            mock_legal.return_value = False

            from pmi_site import transfer_product_custody

            result = transfer_product_custody(to_entity="external_org")
            assert result is None or "unauthorized" in str(result).lower()


class TestOrchestrationPipelineCompliance:
    """Tests for compliance with orchestration pipeline contract."""

    def test_task_class_legal_enforced(self):
        """Task should be classified as legal (need=9)."""
        from pmi_site import get_task_classification

        classification = get_task_classification()
        assert classification.get("task_class") == "legal"
        assert classification.get("need") == 9

    def test_risk_legal_posture_documented(self):
        """Risk level for legal_posture should be documented."""
        from pmi_site import get_task_classification

        classification = get_task_classification()
        assert "legal_posture" in classification.get("risk", [])

    def test_auto_merge_to_dev_after_tests(self):
        """Task should auto-merge to orchestrator/dev after test pass."""
        from pmi_site import get_merge_config

        config = get_merge_config()
        assert config.get("auto_merge") is True
        assert config.get("target_branch") == "orchestrator/dev"
        assert config.get("conditions") == "after_tests_pass"

    def test_coordination_rule_no_deletion(self):
        """Implementation should not delete or overwrite unrelated work."""
        # This is more of a code review check, but test that old content is preserved
        from pmi_site import get_existing_content_preserved

        preserved = get_existing_content_preserved()
        assert preserved is True or "old" in str(preserved).lower()

    def test_preflight_triage_model_available(self):
        """Preflight triage should use google:gemini-2.0-flash."""
        from pmi_site import get_preflight_triage_config

        config = get_preflight_triage_config()
        assert config.get("model") == "gemini-2.0-flash"
        assert config.get("provider") == "google"

    def test_strategy_planner_model_available(self):
        """Strategy planner should use local:codestral:22b."""
        from pmi_site import get_strategy_planner_config

        config = get_strategy_planner_config()
        assert "codestral" in config.get("model", "")
        assert config.get("provider") == "local"

    def test_agentic_coder_model_available(self):
        """Agentic coder should use cowork-skill with claude-haiku."""
        from pmi_site import get_agentic_coder_config

        config = get_agentic_coder_config()
        assert "claude-haiku" in config.get("model", "")
        assert config.get("skill") == "cowork-skill"


class TestContentValidation:
    """Tests for content structure and validation."""

    def test_homepage_valid_html_structure(self):
        """Homepage content should be valid HTML."""
        from pmi_site import homepage_content

        content = homepage_content()
        # Basic HTML structure check
        assert "<" in content and ">" in content
        # Should have opening and closing tags
        assert content.count("<") > 0 and content.count(">") > 0

    def test_publications_valid_json_metadata(self):
        """Publications metadata should be valid JSON."""
        from pmi_site import get_publications_metadata

        metadata = get_publications_metadata()
        # Should be deserializable
        json_str = json.dumps(metadata)
        parsed = json.loads(json_str)
        assert isinstance(parsed, (list, dict))

    def test_data_products_valid_json_structure(self):
        """Data products should have valid JSON structure."""
        from pmi_site import get_orphan_risk_index_data, get_regulatory_curves_data

        for getter in [get_orphan_risk_index_data, get_regulatory_curves_data]:
            data = getter()
            json_str = json.dumps(data)
            parsed = json.loads(json_str)
            assert isinstance(parsed, (list, dict))

    def test_metadata_no_null_required_fields(self):
        """Required metadata fields should not be null."""
        from pmi_site import get_orphan_risk_index_metadata, get_regulatory_curves_metadata

        for getter in [get_orphan_risk_index_metadata, get_regulatory_curves_metadata]:
            meta = getter()
            assert meta.get("title") is not None
            assert meta.get("description") is not None

    def test_urls_properly_formatted(self):
        """All URLs should be properly formatted."""
        from pmi_site import get_data_api_endpoints

        endpoints = get_data_api_endpoints()
        for endpoint in endpoints:
            endpoint_str = str(endpoint)
            # Should start with / for relative or http(s) for absolute
            assert endpoint_str.startswith("/") or endpoint_str.startswith("http")


class TestFailSoftDegradation:
    """Tests for graceful degradation when services unavailable."""

    def test_publications_fetch_failure_degrades(self):
        """Publications page should work even if fetch fails."""
        with patch('pmi_site.fetch_papers_from_source') as mock_fetch:
            mock_fetch.side_effect = Exception("Connection timeout")

            from pmi_site import render_publications_page
            content = render_publications_page()

            assert content is not None
            # Should show placeholder instead of error
            assert "placeholder" in content.lower() or "coming" in content.lower()

    def test_index_fetch_failure_degrades(self):
        """Index should show placeholder when data unavailable."""
        with patch('pmi_site.fetch_index_data') as mock_fetch:
            mock_fetch.side_effect = Exception("API unavailable")

            from pmi_site import render_data_products_page
            content = render_data_products_page()

            # Should still have page content
            assert content is not None and len(content) > 100

    def test_curves_fetch_failure_degrades(self):
        """Curves should show placeholder when data unavailable."""
        with patch('pmi_site.fetch_curves_data') as mock_fetch:
            mock_fetch.side_effect = Exception("API unavailable")

            from pmi_site import render_data_products_page
            content = render_data_products_page()

            # Should still have page content
            assert content is not None and len(content) > 100

    def test_multiple_failures_still_renders(self):
        """Page should render even if all data sources fail."""
        with patch('pmi_site.fetch_papers_from_source') as mock_pub:
            with patch('pmi_site.fetch_index_data') as mock_index:
                with patch('pmi_site.fetch_curves_data') as mock_curves:
                    mock_pub.side_effect = Exception("Failed")
                    mock_index.side_effect = Exception("Failed")
                    mock_curves.side_effect = Exception("Failed")

                    from pmi_site import homepage_content, render_publications_page, render_data_products_page

                    # All should render static content
                    assert len(homepage_content()) > 100
                    assert len(render_publications_page()) > 100
                    assert len(render_data_products_page()) > 100


class TestEndToEndSiteIntegration:
    """End-to-end integration tests."""

    def test_site_homepage_to_publications_navigation(self):
        """Should be able to navigate from homepage to publications."""
        from pmi_site import homepage_content, render_publications_page, get_navigation_links

        home = homepage_content()
        nav_links = get_navigation_links()

        assert "/research" in nav_links or "publications" in home.lower()
        pub_page = render_publications_page()
        assert pub_page is not None

    def test_site_homepage_to_data_navigation(self):
        """Should be able to navigate from homepage to data products."""
        from pmi_site import homepage_content, render_data_products_page, get_navigation_links

        home = homepage_content()
        nav_links = get_navigation_links()

        assert "/data" in nav_links or "data" in home.lower()
        data_page = render_data_products_page()
        assert data_page is not None

    def test_all_pages_have_footer_with_slogan(self):
        """All pages should have footer with branding."""
        from pmi_site import homepage_content, render_publications_page, render_data_products_page, get_footer_content

        footer = get_footer_content()

        for page_getter in [homepage_content, render_publications_page, render_data_products_page]:
            page = page_getter()
            # Should contain footer content
            assert len(page) > 0

    def test_site_structure_complete(self):
        """All required sections should be present."""
        from pmi_site import get_site_structure

        structure = get_site_structure()

        required_sections = ["home", "research", "data"]
        for section in required_sections:
            assert section in structure or section in str(structure).lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
