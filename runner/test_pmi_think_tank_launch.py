#!/usr/bin/env python3
"""
Test suite for the prediction-markets-institute think-tank launch.

WHAT THIS FILE COVERS, AND WHAT IT DELIBERATELY DOES NOT
--------------------------------------------------------
The module under test is `runner/pmi_site.py`. That module implements the
`advocacy-page-comment-letter-coalition-program-d` section of the launch
prompt (intake/processed/20260728-215742-dropbox-PROMPT-pmi-thinktank-launch.md)
plus the homepage/brand surface: slogan, mission, palette, footer, navigation,
API endpoint list, and the orchestration-contract declarations.

The launch prompt's OTHER section — `site-home-thesis-slogan-research-publications-fl`,
i.e. research/publications with a papers pipeline and the two flagship data
products (Orphan Risk Index, regulatory-outcome curves fed by Tomorrow S2S read
endpoints) — is NOT implemented in this repository, in pmi_site.py or anywhere
else (nothing repo-wide mentions an orphan risk index outside this test file and
the intake prompt).

The generated suite that used to live here asserted against ~40 functions that
have never existed — render_publications_page, get_papers_pipeline_config,
papers_cache, get_orphan_risk_index_metadata/_data/_documentation,
get_regulatory_curves_metadata/_data, get_data_api_endpoints, get_data_page_styles,
fetch_papers_from_source, fetch_index_data, fetch_curves_data,
export_data_products, update_licensing_terms, transfer_product_custody,
get_preflight_triage_config, get_strategy_planner_config, get_agentic_coder_config,
get_site_structure, get_existing_content_preserved, homepage_structure,
get_thesis_metadata, get_translatable_strings — every one of them an assertion
about deployed website content rather than about code in this repo. Making those
green would have meant inventing a data product; they are gone, and
`test_no_endpoint_is_advertised_for_the_unbuilt_data_products` below is the
standing guard that this module keeps refusing to advertise a surface it cannot
serve. Tests whose intent could be expressed against real behaviour were kept and
rewritten; each such substitution is named in a comment on the test.
"""
import json
import os
import sys

import pytest
from unittest.mock import DEFAULT, patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

SLOGAN = "What if tomorrow was predictable?"

#: Every page renderer pmi_site actually ships. The research/publications and
#: data-product pages of the launch prompt are absent on purpose — see the module
#: docstring.
PAGE_RENDERERS = (
    "homepage_content",
    "render_advocacy_page",
    "render_advocacy_letters_page",
    "render_letter_archive",
    "render_coalition_program_page",
)


def _render_all_pages():
    import pmi_site

    return {name: getattr(pmi_site, name)() for name in PAGE_RENDERERS}


