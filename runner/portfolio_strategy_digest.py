#!/usr/bin/env python3
"""
portfolio_strategy_digest.py - weekly strategic digest.

Reads pending improvement proposals (kind='proposal'), clusters them into 2-3
strategic themes, estimates projected impact per theme, and files one approval
card for the owner. Transforms 50 scattered ideas into 3 key decisions.

Run weekly (wired to Sunday 1:00 UTC): python3 portfolio_strategy_digest.py
Emits to notifications + cockpit (approvals table).
"""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db, claude_cli, notify

MODEL = os.environ.get("DIGEST_MODEL", "claude-opus-4-8")
MIN_PROPOSALS = int(os.environ.get("DIGEST_MIN_PROPOSALS", "5"))
TIMEOUT = int(os.environ.get("DIGEST_TIMEOUT", "300"))


def read_pending_proposals():
    """Fetch all pending improvement proposals from the approvals table."""
    rows = db.select("approvals", {
        "select": "*",
        "kind": "eq.proposal",
        "status": "eq.pending",
        "order": "created_at.desc",
        "limit": "500"
    }) or []
    return rows


def cluster_and_impact(proposals):
    """
    Use Claude to cluster proposals into 2-3 strategic themes.
    Returns list of theme dicts: {theme, titles, impact_score, rationale}
    """
    if not proposals:
        return []

    proposal_text = "\n".join(
        f"- {p.get('title', 'Untitled')} (project: {p.get('project')}, "
        f"value: {p.get('value', 'TBD')[:60]})"
        for p in proposals[:50]  # limit to 50 to avoid prompt overload
    )

    prompt = f"""You are a strategic portfolio reviewer. Below are {len(proposals)} improvement proposals.

YOUR TASK:
1. Identify 2-3 major strategic themes that unify clusters of these proposals
2. For each theme: list the titles of grouped proposals (2-5 most important)
3. Estimate PROJECTED IMPACT of executing the theme as one cohesive push:
   - Format: integer 1-100 (1=negligible, 50=moderate, 100=transformative)
4. Explain why the theme matters and how the proposals reinforce each other

Output ONLY valid JSON (no markdown, no explanation):
[{{"theme": "Theme Name", "titles": ["prop1", "prop2", ...], "impact": <1-100>, "rationale": "why it matters"}}]

PROPOSALS TO CLUSTER:
{proposal_text}"""

    try:
        r = claude_cli.run(prompt, MODEL, timeout=TIMEOUT)
        if r.get("returncode") != 0:
            print(f"digest: model call failed (rc={r.get('returncode')})")
            return []
        text = r.get("text", "").strip()
        # Extract JSON array from response (handles markdown code blocks if present)
        if "```" in text:
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        text = text.strip()
        if text.startswith("[") and text.endswith("]"):
            themes = json.loads(text)
            # Validate structure and filter out incomplete themes
            valid_themes = []
            for t in themes:
                if not all(k in t for k in ["theme", "titles", "impact", "rationale"]):
                    continue
                if not isinstance(t["impact"], int) or t["impact"] < 1 or t["impact"] > 100:
                    t["impact"] = 50  # clamp invalid scores
                valid_themes.append(t)
            return valid_themes[:3]  # limit to top 3 themes
    except json.JSONDecodeError as e:
        print(f"digest: JSON parse failed: {e}")
    except Exception as e:
        print(f"digest: clustering failed: {e}")

    return []


def build_approval_card(proposals, themes):
    """Build a single approval card summarizing the 3 strategic themes."""
    if not themes:
        return None

    theme_summary = "\n".join(
        f"• **{t['theme']}** (impact: {t['impact']}/100)\n"
        f"  Proposals: {', '.join(t.get('titles', [])[:3])}\n"
        f"  {t['rationale']}"
        for t in themes[:3]
    )

    total_proposals = len(proposals)
    avg_impact = round(sum(t.get("impact", 50) for t in themes) / len(themes), 1)

    title = f"Weekly portfolio strategy: {total_proposals} proposals → {len(themes)} themes"
    why = (
        f"Your improvement backlog ({total_proposals} pending proposals) has natural clusters. "
        f"These {len(themes)} strategic themes each have 50%+ ownership overlap — executing them "
        f"together will amplify impact."
    )
    value = (
        f"Cut decision fatigue: instead of reviewing {total_proposals} scattered ideas, "
        f"you make {len(themes)} cohesive bets. Average projected impact: {avg_impact}/100."
    )
    risk = (
        "Thematic clustering is a planning aid, not a constraint. "
        "You can still approve proposals individually or skip a theme entirely."
    )

    return {
        "project": "ORCHESTRATOR",
        "kind": "digest",
        "title": title,
        "why": why,
        "value": value,
        "risk": risk,
        "detail": theme_summary,
        "command": "",
    }


def run():
    """Main digest flow: read, cluster, file approval, notify."""
    proposals = read_pending_proposals()
    if not proposals:
        print("digest: no proposals pending")
        return 0

    if len(proposals) < MIN_PROPOSALS:
        print(f"digest: only {len(proposals)} proposals (need {MIN_PROPOSALS}+)")
        return 0

    print(f"digest: clustering {len(proposals)} proposals...")
    themes = cluster_and_impact(proposals)
    if not themes:
        print("digest: clustering returned no themes")
        return 0

    print(f"digest: found {len(themes)} strategic themes")
    card = build_approval_card(proposals, themes)
    if not card:
        print("digest: failed to build approval card")
        return 0

    # File the approval card
    try:
        db.insert("approvals", card)
        made = 1
    except Exception as e:
        print(f"digest: failed to insert approval: {e}")
        return 0

    # Send notification (high-level alert)
    try:
        theme_names = ", ".join(t["theme"] for t in themes[:3])
        msg = f"📋 Weekly portfolio digest: {len(proposals)} proposals clustered into 3 themes ({theme_names})"
        notify.send(msg)
    except Exception:
        pass

    print(f"digest: filed 1 weekly strategy card (themes: {', '.join(t['theme'] for t in themes)})")
    return made


if __name__ == "__main__":
    run()
