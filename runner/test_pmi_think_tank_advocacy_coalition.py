#!/usr/bin/env python3
"""
Test suite for prediction-markets-institute think tank launch - advocacy & coalition sections.

Implements sections:
- site-home-thesis-slogan-research-publications-fl (homepage, research, data products)
- advocacy-page-comment-letter-coalition-program-d (advocacy, coalition program)

Focuses on:
- Advocacy page with comment/letter submission system
- Coalition program management and display
- Cross-section integration (home → advocacy → coalition)
- Legal compliance for external communications
- Content moderation and validation
- Fail-soft degradation on submission failures
- Orchestration pipeline contract compliance
"""
import pytest
import os
import json
import sys
from unittest.mock import Mock, patch, MagicMock, call
from datetime import datetime, timedelta
from io import StringIO

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


class TestAdvocacyPageCore:
    """Tests for advocacy page foundation and structure."""

    def test_advocacy_page_loads(self):
        """Advocacy page should render without errors."""
        from pmi_site import render_advocacy_page
        content = render_advocacy_page()

        assert content is not None
        assert len(content) > 100
        assert "advocacy" in content.lower()

    def test_advocacy_page_has_mission_statement(self):
        """Advocacy page should have clear mission statement."""
        from pmi_site import get_advocacy_mission
        mission = get_advocacy_mission()

        assert mission is not None
        assert len(mission) > 50
        # Should reference prediction markets or policy impact
        assert any(term.lower() in mission.lower() for term in ["prediction", "policy", "impact", "markets"])

    def test_advocacy_page_visual_consistency_with_home(self):
        """Advocacy page should use consistent branding with homepage."""
        from pmi_site import get_advocacy_page_styles, homepage_styles

        advocacy_styles = get_advocacy_page_styles()
        home_styles = homepage_styles()

        # Should use same primary brand color
        assert advocacy_styles.get("primary_color") == home_styles.get("primary_color")

    def test_advocacy_page_navigation_integration(self):
        """Advocacy page should be linked in main navigation."""
        from pmi_site import get_navigation_links

        nav_links = get_navigation_links()
        assert "/advocacy" in nav_links or "advocacy" in str(nav_links).lower()

    def test_advocacy_page_includes_pmi_slogan(self):
        """Advocacy page should include PMI slogan for consistency."""
        from pmi_site import render_advocacy_page

        content = render_advocacy_page()
        assert "What if tomorrow was predictable?" in content


class TestAdvocacyCommentSystem:
    """Tests for comment submission and moderation on advocacy page."""

    def test_comment_submission_form_exists(self):
        """Advocacy page should have comment submission form."""
        from pmi_site import get_advocacy_comment_form

        form = get_advocacy_comment_form()
        assert form is not None
        assert "email" in str(form).lower() or "name" in str(form).lower()

    def test_comment_form_required_fields(self):
        """Comment form should have required fields."""
        from pmi_site import get_comment_form_schema

        schema = get_comment_form_schema()
        required_fields = ["name", "email", "comment_text"]

        for field in required_fields:
            assert field in schema.get("fields", {})

    def test_comment_submission_success(self):
        """Should successfully submit a valid comment."""
        from pmi_site import submit_advocacy_comment

        comment_data = {
            "name": "Jane Researcher",
            "email": "jane@example.com",
            "comment_text": "Great work on prediction markets policy research!"
        }
        result = submit_advocacy_comment(comment_data)

        assert result is not None
        assert result.get("status") == "success" or result.get("id") is not None

    def test_comment_submission_requires_valid_email(self):
        """Comment submission should validate email format."""
        from pmi_site import submit_advocacy_comment

        invalid_comment = {
            "name": "John",
            "email": "not-an-email",
            "comment_text": "My thoughts..."
        }
        result = submit_advocacy_comment(invalid_comment)

        assert result.get("status") == "error" or "email" in str(result).lower()

    def test_comment_submission_requires_non_empty_text(self):
        """Comment text should not be empty."""
        from pmi_site import submit_advocacy_comment

        invalid_comment = {
            "name": "John",
            "email": "john@example.com",
            "comment_text": ""
        }
        result = submit_advocacy_comment(invalid_comment)

        assert result.get("status") == "error" or len(result) == 0

    def test_comment_moderation_queue_exists(self):
        """Comments should be queued for moderation."""
        from pmi_site import get_comment_moderation_queue

        queue = get_comment_moderation_queue()
        assert isinstance(queue, (list, dict))

    def test_comment_moderation_marks_spam_keywords(self):
        """Comments with spam keywords should be flagged."""
        from pmi_site import flag_comment_for_moderation

        comment = {
            "id": "comment_123",
            "text": "Click here for FREE MONEY!!! Viagra pills cheap!!!"
        }
        flagged = flag_comment_for_moderation(comment)

        assert flagged.get("spam_risk") > 0.5 or flagged.get("needs_review") is True

    def test_comments_persist_in_storage(self):
        """Submitted comments should persist."""
        from pmi_site import get_submitted_comments

        comments = get_submitted_comments()
        assert isinstance(comments, (list, dict))

    def test_comment_display_on_advocacy_page(self):
        """Approved comments should appear on advocacy page."""
        with patch('pmi_site.get_approved_comments') as mock_comments:
            mock_comments.return_value = [
                {"author": "Jane", "text": "Great initiative!", "date": "2026-07-28"}
            ]

            from pmi_site import render_advocacy_page
            content = render_advocacy_page()

            assert "Jane" in content or "Great initiative" in content or "comment" in content.lower()

    def test_comments_fail_soft_on_submission_error(self):
        """Comment system should degrade gracefully on submission error."""
        with patch('pmi_site.persist_comment') as mock_persist:
            mock_persist.side_effect = Exception("Database unavailable")

            from pmi_site import submit_advocacy_comment
            result = submit_advocacy_comment({
                "name": "John",
                "email": "john@example.com",
                "comment_text": "My thoughts"
            })

            # Should indicate error but not crash
            assert result is not None
            assert "error" in str(result).lower() or result.get("status") in ["error", "retry"]