class TestHomepageThesisAndSlogan:
    """Homepage thesis and slogan content."""

    def test_homepage_contains_slogan(self):
        """Homepage must contain the canonical slogan."""
        from pmi_site import homepage_content

        content = homepage_content()
        assert SLOGAN in content

    def test_homepage_hero_carries_the_slogan(self):
        """The slogan belongs in the hero header, not buried further down."""
        from pmi_site import homepage_content

        content = homepage_content()
        hero_start = content.index('class="hero"')
        hero_end = content.index("</header>", hero_start)
        assert SLOGAN in content[hero_start:hero_end]

    def test_homepage_states_the_pmi_thesis(self):
        """Homepage must carry the mission copy that states PMI's thesis.

        Substitution: the removed test asked get_thesis_metadata() for
        title/description/keywords. No metadata function exists; the thesis copy
        the homepage actually renders is get_pmi_mission(), so this asserts the
        mission is both substantive and embedded in the page.
        """
        from pmi_site import get_pmi_mission, homepage_content

        mission = get_pmi_mission()
        lowered = mission.lower()
        assert "prediction markets" in lowered
        assert "research" in lowered
        assert "policy" in lowered or "advocacy" in lowered
        assert mission in homepage_content()

    def test_homepage_styles_are_the_shared_brand_palette(self):
        """Homepage styling is the one PMI palette, not a page-local theme.

        Substitution: the removed test grepped homepage_styles() for the literal
        words "minimal"/"clean" and for #333/#000 — the style dict carries no
        adjectives and the palette is #2563eb on white. The checkable part of
        "one serious visual language" is that the homepage and every other page
        resolve to the same brand constants.
        """
        from pmi_site import get_advocacy_page_styles, get_brand_colors, homepage_styles

        home = homepage_styles()
        assert home == get_advocacy_page_styles()
        assert home["primary_color"] == get_brand_colors()["primary"]
        assert home["secondary_color"] == get_brand_colors()["secondary"]
        assert home["background"] == "#ffffff"

    def test_homepage_falls_back_to_the_slogan_when_mission_lookup_fails(self):
        """Homepage renders static branding even if its content source raises."""
        with patch("pmi_site.get_pmi_mission", side_effect=Exception("content store down")):
            from pmi_site import homepage_content

            content = homepage_content()

        assert SLOGAN in content
        assert "<div class='homepage'>" in content

    def test_slogan_is_sourced_from_a_single_constant(self):
        """Every page pulls the slogan from pmi_site.BRAND_SLOGAN.

        Substitution: the removed test wanted get_translatable_strings(); there is
        no i18n layer in this repo. The property that makes one possible — the
        copy having exactly one definition site rather than being retyped per
        page — is testable now, so that is what this asserts.
        """
        import pmi_site

        translated = "Et si demain etait previsible ?"
        with patch.object(pmi_site, "BRAND_SLOGAN", translated):
            pages = _render_all_pages()

        for name, page in pages.items():
            assert translated in page, f"{name} does not render BRAND_SLOGAN"
            assert SLOGAN not in page, f"{name} hardcodes the English slogan"


class TestBrandingConsistencyAcrossLaunchPages:
    """PMI branding must be identical across every page that ships."""

    def test_every_page_carries_pmi_identity(self):
        for name, page in _render_all_pages().items():
            lowered = page.lower()
            assert "pmi" in lowered or "prediction markets institute" in lowered, name

    def test_every_page_carries_the_slogan(self):
        for name, page in _render_all_pages().items():
            assert SLOGAN in page, f"{name} is missing the launch slogan"

    def test_brand_palette_is_shared_by_every_page_style(self):
        """Rewritten against the real style shape: flat "primary_color" keys.

        The removed version read homepage_styles().get("colors", {}).get("primary");
        no style dict is nested that way, so it compared None to None and would
        have passed against any palette at all.
        """
        from pmi_site import get_advocacy_page_styles, get_brand_colors, homepage_styles

        brand = get_brand_colors()
        for styles in (homepage_styles(), get_advocacy_page_styles()):
            assert styles["primary_color"] == brand["primary"]
            assert styles["secondary_color"] == brand["secondary"]

    def test_footer_attributes_the_institute_and_links_policy_pages(self):
        from pmi_site import get_footer_content

        footer = get_footer_content()
        assert "Prediction Markets Institute" in footer
        for path in ("/about", "/contact", "/privacy"):
            assert f"href='{path}'" in footer


class TestLegalPostureOfPublishedCopy:
    """Legal gate: what the public copy is and is not allowed to claim."""

    def test_public_copy_never_claims_501c3_or_tax_deductible_status(self):
        """PMI ships as a 501(c)(6) association; c(3)/deductibility claims are barred.

        Substitution: the removed legal-gate tests patched export_data_products /
        update_licensing_terms / transfer_product_custody, none of which exist.
        The launch prompt's actual legal constraint on this pass is item 4 —
        "copy must not claim c(3)/tax-deductible status" — and that is enforceable
        against the copy this module really renders.
        """
        from pmi_site import (
            get_coalition_member_agreement,
            get_comment_consent_terms,
            get_footer_content,
            get_letter_copyright_notice,
            get_pmi_mission,
        )

        forbidden = ("501(c)(3)", "501c3", "tax-deductible", "tax deductible")
        surfaces = dict(_render_all_pages())
        surfaces.update(
            footer=get_footer_content(),
            mission=get_pmi_mission(),
            consent=get_comment_consent_terms(),
            copyright=get_letter_copyright_notice(),
            member_agreement=get_coalition_member_agreement(),
        )
        for name, copy in surfaces.items():
            lowered = copy.lower()
            for claim in forbidden:
                assert claim not in lowered, f"{name} claims {claim!r}"

    def test_published_letters_carry_a_licence_and_attribution_notice(self):
        from pmi_site import get_letter_copyright_notice

        notice = get_letter_copyright_notice()
        assert "Prediction Markets Institute" in notice
        assert "CC BY 4.0" in notice
        assert "signator" in notice.lower()


