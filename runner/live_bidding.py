#!/usr/bin/env python3
"""
live_bidding.py — Live colosseum bidding (500X routing improvement).

Phase 2 of the colosseum: instead of routing solely on historical reputation,
actually ask 2-3 models "how would you implement this?" (~100 tokens each).
The best plan wins the implementation contract.

This turns the market from historical-routing into a live auction where models
compete on approach quality, not just past performance.

Flow:
  1. Select top 2-3 candidates from colosseum reputation
  2. Send each a micro-prompt: "In 2-3 sentences, describe your approach to: {task}"
  3. Score each bid on: specificity, file awareness, risk identification, cost estimate
  4. Best bid wins implementation; losing bids become critic/verifier context
  5. Budget-aware: small tasks get 2-seat bid, high-risk get 3-seat

Usage:
    import live_bidding
    winner = live_bidding.auction(task, project, candidates)
"""
import os, sys, json, re, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

BID_TIMEOUT = int(os.environ.get("ORCH_BID_TIMEOUT", "30"))
MAX_BID_TOKENS = int(os.environ.get("ORCH_BID_MAX_TOKENS", "200"))
MIN_CANDIDATES = int(os.environ.get("ORCH_BID_MIN_CANDIDATES", "2"))
MAX_CANDIDATES = int(os.environ.get("ORCH_BID_MAX_CANDIDATES", "3"))

BID_PROMPT = """In 2-3 sentences, describe exactly how you would implement this task.
Name specific files to change and the approach. Be concrete, not generic.

TASK: {task_prompt}
PROJECT: {project}

Reply with JSON: {{"approach": "...", "files": ["file1", "file2"], "risk": "main risk", "estimated_lines": N}}"""


def _select_candidates(task, project="", n=3):
    """Select top candidates from colosseum reputation + model portfolios."""
    candidates = []
    try:
        import colosseum, model_portfolios, model_gateway
        task_class = task.get("kind", "feature")

        # Get domain for this task
        domain = model_portfolios.classify(task, [])

        # Get bids from colosseum
        bids = colosseum.solicit_bids(task)
        for bid in bids[:n]:
            agent_id = bid.get("agent_id", "")
            parts = agent_id.split(":")
            if len(parts) >= 2:
                candidates.append({
                    "agent_id": agent_id,
                    "provider": parts[0],
                    "model": ":".join(parts[1:]),
                    "reputation_score": bid.get("score", 0),
                    "elo": bid.get("elo", 1200),
                })

        # If not enough candidates, add from model_gateway
        if len(candidates) < MIN_CANDIDATES:
            try:
                providers = model_gateway.available_providers()
                for prov in providers:
                    models = model_gateway.models_for(prov)
                    for m in models[:1]:
                        aid = f"{prov}:{m}"
                        if not any(c["agent_id"] == aid for c in candidates):
                            candidates.append({
                                "agent_id": aid,
                                "provider": prov,
                                "model": m,
                                "reputation_score": 0,
                                "elo": 1200,
                            })
                            if len(candidates) >= n:
                                break
                    if len(candidates) >= n:
                        break
            except Exception:
                pass

    except Exception:
        pass

    return candidates[:n]


def _score_bid(bid_response, task):
    """Score a bid on quality of the proposed approach.

    Scoring criteria:
    - Specificity: names actual files/functions (not generic)
    - Risk awareness: identifies concrete risks
    - Scope control: reasonable estimated_lines
    - Actionability: clear next steps
    """
    score = 0
    bid = bid_response or {}

    approach = bid.get("approach", "")
    files = bid.get("files", [])
    risk = bid.get("risk", "")
    est_lines = bid.get("estimated_lines", 0)

    # Specificity: names files
    if files and len(files) > 0:
        score += 3
        if any("." in f for f in files):  # actual file extensions
            score += 2

    # Approach quality
    if len(approach) > 20:
        score += 1
    if len(approach) > 50:
        score += 1
    # Penalize generic responses
    generic_phrases = ["i would", "simply", "just need to", "straightforward"]
    if any(g in approach.lower() for g in generic_phrases):
        score -= 1

    # Risk identification
    if risk and len(risk) > 10:
        score += 2

    # Scope control (reasonable estimate)
    if 1 <= est_lines <= 200:
        score += 1
    elif est_lines > 500:
        score -= 1  # likely overscoping

    return max(0, score)