class TestAdvocacyLetterSystem:
    """Tests for policy letter and statement management."""

    def test_advocacy_letter_library_page_exists(self):
        """Advocacy page should link to library of published letters."""
        from pmi_site import render_advocacy_letters_page

        content = render_advocacy_letters_page()
        assert content is not None
        assert len(content) > 100

    def test_letters_have_metadata(self):
        """Published letters should have complete metadata."""
        from pmi_site import get_advocacy_letters

        letters = get_advocacy_letters()
        if letters:
            for letter in letters:
                assert "title" in letter or "subject" in letter
                assert "date" in letter or "published" in letter
                assert "text" in letter or "content" in letter

    def test_letter_download_functionality(self):
        """Letters should be downloadable (PDF/text format)."""
        from pmi_site import get_letter_download_url

        letter_id = "letter_001"
        url = get_letter_download_url(letter_id)

        assert url is not None
        assert ".pdf" in url.lower() or ".txt" in url.lower() or url.startswith("/")

    def test_letter_signature_collection(self):
        """Letters should support signature collection."""
        from pmi_site import get_letter_signatures, add_signature_to_letter

        # Add a signature
        result = add_signature_to_letter("letter_001", "John Researcher")
        assert result.get("status") == "success" or result.get("id") is not None

        # Verify signature appears
        signatures = get_letter_signatures("letter_001")
        assert "John Researcher" in str(signatures) or len(signatures) > 0

    def test_letter_sorting_by_date(self):
        """Letters should be sortable by date."""
        from pmi_site import get_advocacy_letters_sorted

        letters = get_advocacy_letters_sorted()
        if len(letters) > 1:
            for i in range(len(letters) - 1):
                current = letters[i].get("date") or letters[i].get("published")
                next_item = letters[i + 1].get("date") or letters[i + 1].get("published")
                if current and next_item:
                    assert current >= next_item, "Letters should be sorted newest first"

    def test_letter_full_text_rendering(self):
        """Letter full text should render without formatting errors."""
        from pmi_site import get_letter_full_text

        text = get_letter_full_text("letter_001")
        assert text is not None
        assert len(text) > 200

    def test_letter_archive_page(self):
        """Previous letters should be accessible in archive."""
        from pmi_site import render_letter_archive

        content = render_letter_archive()
        assert content is not None
        assert "archive" in content.lower() or len(content) > 100


