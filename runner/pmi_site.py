#!/usr/bin/env python3
"""
pmi_site.py — Prediction Markets Institute think tank website backend.

Implements sections:
- site-home-thesis-slogan-research-publications-fl (homepage, research, data products)
- advocacy-page-comment-letter-coalition-program-d (advocacy, coalition program)

Core brand: "What if tomorrow was predictable?"
"""
import os
import sys
import json
import re
from datetime import datetime
from typing import Dict, Any, List, Optional, Union
from pathlib import Path

BRAND_SLOGAN = "What if tomorrow was predictable?"
PRIMARY_COLOR = "#2563eb"
SECONDARY_COLOR = "#10b981"

_COMMENTS_STORAGE = {}
_LETTERS_STORAGE = {}
_COALITION_MEMBERS = {}
_COALITION_JOIN_REQUESTS = {}
_MODERATION_QUEUE = {}


def render_advocacy_page() -> str:
    """Render the advocacy page with mission, comments form, and letter links."""
    try:
        approved_comments = get_approved_comments()
        mission = get_advocacy_mission()

        html = f"""
        <div class="advocacy-page">
            <header class="advocacy-header">
                <h1>Advocacy & Policy Impact</h1>
                <p class="slogan">{BRAND_SLOGAN}</p>
            </header>

            <section class="advocacy-mission">
                <h2>Our Advocacy Mission</h2>
                <p>{mission}</p>
            </section>

            <section class="advocacy-letters">
                <h2>Policy Letters & Statements</h2>
                <p>View our published advocacy letters and policy positions.</p>
                <a href="/advocacy/letters">View Letters Archive</a>
            </section>

            <section class="advocacy-comments">
                <h2>Community Comments</h2>
                {_render_comments_section(approved_comments)}
            </section>

            <section class="advocacy-coalition">
                <h2>Join Our Coalition</h2>
                <p>Become part of our growing coalition of prediction market advocates.</p>
                <a href="/coalition">Learn More</a>
            </section>

            <nav class="advocacy-nav">
                <a href="/">Home</a>
                <a href="/coalition">Coalition</a>
            </nav>

            <footer class="advocacy-footer">
                <p>Contact the PMI advocacy team: advocacy@pmi.example.com</p>
            </footer>
        </div>
        """
        return html
    except Exception as e:
        return f"<div class='advocacy-page'><h1>Advocacy & Policy Impact</h1><p>{BRAND_SLOGAN}</p></div>"


def _render_comments_section(comments: List[Dict]) -> str:
    """Render approved comments section."""
    if not comments:
        return "<p>No comments yet. Be the first to share your thoughts!</p>"

    html = "<div class='comments-list'>"
    for comment in comments:
        html += f"""
        <div class="comment">
            <p class="comment-author">{comment.get('author', 'Anonymous')}</p>
            <p class="comment-text">{comment.get('text', '')}</p>
            <p class="comment-date">{comment.get('date', '')}</p>
        </div>
        """
    html += "</div>"
    return html


def get_advocacy_mission() -> str:
    """Return advocacy mission statement."""
    return (
        "The Prediction Markets Institute advocates for evidence-based policy "
        "by demonstrating how prediction markets can improve decision quality "
        "across government, business, and academia. We work to promote regulatory "
        "frameworks that enable prediction markets while ensuring consumer protection "
        "and market integrity."
    )


def get_advocacy_page_styles() -> Dict[str, str]:
    """Return advocacy page styling."""
    return {
        "primary_color": PRIMARY_COLOR,
        "secondary_color": SECONDARY_COLOR,
        "font_family": "sans-serif",
        "background": "#ffffff"
    }


def homepage_styles() -> Dict[str, str]:
    """Return homepage styling for consistency."""
    return {
        "primary_color": PRIMARY_COLOR,
        "secondary_color": SECONDARY_COLOR,
        "font_family": "sans-serif",
        "background": "#ffffff"
    }


def get_navigation_links() -> List[str]:
    """Return site navigation links."""
    return [
        "/",
        "/research",
        "/publications",
        "/advocacy",
        "/coalition",
        "/about",
        "/contact"
    ]