class TestOrchestrationPipelineCompliance:
    """The module's own orchestration declarations must match the fleet contract."""

    def test_task_class_legal_need_9(self):
        from pmi_site import get_task_classification

        classification = get_task_classification()
        assert classification["task_class"] == "legal"
        assert classification["need"] == 9

    def test_risk_legal_posture_documented(self):
        from pmi_site import get_task_classification

        assert get_task_classification()["risk"] == "legal_posture"

    def test_declared_classification_agrees_with_pipeline_contract(self):
        """pipeline_contract.classify() is the authority; the declaration must match it."""
        import pipeline_contract
        from pmi_site import get_task_classification

        authoritative = pipeline_contract.classify(
            "PMI think tank launch: public legal posture copy", kind="build", material=True
        )
        declared = get_task_classification()
        for field in ("task_class", "need", "risk"):
            assert declared[field] == authoritative[field], field

    def test_auto_merge_targets_the_fleet_staging_branch(self):
        """Substitution: the removed test also demanded config["conditions"] ==
        "after_tests_pass"; no such key exists and inventing one would be product
        written to a spec. require_approval is the real gate flag, so it is what
        the "not before the gates pass" half of the intent asserts against.
        """
        from pmi_site import get_merge_config

        config = get_merge_config()
        assert config["auto_merge"] is True
        assert config["target_branch"] == "orchestrator/dev"
        assert config["require_approval"] is True

    def test_model_routing_covers_agentic_coding_and_complex_work(self):
        """Substitution: three removed tests asked for get_preflight_triage_config /
        get_strategy_planner_config / get_agentic_coder_config. The single routing
        declaration that exists is get_model_routing_config(), so the per-gate
        model expectations are asserted against its real keys.
        """
        from pmi_site import get_model_routing_config

        routing = get_model_routing_config()
        assert "claude-haiku" in routing["default"]
        assert "codestral" in routing["complex"]
        assert routing["review"].startswith("claude-")

    def test_preserved_content_list_names_the_sections_that_must_survive(self):
        from pmi_site import get_preserved_content_list

        preserved = get_preserved_content_list()
        assert isinstance(preserved, list)
        for section in ("existing-branding", "homepage-content", "user-data"):
            assert section in preserved