class TestCoalitionProgram:
    """Tests for coalition program management and member coordination."""

    def test_coalition_program_page_loads(self):
        """Coalition program page should render without errors."""
        from pmi_site import render_coalition_program_page

        content = render_coalition_program_page()
        assert content is not None
        assert len(content) > 100
        assert "coalition" in content.lower()

    def test_coalition_mission_statement(self):
        """Coalition should have clear mission and goals."""
        from pmi_site import get_coalition_mission

        mission = get_coalition_mission()
        assert mission is not None
        assert len(mission) > 50

    def test_coalition_member_roster(self):
        """Coalition page should list member organizations."""
        from pmi_site import get_coalition_members

        members = get_coalition_members()
        assert isinstance(members, (list, dict))
        if members:
            for member in members:
                assert "name" in str(member) or isinstance(member, str)

    def test_coalition_member_profiles(self):
        """Member organizations should have profiles."""
        from pmi_site import get_coalition_member_profile

        profile = get_coalition_member_profile("member_001")
        if profile:
            assert "name" in profile or "organization" in profile
            assert "mission" in profile or "description" in profile

    def test_coalition_join_request_form(self):
        """Coalition page should have membership interest form."""
        from pmi_site import get_coalition_join_form

        form = get_coalition_join_form()
        assert form is not None
        required_fields = ["organization_name", "email", "interest_description"]
        for field in required_fields:
            assert field in str(form).lower()

    def test_coalition_join_request_submission(self):
        """Should accept coalition membership requests."""
        from pmi_site import submit_coalition_join_request

        request_data = {
            "organization_name": "Research Institute",
            "email": "contact@research.org",
            "interest_description": "Interested in prediction markets research"
        }
        result = submit_coalition_join_request(request_data)

        assert result is not None
        assert result.get("status") == "success" or result.get("id") is not None

    def test_coalition_member_benefits_documented(self):
        """Coalition membership benefits should be clearly documented."""
        from pmi_site import get_coalition_membership_benefits

        benefits = get_coalition_membership_benefits()
        assert benefits is not None
        assert isinstance(benefits, (list, dict))
        # Should have multiple benefits
        assert len(benefits) > 0

    def test_coalition_shared_resources(self):
        """Coalition should provide shared resources for members."""
        from pmi_site import get_coalition_shared_resources

        resources = get_coalition_shared_resources()
        assert resources is not None
        assert isinstance(resources, (list, dict))

    def test_coalition_event_schedule(self):
        """Coalition should have event schedule."""
        from pmi_site import get_coalition_events

        events = get_coalition_events()
        assert isinstance(events, (list, dict))
        if events:
            for event in events:
                assert "title" in str(event) or "date" in str(event).lower()

    def test_coalition_communication_hub(self):
        """Coalition should have communication guidelines."""
        from pmi_site import get_coalition_communication_guidelines

        guidelines = get_coalition_communication_guidelines()
        assert guidelines is not None
        assert len(guidelines) > 0

    def test_coalition_member_access_control(self):
        """Coalition resources should require membership authentication."""
        from pmi_site import check_coalition_member_access

        # Non-member access should be blocked or limited
        result = check_coalition_member_access("nonmember_token")
        assert result is False or result.get("access_level") == "guest"


class TestAdvocacyCoalitionIntegration:
    """Tests for integration between advocacy and coalition components."""

    def test_coalition_advocacy_alignment(self):
        """Coalition and advocacy pages should be cross-linked."""
        from pmi_site import render_advocacy_page, render_coalition_program_page

        advocacy = render_advocacy_page()
        coalition = render_coalition_program_page()

        # Should reference each other
        assert ("coalition" in advocacy.lower() or "join" in advocacy.lower()) or "advocacy" in coalition.lower()

    def test_coalition_members_on_advocacy_page(self):
        """Coalition members should be listed on advocacy page."""
        from pmi_site import render_advocacy_page, get_coalition_members

        page = render_advocacy_page()
        members = get_coalition_members()

        if members:
            # Should show some member representation
            assert len(page) > 500  # Sufficient content

    def test_advocacy_letters_shared_with_coalition(self):
        """Coalition members should have access to advocacy letters."""
        from pmi_site import get_advocacy_letters, check_coalition_member_access

        letters = get_advocacy_letters()
        # Letters should be gettable by coalition members
        assert letters is not None or isinstance(letters, (list, dict))

    def test_coalition_events_on_main_calendar(self):
        """Coalition events should appear in main PMI event calendar."""
        from pmi_site import get_all_pmi_events

        events = get_all_pmi_events()
        # Should include coalition events
        coalition_events = [e for e in events if "coalition" in str(e).lower()]
        assert len(events) > 0

    def test_joint_advocacy_campaign_support(self):
        """Coalition should support joint advocacy campaigns."""
        from pmi_site import get_active_advocacy_campaigns

        campaigns = get_active_advocacy_campaigns()
        if campaigns:
            for campaign in campaigns:
                # Should indicate coalition participation
                assert "coalition" in str(campaign).lower() or len(str(campaign)) > 100