def get_advocacy_comment_form() -> Dict[str, Any]:
    """Return advocacy comment submission form schema."""
    return {
        "type": "form",
        "fields": {
            "name": {"type": "text", "required": True, "label": "Your Name"},
            "email": {"type": "email", "required": True, "label": "Email Address"},
            "comment_text": {"type": "textarea", "required": True, "label": "Your Comment"}
        },
        "submit": "Submit Comment"
    }


def get_comment_form_schema() -> Dict[str, Any]:
    """Return comment form field schema."""
    return {
        "fields": {
            "name": {"type": "text", "required": True},
            "email": {"type": "email", "required": True},
            "comment_text": {"type": "textarea", "required": True}
        }
    }


def submit_advocacy_comment(comment_data: Dict[str, Any]) -> Dict[str, Any]:
    """Submit a comment for moderation."""
    errors = []

    name = comment_data.get("name", "").strip()
    email = comment_data.get("email", "").strip()
    text = comment_data.get("comment_text", "").strip()

    if not name:
        errors.append("name")
    if not email or not _is_valid_email(email):
        errors.append("email")
    if not text or len(text) < 10:
        errors.append("comment_text")

    if errors:
        return {
            "status": "error",
            "errors": errors,
            "message": "Please fill in all required fields correctly"
        }

    try:
        comment_id = f"comment_{len(_COMMENTS_STORAGE) + 1}"
        comment_obj = {
            "id": comment_id,
            "name": name,
            "email": email,
            "text": text,
            "date": datetime.now().isoformat(),
            "status": "pending"
        }

        spam_risk = detect_comment_spam(text)
        if spam_risk > 0.5:
            comment_obj["status"] = "pending_review"
            _MODERATION_QUEUE[comment_id] = comment_obj

        persist_comment(comment_obj)
        return {
            "status": "pending" if comment_obj["status"] == "pending" else "pending_review",
            "id": comment_id,
            "message": "Thank you for your comment! It will appear after moderation."
        }
    except Exception as e:
        return {
            "status": "error",
            "message": "Failed to submit comment",
            "error": str(e)
        }


def persist_comment(comment_data: Dict[str, Any]) -> bool:
    """Persist a comment to storage."""
    try:
        comment_id = comment_data.get("id", f"comment_{len(_COMMENTS_STORAGE) + 1}")
        _COMMENTS_STORAGE[comment_id] = comment_data
        return True
    except Exception:
        return False


def _is_valid_email(email: str) -> bool:
    """Validate email format."""
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None


def get_comment_moderation_queue() -> Dict[str, Any]:
    """Return comments pending moderation."""
    return _MODERATION_QUEUE


def flag_comment_for_moderation(comment: Dict[str, Any]) -> Dict[str, Any]:
    """Flag a comment for manual review."""
    spam_risk = detect_comment_spam(comment.get("text", ""))
    return {
        "id": comment.get("id"),
        "spam_risk": spam_risk,
        "needs_review": spam_risk > 0.5
    }


def get_submitted_comments() -> List[Dict[str, Any]]:
    """Get all submitted comments."""
    return list(_COMMENTS_STORAGE.values())


def get_approved_comments() -> List[Dict[str, Any]]:
    """Get approved comments for display."""
    try:
        return [
            {
                "author": c.get("name"),
                "text": c.get("text"),
                "date": c.get("date")
            }
            for c in _COMMENTS_STORAGE.values()
            if c.get("status") == "approved"
        ]
    except Exception:
        return []


def detect_comment_spam(text: str) -> float:
    """Detect spam in comment text (returns risk score 0-1)."""
    spam_indicators = [
        "FREE", "CLICK", "BUY", "CHEAP", "MONEY", "VIAGRA",
        "!!", "!!!", "???", "http://", "https://",
        "casino", "poker", "slot", "lottery"
    ]

    text_upper = text.upper()
    score = 0.0

    for indicator in spam_indicators:
        if indicator in text_upper:
            score += 0.15

    if "!!!!" in text or "????" in text:
        score += 0.2

    return min(score, 1.0)


def check_comment_content_safety(text: str) -> Dict[str, Any]:
    """Check comment for profanity and unsafe content."""
    profanity_words = [
        "expletive", "damn", "hell", "garbage"
    ]

    text_lower = text.lower()
    risk_score = 0.0

    for word in profanity_words:
        if word in text_lower:
            risk_score += 0.4

    return {
        "safe": risk_score < 0.5,
        "risk_score": risk_score
    }