class TestPublicSurfaceContract:
    """The advertised surface must match the surface that can actually be served."""

    def test_api_endpoints_are_rooted_paths_and_unique(self):
        from pmi_site import get_api_endpoints

        endpoints = get_api_endpoints()
        assert endpoints
        assert len(set(endpoints)) == len(endpoints)
        for endpoint in endpoints:
            assert endpoint.startswith("/api/"), endpoint
            assert " " not in endpoint

    def test_no_endpoint_is_advertised_for_the_unbuilt_data_products(self):
        """Guard for the removed data-products block (see module docstring).

        The Orphan Risk Index and the regulatory-outcome curves are not
        implemented in this repo. Publishing routes for them would hand clients a
        404 surface — and would be the first sign that someone half-built the
        section without the renderers. If this test starts failing because the
        data products landed, restore the removed coverage against the real code.
        """
        import pmi_site

        for endpoint in pmi_site.get_api_endpoints():
            lowered = endpoint.lower()
            assert "orphan" not in lowered and "curve" not in lowered, endpoint
        for name in ("render_data_products_page", "get_orphan_risk_index_data",
                     "get_regulatory_curves_data"):
            assert not hasattr(pmi_site, name), (
                f"{name} exists now — reinstate the data-product tests against it"
            )

    def test_navigation_links_are_rooted_and_cover_the_shipped_sections(self):
        from pmi_site import get_navigation_links

        links = get_navigation_links()
        for link in links:
            assert link.startswith("/"), link
        # Sections this module renders must be reachable from the nav.
        for shipped in ("/", "/advocacy", "/coalition"):
            assert shipped in links

    def test_endpoint_and_navigation_lists_are_json_serialisable(self):
        """Config surfaces are shipped to the web app as JSON."""
        from pmi_site import get_api_endpoints, get_brand_colors, get_navigation_links

        for getter in (get_api_endpoints, get_navigation_links, get_brand_colors):
            assert json.loads(json.dumps(getter())) == getter()

    def test_homepage_markup_closes_every_element_it_opens(self):
        from pmi_site import homepage_content

        content = homepage_content()
        for tag in ("div", "header", "section", "nav"):
            assert content.count(f"<{tag}") == content.count(f"</{tag}>"), tag


class TestFailSoftDegradation:
    """Content unavailability must degrade, never wedge."""

    def test_letter_archive_degrades_to_a_branded_stub(self):
        with patch("pmi_site.get_advocacy_letters_sorted", side_effect=Exception("storage down")):
            from pmi_site import render_letter_archive

            content = render_letter_archive()

        assert "Letter Archive" in content
        assert SLOGAN in content

    def test_coalition_page_degrades_but_keeps_its_heading_and_slogan(self):
        with patch("pmi_site.get_coalition_mission", side_effect=Exception("api down")):
            from pmi_site import render_coalition_program_page

            content = render_coalition_program_page()

        assert "PMI Coalition Program" in content
        assert SLOGAN in content

    def test_unknown_letter_id_returns_the_default_position_letter(self):
        """A missing letter yields PMI's standing position text, not an error."""
        from pmi_site import get_letter_full_text

        text = get_letter_full_text("no-such-letter-id")
        assert "Prediction Markets Institute" in text
        assert len(text) > 200

    def test_every_page_still_renders_when_all_content_sources_fail(self):
        import pmi_site

        failures = {
            "get_pmi_mission": Exception("mission store down"),
            "get_approved_comments": Exception("comment store down"),
            "get_advocacy_letters": Exception("letter store down"),
            "get_advocacy_letters_sorted": Exception("letter store down"),
            "get_coalition_members": Exception("member store down"),
            "get_coalition_mission": Exception("cms down"),
        }
        with patch.multiple(
            pmi_site, **{name: DEFAULT for name in failures}
        ) as mocks:
            for name, exc in failures.items():
                mocks[name].side_effect = exc
            pages = _render_all_pages()

        for name, page in pages.items():
            assert len(page) > 40, name
            assert "Traceback" not in page


class TestEndToEndLaunchNavigation:
    """Cross-section integration for the pages that ship."""

    def test_homepage_links_to_the_shipped_sections(self):
        from pmi_site import homepage_content

        content = homepage_content()
        for href in ("/advocacy", "/coalition"):
            assert f'href="{href}"' in content

    def test_homepage_to_advocacy_to_coalition_all_render(self):
        from pmi_site import (
            get_navigation_links,
            homepage_content,
            render_advocacy_page,
            render_coalition_program_page,
        )

        links = get_navigation_links()
        assert homepage_content() and "/advocacy" in links

        advocacy = render_advocacy_page()
        assert "advocacy" in advocacy.lower()
        assert 'href="/coalition"' in advocacy

        coalition = render_coalition_program_page()
        assert "Coalition" in coalition

    def test_letters_are_reachable_from_the_advocacy_page(self):
        from pmi_site import render_advocacy_page, render_advocacy_letters_page

        assert 'href="/advocacy/letters"' in render_advocacy_page()
        letters_page = render_advocacy_letters_page()
        assert "Advocacy Letters" in letters_page


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