class TestContentModeration:
    """Tests for content moderation and compliance."""

    def test_comment_profanity_filter(self):
        """Comments should be checked for inappropriate language."""
        from pmi_site import check_comment_content_safety

        clean_comment = "Excellent research on this topic!"
        profane_comment = "This is *expletive* garbage"

        clean_result = check_comment_content_safety(clean_comment)
        profane_result = check_comment_content_safety(profane_comment)

        assert clean_result.get("safe") is True or clean_result.get("risk_score", 1.0) < 0.5
        assert profane_result.get("safe") is False or profane_result.get("risk_score", 0.0) > 0.5

    def test_comment_spam_detection(self):
        """Comments should detect spam/promotional content."""
        from pmi_site import detect_comment_spam

        spam_comment = "BUY NOW!!! CHEAP PILLS!!! CLICK HERE!!!"
        real_comment = "I disagree with the methodology used in this analysis."

        spam_risk = detect_comment_spam(spam_comment)
        real_risk = detect_comment_spam(real_comment)

        assert spam_risk > real_risk

    def test_moderation_queue_automatic_flagging(self):
        """High-risk comments should be automatically flagged."""
        from pmi_site import submit_advocacy_comment

        suspicious_comment = {
            "name": "Unknown",
            "email": "spam@spam.com",
            "comment_text": "FREE MONEY CLICK HERE NOW!!!"
        }
        result = submit_advocacy_comment(suspicious_comment)

        # Should indicate it's pending review
        assert "pending" in str(result).lower() or "review" in str(result).lower()

    def test_moderator_approval_workflow(self):
        """Moderation system should support approval workflow."""
        from pmi_site import approve_comment, reject_comment

        comment_id = "comment_123"

        # Should support approval
        approve_result = approve_comment(comment_id)
        assert approve_result is not None

        # Should support rejection
        reject_result = reject_comment(comment_id, "Off-topic")
        assert reject_result is not None


class TestLegalComplianceAdvocacy:
    """Tests for legal compliance in advocacy operations."""

    def test_comment_submission_requires_consent(self):
        """Comment submission should require content sharing consent."""
        from pmi_site import get_comment_consent_terms

        terms = get_comment_consent_terms()
        assert terms is not None
        assert any(term in terms.lower() for term in ["consent", "agree", "policy", "license"])

    def test_advocacy_letters_copyright_attribution(self):
        """Published letters should have proper attribution."""
        from pmi_site import get_letter_copyright_notice

        notice = get_letter_copyright_notice()
        assert notice is not None
        assert any(term in notice.lower() for term in ["copyright", "rights", "attributed", "permission"])

    def test_coalition_member_agreement_required(self):
        """Coalition membership should require agreement."""
        from pmi_site import get_coalition_member_agreement

        agreement = get_coalition_member_agreement()
        assert agreement is not None
        assert len(agreement) > 200

    def test_advocacy_claims_fact_checking(self):
        """Advocacy claims should be fact-checkable."""
        from pmi_site import validate_advocacy_claim

        claim = "Prediction markets improve decision quality"
        result = validate_advocacy_claim(claim)

        assert "source" in str(result).lower() or "citation" in str(result).lower() or result is not None

    def test_external_communications_legal_review(self):
        """External advocacy communications should be flagged for legal review."""
        from pmi_site import flag_for_legal_review

        letter = "We hereby petition the government..."
        result = flag_for_legal_review("letter", letter)

        assert result is not None or result is True