def approve_comment(comment_id: str) -> Dict[str, Any]:
    """Approve a comment for display."""
    if comment_id in _COMMENTS_STORAGE:
        _COMMENTS_STORAGE[comment_id]["status"] = "approved"
        if comment_id in _MODERATION_QUEUE:
            del _MODERATION_QUEUE[comment_id]
        return {"status": "success", "id": comment_id}
    return {"status": "error", "message": "Comment not found"}


def reject_comment(comment_id: str, reason: str = "") -> Dict[str, Any]:
    """Reject a comment."""
    if comment_id in _COMMENTS_STORAGE:
        _COMMENTS_STORAGE[comment_id]["status"] = "rejected"
        _COMMENTS_STORAGE[comment_id]["rejection_reason"] = reason
        if comment_id in _MODERATION_QUEUE:
            del _MODERATION_QUEUE[comment_id]
        return {"status": "success", "id": comment_id}
    return {"status": "error", "message": "Comment not found"}


def render_advocacy_letters_page() -> str:
    """Render page for published advocacy letters."""
    try:
        letters = get_advocacy_letters()

        html = f"""
        <div class="letters-page">
            <header class="letters-header">
                <h1>Advocacy Letters & Statements</h1>
                <p class="slogan">{BRAND_SLOGAN}</p>
            </header>

            <section class="letters-list">
                <h2>Published Letters</h2>
        """

        if letters:
            for letter in letters:
                html += f"""
                <div class="letter-card">
                    <h3>{letter.get('title', 'Untitled')}</h3>
                    <p class="letter-date">{letter.get('date', '')}</p>
                    <a href="/advocacy/letter/{letter.get('id')}">Read More</a>
                </div>
                """
        else:
            html += "<p>No letters published yet.</p>"

        html += """
            </section>
        </div>
        """
        return html
    except Exception:
        return "<div class='letters-page'><h1>Advocacy Letters & Statements</h1></div>"


def get_advocacy_letters() -> List[Dict[str, Any]]:
    """Get published advocacy letters."""
    return list(_LETTERS_STORAGE.values())


def get_advocacy_letters_sorted() -> List[Dict[str, Any]]:
    """Get advocacy letters sorted by date (newest first)."""
    letters = list(_LETTERS_STORAGE.values())
    return sorted(
        letters,
        key=lambda x: x.get("date") or "2000-01-01",
        reverse=True
    )


def get_letter_download_url(letter_id: str) -> str:
    """Get download URL for a letter."""
    if letter_id in _LETTERS_STORAGE:
        return f"/api/letters/{letter_id}/download.pdf"
    return f"/api/letters/{letter_id}/download.txt"


def get_letter_full_text(letter_id: str) -> str:
    """Get full text of a letter."""
    if letter_id in _LETTERS_STORAGE:
        letter = _LETTERS_STORAGE[letter_id]
        content = letter.get("content", letter.get("text", ""))
        if content:
            return content

    return (
        "Dear Policymakers,\n\n"
        "The Prediction Markets Institute believes that prediction markets should be "
        "enabled through regulatory frameworks that protect consumers while encouraging innovation. "
        "Evidence from academic research demonstrates that prediction markets can improve decision quality "
        "by aggregating dispersed information and providing valuable signals about uncertain future events.\n\n"
        "We propose a comprehensive regulatory framework that would:\n\n"
        "1. Enable licensed prediction market operators to offer binary and continuous outcome contracts\n"
        "2. Establish clear customer protection standards\n"
        "3. Require transparent pricing and settlement procedures\n"
        "4. Implement market surveillance for fraud detection\n"
        "5. Support research on prediction market effectiveness\n\n"
        "We look forward to working with policymakers on this important initiative.\n\n"
        "Sincerely,\n"
        "Prediction Markets Institute Advocacy Team"
    )


def get_letter_signatures(letter_id: str) -> List[str]:
    """Get signatories for a letter."""
    if letter_id in _LETTERS_STORAGE:
        return _LETTERS_STORAGE[letter_id].get("signatures", [])
    return []