def auction(task, project="", candidates=None):
    """Run a live bidding auction among candidate models.

    Returns: {
        winner: {agent_id, provider, model, bid, score},
        losers: [{agent_id, bid, score}],
        total_bid_cost_usd: float,
    }
    """
    if candidates is None:
        candidates = _select_candidates(task, project)

    if len(candidates) < MIN_CANDIDATES:
        return None  # Not enough candidates for a meaningful auction

    task_prompt = (task.get("prompt") or "")[:1000]
    prompt = BID_PROMPT.format(task_prompt=task_prompt, project=project)

    bids = []
    total_cost = 0

    for candidate in candidates[:MAX_CANDIDATES]:
        try:
            import model_gateway
            res = model_gateway.complete(
                candidate["provider"], candidate["model"], prompt,
                project=project, timeout=BID_TIMEOUT,
                operation="live_bid", task_class="review",
                max_tokens=MAX_BID_TOKENS,
            )
            text = res.get("text", "")
            cost = res.get("cost_usd", 0)
            total_cost += cost

            # Parse JSON response
            m = re.search(r"\{.*\}", text, re.S)
            bid_data = json.loads(m.group(0)) if m else {"approach": text[:200]}

            score = _score_bid(bid_data, task)
            # Blend with reputation (30% reputation, 70% bid quality)
            blended = score * 0.7 + candidate.get("reputation_score", 0) * 0.3

            bids.append({
                **candidate,
                "bid": bid_data,
                "bid_score": score,
                "blended_score": round(blended, 2),
                "cost_usd": cost,
            })
        except Exception:
            continue

    if not bids:
        return None

    # Sort by blended score
    bids.sort(key=lambda b: -b["blended_score"])

    winner = bids[0]
    losers = bids[1:]

    # Log the auction
    try:
        db.insert("resource_events", {
            "kind": "live_auction",
            "detail": json.dumps({
                "winner": winner["agent_id"],
                "winner_score": winner["blended_score"],
                "candidates": len(bids),
                "total_cost": round(total_cost, 4),
                "task_slug": task.get("slug", ""),
            }, default=str)[:500],
            "action": "auction",
            "created_at": "now()",
        })
    except Exception:
        pass

    return {
        "winner": winner,
        "losers": losers,
        "total_bid_cost_usd": round(total_cost, 4),
        "loser_context": _build_loser_context(losers),
    }


def _build_loser_context(losers):
    """Build context from losing bids to enrich the winner's prompt."""
    if not losers:
        return ""
    context = "\n## ALTERNATIVE APPROACHES (from other models' bids)\n"
    for l in losers[:2]:
        bid = l.get("bid", {})
        context += f"\n- {l['agent_id']}: {bid.get('approach', '')[:150]}"
        risk = bid.get("risk", "")
        if risk:
            context += f" (risk: {risk[:80]})"
    return context


def inject_auction_context(prompt, auction_result):
    """Inject winning bid + loser context into the agent prompt."""
    if not auction_result:
        return prompt

    winner = auction_result.get("winner", {})
    bid = winner.get("bid", {})

    injection = "\n\n## YOUR WINNING BID (implement this approach)\n"
    injection += f"Approach: {bid.get('approach', '')}\n"
    files = bid.get("files", [])
    if files:
        injection += f"Focus files: {', '.join(files[:10])}\n"
    risk = bid.get("risk", "")
    if risk:
        injection += f"Main risk to mitigate: {risk}\n"

    loser_ctx = auction_result.get("loser_context", "")
    if loser_ctx:
        injection += loser_ctx

    return injection + "\n" + prompt