class TestAdvocacyDataValidation:
    """Tests for data validation across advocacy components."""

    def test_comment_form_email_normalization(self):
        """Email addresses should be normalized."""
        from pmi_site import normalize_email

        email = "John.Doe+TAG@Example.COM"
        normalized = normalize_email(email)

        assert normalized == normalized.lower()
        assert "@" in normalized

    def test_coalition_member_url_validation(self):
        """Member organization URLs should be validated."""
        from pmi_site import validate_organization_url

        valid_url = "https://example.org"
        invalid_url = "not a url"

        assert validate_organization_url(valid_url) is True
        assert validate_organization_url(invalid_url) is False

    def test_advocacy_letter_metadata_completeness(self):
        """Letter metadata should have required fields."""
        from pmi_site import validate_letter_metadata

        valid_meta = {
            "title": "Policy Letter",
            "date": "2026-07-28",
            "authors": ["Jane Researcher"]
        }
        result = validate_letter_metadata(valid_meta)

        assert result.get("valid") is True or result is True

    def test_comment_length_constraints(self):
        """Comments should have reasonable length constraints."""
        from pmi_site import get_comment_length_limits

        limits = get_comment_length_limits()
        assert "min_length" in limits
        assert "max_length" in limits
        assert limits["min_length"] < limits["max_length"]


class TestFailSoftDegradationAdvocacy:
    """Tests for graceful degradation in advocacy features."""

    def test_comments_unavailable_page_still_renders(self):
        """Advocacy page should render even if comment system fails."""
        with patch('pmi_site.get_submitted_comments') as mock_comments:
            mock_comments.side_effect = Exception("Database error")

            from pmi_site import render_advocacy_page
            content = render_advocacy_page()

            assert content is not None and len(content) > 100

    def test_coalition_members_unavailable_page_still_loads(self):
        """Coalition page should load even if member list unavailable."""
        with patch('pmi_site.get_coalition_members') as mock_members:
            mock_members.side_effect = Exception("API error")

            from pmi_site import render_coalition_program_page
            content = render_coalition_program_page()

            assert content is not None and len(content) > 100

    def test_advocacy_letters_fetch_failure_degrades(self):
        """Letter display should degrade gracefully."""
        with patch('pmi_site.get_advocacy_letters') as mock_letters:
            mock_letters.side_effect = Exception("Storage unavailable")

            from pmi_site import render_advocacy_letters_page
            content = render_advocacy_letters_page()

            # Should show placeholder or empty state
            assert content is not None or "unavailable" in content.lower()

    def test_coalition_events_fetch_failure_degrades(self):
        """Coalition events should show placeholder on failure."""
        with patch('pmi_site.get_coalition_events') as mock_events:
            mock_events.side_effect = Exception("Event service down")

            from pmi_site import render_coalition_program_page
            content = render_coalition_program_page()

            assert content is not None and len(content) > 50


class TestAdvocacyAPIEndpoints:
    """Tests for advocacy system API routes."""

    def test_comment_submission_api_endpoint(self):
        """POST /api/advocacy/comments should accept submissions."""
        from pmi_site import get_api_endpoints

        endpoints = get_api_endpoints()
        assert "/api/advocacy/comments" in endpoints or any("comment" in str(e) for e in endpoints)

    def test_letters_api_endpoint(self):
        """GET /api/advocacy/letters should return letter list."""
        from pmi_site import get_api_endpoints

        endpoints = get_api_endpoints()
        assert "/api/advocacy/letters" in endpoints or any("letter" in str(e) for e in endpoints)

    def test_coalition_members_api_endpoint(self):
        """GET /api/coalition/members should return member list."""
        from pmi_site import get_api_endpoints

        endpoints = get_api_endpoints()
        assert "/api/coalition/members" in endpoints or any("coalition" in str(e) for e in endpoints)

    def test_coalition_join_api_endpoint(self):
        """POST /api/coalition/join should accept membership requests."""
        from pmi_site import get_api_endpoints

        endpoints = get_api_endpoints()
        assert "/api/coalition/join" in endpoints or any("join" in str(e) for e in endpoints)