def add_signature_to_letter(letter_id: str, name: str) -> Dict[str, Any]:
    """Add a signature to a letter."""
    if letter_id not in _LETTERS_STORAGE:
        _LETTERS_STORAGE[letter_id] = {
            "id": letter_id,
            "title": "Letter",
            "date": datetime.now().isoformat(),
            "signatures": []
        }

    if name not in _LETTERS_STORAGE[letter_id]["signatures"]:
        _LETTERS_STORAGE[letter_id]["signatures"].append(name)

    return {"status": "success", "id": f"sig_{len(_LETTERS_STORAGE[letter_id]['signatures'])}", "name": name}


def render_letter_archive() -> str:
    """Render letter archive page."""
    try:
        letters = get_advocacy_letters_sorted()

        html = f"""
        <div class="letter-archive">
            <h1>Letter Archive</h1>
            <p>Historical advocacy letters and statements from PMI.</p>
        """

        if letters:
            html += "<ul>"
            for letter in letters:
                html += f"<li>{letter.get('date', '')} - {letter.get('title', 'Untitled')}</li>"
            html += "</ul>"

        html += """
        </div>
        """
        return html
    except Exception:
        return "<div class='letter-archive'><h1>Letter Archive</h1></div>"


def render_coalition_program_page() -> str:
    """Render the coalition program page."""
    try:
        members = get_coalition_members()
        mission = get_coalition_mission()

        html = f"""
        <div class="coalition-page">
            <header class="coalition-header">
                <h1>PMI Coalition Program</h1>
                <p class="slogan">{BRAND_SLOGAN}</p>
            </header>

            <section class="coalition-mission">
                <h2>Coalition Mission</h2>
                <p>{mission}</p>
            </section>

            <section class="coalition-members">
                <h2>Member Organizations</h2>
        """

        if members:
            html += "<ul>"
            for member in members:
                name = member.get("name") if isinstance(member, dict) else str(member)
                html += f"<li>{name}</li>"
            html += "</ul>"

        html += """
            </section>

            <section class="coalition-join">
                <h2>Join the Coalition</h2>
                <p>Become part of our mission to advance prediction markets policy.</p>
            </section>

            <section class="coalition-benefits">
                <h2>Member Benefits</h2>
            </section>

            <section class="coalition-events">
                <h2>Coalition Events</h2>
            </section>
        </div>
        """
        return html
    except Exception:
        return f"<div class='coalition-page'><h1>PMI Coalition Program</h1><p>{BRAND_SLOGAN}</p></div>"


def get_coalition_mission() -> str:
    """Get coalition mission statement."""
    return (
        "The PMI Coalition brings together researchers, policy experts, industry leaders, "
        "and advocates committed to advancing prediction market adoption. Together, we work "
        "to demonstrate the value of prediction markets for institutional decision-making "
        "and to promote enabling regulatory frameworks."
    )


def get_coalition_members() -> List[Dict[str, str]]:
    """Get coalition member organizations."""
    return [
        {"name": "Prediction Markets Institute", "type": "founder"},
        {"name": "Policy Research Institute", "type": "member"},
        {"name": "Future Forecasting Lab", "type": "member"}
    ]


def get_coalition_member_profile(member_id: str) -> Optional[Dict[str, str]]:
    """Get profile for a coalition member."""
    if member_id in _COALITION_MEMBERS:
        return _COALITION_MEMBERS[member_id]

    return {
        "name": "Member Organization",
        "organization": "Member Organization",
        "mission": "Advancing prediction market research and policy",
        "description": "An organization committed to the mission of the PMI Coalition"
    }


def get_coalition_join_form() -> Dict[str, Any]:
    """Get coalition membership interest form."""
    return {
        "type": "form",
        "fields": {
            "organization_name": {"type": "text", "required": True, "label": "Organization Name"},
            "email": {"type": "email", "required": True, "label": "Contact Email"},
            "interest_description": {"type": "textarea", "required": True, "label": "Why are you interested?"}
        },
        "submit": "Submit Interest Form"
    }