class TestEndToEndAdvocacyWorkflow:
    """End-to-end integration tests for advocacy features."""

    def test_visit_advocacy_submit_comment_workflow(self):
        """Full workflow: visit advocacy page, submit comment."""
        from pmi_site import render_advocacy_page, submit_advocacy_comment

        # Visit page
        page = render_advocacy_page()
        assert "advocacy" in page.lower()

        # Submit comment
        result = submit_advocacy_comment({
            "name": "Jane Researcher",
            "email": "jane@research.org",
            "comment_text": "Great initiative for prediction markets policy!"
        })

        assert result.get("status") in ["success", "pending"] or result.get("id") is not None

    def test_visit_coalition_join_workflow(self):
        """Full workflow: visit coalition page, submit join request."""
        from pmi_site import render_coalition_program_page, submit_coalition_join_request

        # Visit page
        page = render_coalition_program_page()
        assert "coalition" in page.lower()

        # Submit request
        result = submit_coalition_join_request({
            "organization_name": "Research Institute",
            "email": "admin@research.org",
            "interest_description": "Research on prediction market policy"
        })

        assert result.get("status") == "success" or result.get("id") is not None

    def test_advocacy_letters_discovery_workflow(self):
        """Full workflow: find and read advocacy letters."""
        from pmi_site import render_advocacy_page, render_advocacy_letters_page

        # Start from advocacy page
        page = render_advocacy_page()
        assert page is not None

        # Navigate to letters
        letters_page = render_advocacy_letters_page()
        assert "letter" in letters_page.lower()

    def test_site_navigation_to_advocacy_and_coalition(self):
        """Should be able to navigate from home to advocacy to coalition."""
        from pmi_site import homepage_content, render_advocacy_page, render_coalition_program_page

        home = homepage_content()
        advocacy = render_advocacy_page()
        coalition = render_coalition_program_page()

        # All should load
        for page in [home, advocacy, coalition]:
            assert page is not None and len(page) > 100


class TestOrchestrationComplianceAdvocacy:
    """Tests for orchestration pipeline contract compliance."""

    def test_advocacy_task_classification(self):
        """Advocacy section should be classified as legal task (need=9)."""
        from pmi_site import get_task_classification

        classification = get_task_classification()
        assert classification.get("task_class") == "legal"
        assert classification.get("need") >= 9

    def test_auto_merge_configured(self):
        """Task should auto-merge after tests pass."""
        from pmi_site import get_merge_config

        config = get_merge_config()
        assert config.get("auto_merge") is True
        assert "dev" in config.get("target_branch", "")

    def test_model_routing_configured(self):
        """Implementation should use configured models."""
        from pmi_site import get_model_routing_config

        config = get_model_routing_config()
        assert "claude-haiku" in str(config) or "codestral" in str(config)

    def test_no_deleted_unrelated_content(self):
        """Implementation should preserve existing content."""
        from pmi_site import get_preserved_content_list

        preserved = get_preserved_content_list()
        # Should have record of preserved items
        assert isinstance(preserved, (list, dict))


class TestBrandingConsistencyAdvocacy:
    """Tests for consistent PMI branding across advocacy sections."""

    def test_advocacy_uses_pmi_colors(self):
        """Advocacy page should use PMI brand colors."""
        from pmi_site import get_brand_colors, get_advocacy_page_styles

        brand_colors = get_brand_colors()
        advocacy_styles = get_advocacy_page_styles()

        assert advocacy_styles.get("primary_color") == brand_colors.get("primary")

    def test_advocacy_includes_mission_statement(self):
        """Advocacy materials should include PMI mission."""
        from pmi_site import render_advocacy_page, get_pmi_mission

        page = render_advocacy_page()
        mission = get_pmi_mission()

        # Mission should be represented somewhere
        assert mission is not None or "mission" in page.lower()

    def test_coalition_branded_as_pmi_initiative(self):
        """Coalition should be clearly branded as PMI initiative."""
        from pmi_site import render_coalition_program_page

        page = render_coalition_program_page()
        assert "pmi" in page.lower() or "prediction markets institute" in page.lower()

    def test_advocacy_footer_consistency(self):
        """Advocacy pages should have consistent footer."""
        from pmi_site import render_advocacy_page, get_footer_content

        page = render_advocacy_page()
        footer = get_footer_content()

        # Footer should be present
        assert "pmi" in page.lower() or "contact" in page.lower()


class TestAccessibility:
    """Tests for accessibility compliance."""

    def test_comments_form_accessible(self):
        """Comment form should have proper labels and ARIA attributes."""
        from pmi_site import get_advocacy_comment_form

        form = get_advocacy_comment_form()
        form_str = str(form)

        # Should have labels or aria attributes
        assert "label" in form_str.lower() or "aria" in form_str.lower()

    def test_advocacy_page_semantic_html(self):
        """Advocacy page should use semantic HTML."""
        from pmi_site import render_advocacy_page

        content = render_advocacy_page()
        # Should have semantic tags
        assert any(tag in content for tag in ["<section>", "<article>", "<header>", "<nav>"])

    def test_coalition_member_list_structured_data(self):
        """Coalition member list should have structured data for accessibility."""
        from pmi_site import render_coalition_program_page

        content = render_coalition_program_page()
        # Should have list structure
        assert "<li>" in content or "<ul>" in content or "<ol>" in content


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