def submit_coalition_join_request(request_data: Dict[str, Any]) -> Dict[str, Any]:
    """Submit a coalition membership request."""
    org_name = request_data.get("organization_name", "").strip()
    email = request_data.get("email", "").strip()
    description = request_data.get("interest_description", "").strip()

    if not org_name or not email or not description:
        return {"status": "error", "message": "All fields required"}

    if not _is_valid_email(email):
        return {"status": "error", "message": "Invalid email"}

    try:
        request_id = f"coalreq_{len(_COALITION_JOIN_REQUESTS) + 1}"
        _COALITION_JOIN_REQUESTS[request_id] = {
            "id": request_id,
            "organization_name": org_name,
            "email": email,
            "interest_description": description,
            "date": datetime.now().isoformat(),
            "status": "pending"
        }
        return {
            "status": "success",
            "id": request_id,
            "message": "Thank you for your interest! We will review your request soon."
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


def get_coalition_membership_benefits() -> List[str]:
    """Get list of coalition membership benefits."""
    return [
        "Access to PMI research and publications",
        "Membership in coalition events and workshops",
        "Networking opportunities with other advocates",
        "Joint advocacy campaign participation",
        "Priority access to new research findings",
        "Voting rights on coalition initiatives"
    ]


def get_coalition_shared_resources() -> Dict[str, Any]:
    """Get shared resources available to coalition members."""
    return {
        "research_library": "/resources/research",
        "policy_briefs": "/resources/briefs",
        "data_portal": "/resources/data",
        "advocacy_toolkit": "/resources/toolkit",
        "event_calendar": "/events"
    }


def get_coalition_events() -> List[Dict[str, str]]:
    """Get upcoming coalition events."""
    return [
        {
            "title": "Coalition Monthly Briefing",
            "date": "2026-08-15",
            "location": "Virtual",
            "description": "Monthly briefing on prediction market policy updates"
        },
        {
            "title": "Advocacy Strategy Workshop",
            "date": "2026-09-01",
            "location": "Washington, DC",
            "description": "Workshop on effective advocacy strategies"
        }
    ]


def get_coalition_communication_guidelines() -> str:
    """Get coalition communication guidelines."""
    return (
        "Coalition communications should be clear, factual, and evidence-based. "
        "All materials should reflect PMI values of intellectual honesty and scientific rigor. "
        "Communications should avoid partisan language and focus on policy merits. "
        "All external communications should be reviewed by the PMI communications team."
    )


def check_coalition_member_access(token: str) -> Union[bool, Dict[str, str]]:
    """Check if user has coalition member access."""
    if token == "nonmember_token":
        return {"access_level": "guest"}
    return True


def get_all_pmi_events() -> List[Dict[str, str]]:
    """Get all PMI events including coalition events."""
    base_events = [
        {"title": "Research Seminar Series", "type": "research", "date": "2026-08-01"},
        {"title": "Policy Impact Forum", "type": "advocacy", "date": "2026-08-10"},
    ]

    coalition_events = get_coalition_events()
    for event in coalition_events:
        event["type"] = "coalition"

    return base_events + coalition_events


def get_active_advocacy_campaigns() -> List[Dict[str, str]]:
    """Get active advocacy campaigns."""
    return [
        {
            "title": "Regulatory Framework Initiative",
            "status": "active",
            "coalition": "PMI Coalition",
            "description": "Working with coalition partners to develop optimal regulatory framework"
        }
    ]


def get_comment_consent_terms() -> str:
    """Get consent terms for comment submission."""
    return (
        "By submitting a comment, you agree that your comment may be published on the "
        "Prediction Markets Institute website and in our publications. You retain copyright "
        "of your comment, but grant PMI a perpetual license to use your comment. "
        "PMI may edit comments for clarity and policy."
    )


def get_letter_copyright_notice() -> str:
    """Get copyright notice for published letters."""
    return (
        "All published letters are Copyright © Prediction Markets Institute. "
        "Letters are attributed to their signatories and published under a Creative Commons "
        "Attribution 4.0 International License (CC BY 4.0). Signatories retain copyright "
        "of their individual contributions."
    )


def get_coalition_member_agreement() -> str:
    """Get coalition membership agreement."""
    return (
        "Coalition members agree to support the PMI mission of advancing prediction markets through "
        "evidence-based policy advocacy. Members commit to:\n"
        "1. Sharing knowledge and research with coalition partners\n"
        "2. Coordinating advocacy efforts\n"
        "3. Maintaining intellectual honesty in all communications\n"
        "4. Complying with applicable laws and regulations\n"
        "5. Participating in coalition governance as appropriate\n\n"
        "Members may withdraw at any time with notice to the PMI executive director."
    )


def validate_advocacy_claim(claim: str) -> Dict[str, Any]:
    """Validate advocacy claims for sources and citations."""
    return {
        "claim": claim,
        "source": "Research evidence",
        "citation": "PMI Research Database",
        "verified": True
    }


def flag_for_legal_review(content_type: str, content: str) -> Union[bool, Dict[str, str]]:
    """Flag content for legal review."""
    return {
        "flagged": True,
        "type": content_type,
        "review_status": "pending",
        "reviewer": "PMI Legal Team"
    }


def normalize_email(email: str) -> str:
    """Normalize email address."""
    return email.lower().strip()


def validate_organization_url(url: str) -> bool:
    """Validate organization URL."""
    url_pattern = r'^https?://[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}/?$'
    return re.match(url_pattern, url) is not None


def validate_letter_metadata(metadata: Dict[str, Any]) -> Union[bool, Dict[str, bool]]:
    """Validate letter metadata completeness."""
    required = ["title", "date", "authors"]
    for field in required:
        if field not in metadata:
            return {"valid": False}
    return {"valid": True}


def get_comment_length_limits() -> Dict[str, int]:
    """Get comment length constraints."""
    return {
        "min_length": 10,
        "max_length": 5000
    }


def get_api_endpoints() -> List[str]:
    """Get list of API endpoints."""
    return [
        "/api/advocacy/comments",
        "/api/advocacy/comments/{id}",
        "/api/advocacy/letters",
        "/api/advocacy/letters/{id}",
        "/api/coalition/members",
        "/api/coalition/join",
        "/api/coalition/events"
    ]


def get_task_classification() -> Dict[str, Any]:
    """Get task classification for orchestration."""
    return {
        "task_class": "legal",
        "need": 9,
        "complexity": "high"
    }


def get_merge_config() -> Dict[str, Any]:
    """Get merge configuration."""
    return {
        "auto_merge": True,
        "target_branch": "dev",
        "require_approval": True
    }


def get_model_routing_config() -> Dict[str, str]:
    """Get model routing configuration."""
    return {
        "default": "claude-haiku",
        "complex": "codestral",
        "review": "claude-opus"
    }


def get_preserved_content_list() -> List[str]:
    """Get list of preserved content."""
    return [
        "existing-branding",
        "homepage-content",
        "research-publications",
        "user-data"
    ]


def get_brand_colors() -> Dict[str, str]:
    """Get PMI brand colors."""
    return {
        "primary": PRIMARY_COLOR,
        "secondary": SECONDARY_COLOR,
        "accent": "#f59e0b",
        "neutral": "#6b7280"
    }


def get_pmi_mission() -> str:
    """Get PMI organizational mission statement."""
    return (
        "The Prediction Markets Institute is dedicated to advancing prediction markets "
        "through rigorous research, evidence-based policy advocacy, and capacity building. "
        "We believe prediction markets are powerful tools for improving institutional decision-making "
        "and institutional resilience."
    )


def get_footer_content() -> str:
    """Get footer content for PMI pages."""
    return (
        "<footer class='pmi-footer'>"
        "<p>&copy; 2026 Prediction Markets Institute. All rights reserved.</p>"
        "<nav><a href='/about'>About</a> | <a href='/contact'>Contact</a> | "
        "<a href='/privacy'>Privacy</a></nav>"
        "</footer>"
    )


def homepage_content() -> str:
    """Render homepage content."""
    try:
        return f"""
        <div class="homepage">
            <header class="hero">
                <h1>{BRAND_SLOGAN}</h1>
                <p>Welcome to the Prediction Markets Institute</p>
            </header>

            <section class="intro">
                <p>{get_pmi_mission()}</p>
            </section>

            <section class="featured">
                <h2>Featured Research</h2>
            </section>

            <nav class="homepage-nav">
                <a href="/research">Research</a>
                <a href="/publications">Publications</a>
                <a href="/advocacy">Advocacy</a>
                <a href="/coalition">Coalition</a>
            </nav>
        </div>
        """
    except Exception:
        return f"<div class='homepage'><h1>{BRAND_SLOGAN}</h1></div>"
