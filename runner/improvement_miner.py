#!/usr/bin/env python3
"""
improvement_miner.py - bakes "how can I make this 20-500X better?" into the learning loop. For each app
and each SURFACE (feature, product, api, backend, frontend, ux, function, growth), it asks a strong model
for concrete, high-leverage improvements, then:

  * NON-DIVERGENT ideas (improve an existing feature/UX/perf/quality/api without changing the business
    model) -> auto-QUEUED as build tasks in that app, so the swarm implements them autonomously.
  * DIVERGENT ideas (new pricing, new product line, new market, changed core value prop, regulatory) ->
    NOT built. Stored as improvement_proposals(status='for_review') WITH a written rationale/presentation
    for the owner to approve later — nothing high-leverage is ever discarded.

Rotates apps+surfaces so over time it re-examines everything. Costless-first (subscription models = $0).
Bounded: a few (app,surface) pairs per run. Schedule ~hourly (heavier in the 2-5am research window).
"""
import os, sys, json, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import pipeline_contract

# EVERYTHING is in scope — not just the app's product surfaces, but the whole autonomous system:
# cross-app coordination, the orchestration layer, the individual bots, the swarm, and the hive-mind.
SURFACES = ["feature", "product", "api", "backend", "frontend", "ux", "function", "growth",
            "performance", "reliability", "security", "data-model", "cost-efficiency",
            "cross-app-coordination", "orchestration-layer", "agent-bot", "swarm", "hive-mind",
            "integration", "developer-experience", "observability"]
# meta surfaces target the orchestrator's OWN repo (beethoven) so the system improves itself too
META_SURFACES = {"orchestration-layer", "agent-bot", "swarm", "hive-mind"}
PER_RUN = int(os.environ.get("IMPROVE_PAIRS_PER_RUN", "4"))
MIN_SCORE = float(os.environ.get("IMPROVE_MIN_SCORE", "12"))   # auto-build bar (impact x feasibility)

PROMPT = """You are a world-class product+engineering+systems strategist. For the target below, propose 3
concrete, high-leverage ways to make its {surface} 20x-500x better — MORE EFFICIENT, faster, cheaper,
higher-quality, or more autonomous. This can be the app itself OR the autonomous system that builds it
(how the bots, the swarm, the hive-mind, and the cross-app coordination work). Be specific and buildable,
not vague. Return ONE JSON array; each item:
{"title":"...","current_state":"what exists / the gap","proposal":"the concrete change to build",
 "expected_multiplier":"20x|50x|100x|500x","impact":1-10,"feasibility":1-10,"divergent":true|false,
 "rationale":"why this is 20-500x leverage (2-3 sentences)"}
Set divergent=true ONLY if it changes the BUSINESS MODEL (new pricing/product line/market/core value
prop/regulated activity) — those need owner sign-off. Everything else (features, UX, perf, quality,
reliability, APIs, and improvements to the orchestration/bots/swarm itself) is divergent=false.
TARGET: {app}
CONTEXT: {context}"""


def _context(app):
    parts = []
    rev = (db.select("app_revenue", {"select": "*", "app": f"eq.{app}"}) or [None])[0]
    if rev:
        parts.append(f"MRR ${rev.get('mrr_usd')}, users {rev.get('active_users')}")
    p = (db.select("projects", {"select": "repo_path", "name": f"eq.{app}"}) or [{}])[0]
    repo = p.get("repo_path", "")
    for f in ("SPEC.md", "README.md"):
        fp = os.path.join(repo, f)
        if repo and os.path.isfile(fp):
            try:
                parts.append(f"# {f}\n" + open(fp).read()[:1500])
            except Exception:
                pass
    merged = db.select("tasks", {"select": "slug", "project_id": f"eq.{p.get('id','')}",
                                 "state": "eq.MERGED", "order": "updated_at.desc", "limit": "8"}) or []
    if merged:
        parts.append("recent shipped: " + ", ".join(m["slug"] for m in merged))
    return "\n\n".join(parts)[:6000] or "(no context yet)"


def _next_pairs():
    """Rotate (app, surface) pairs using a persistent cursor so everything gets re-examined."""
    apps = [p["name"] for p in (db.select("projects", {"select": "name"}) or [])
            if p["name"] not in ("smoke-test",)]
    pairs = [(a, s) for a in apps for s in SURFACES]
    if not pairs:
        return []
    home = os.environ.get("CLAUDE_ORCH_HOME", os.path.expanduser("~/.claude-orchestrator"))
    cur_file = os.path.join(home, "improve_cursor.json")
    try:
        i = int(json.load(open(cur_file)).get("i", 0))
    except Exception:
        i = 0
    out = [pairs[(i + k) % len(pairs)] for k in range(min(PER_RUN, len(pairs)))]
    try:
        json.dump({"i": (i + PER_RUN) % len(pairs)}, open(cur_file, "w"))
    except Exception:
        pass
    return out


def _mine(app, surface):
    prompt = PROMPT.replace("{surface}", surface).replace("{app}", app).replace("{context}", _context(app))
    try:
        import model_policy, model_gateway
        prov, model, _ = model_policy.choose("plan", agentic=False, need=8)  # strong model; $0 on subscription
        r = model_gateway.complete(prov, model, prompt)
        m = re.search(r"\[.*\]", r.get("text") or "", re.S)
        return json.loads(m.group(0)) if m else []
    except Exception:
        return []


def run():
    pid = {p["name"]: p["id"] for p in (db.select("projects", {"select": "id,name"}) or [])}
    # don't re-propose the same title for the same app+surface
    seen = {(r["app"], r.get("surface"), (r.get("title") or "").lower())
            for r in (db.select("improvement_proposals", {"select": "app,surface,title"}) or [])}
    import math
    mrr = {r["app"]: float(r.get("mrr_usd") or 0) for r in (db.select("app_revenue", {"select": "*"}) or [])}
    # gather + SCORE all candidates first (impact x feasibility x revenue-fit), then build highest-EV first
    cands = []
    for app0, surface in _next_pairs():
        # meta surfaces improve the AUTONOMOUS SYSTEM itself -> target the orchestrator repo
        app = "beethoven" if surface in META_SURFACES else app0
        for it in (_mine(app, surface) or [])[:3]:
            title = (it.get("title") or "").strip()
            if not title or (app, surface, title.lower()) in seen:
                continue
            impact = float(it.get("impact", 6) or 6); feas = float(it.get("feasibility", 6) or 6)
            # bias toward surfaces that have PROVEN to pay off (from improvement_measure)
            sret = {r["surface"]: float(r.get("avg_delta") or 0)
                    for r in (db.select("surface_returns", {"select": "surface,avg_delta"}) or [])}
            surf_boost = 1 + max(0.0, math.log10(1 + max(0.0, sret.get(surface, 0))))
            score = round(impact * feas * (1 + math.log10(1 + mrr.get(app, 0))) * surf_boost, 1)
            cands.append((score, app, surface, it, title))
            seen.add((app, surface, title.lower()))
    cands.sort(key=lambda x: x[0], reverse=True)   # impact-ranked: biggest wins first
    queued = review = 0
    for score, app, surface, it, title in cands:
            divergent = bool(it.get("divergent"))
            row = {"app": app, "surface": surface, "title": title[:200],
                   "current_state": (it.get("current_state") or "")[:600],
                   "proposal": (it.get("proposal") or "")[:1500],
                   "expected_multiplier": it.get("expected_multiplier", ""), "score": score,
                   "divergent": divergent, "rationale": (it.get("rationale") or "")[:800]}
            if divergent:
                row["status"] = "for_review"
                db.insert("improvement_proposals", row)
                review += 1
            elif score < MIN_SCORE:
                # below the auto-build bar -> keep as a proposal (visible) but don't spend on it yet
                row["status"] = "proposed"
                db.insert("improvement_proposals", row)
            else:
                # auto-queue a build task in the app (only if the app is active)
                slug = "improve-" + re.sub(r"[^a-z0-9]+", "-", title[:40].lower()).strip("-")
                if pid.get(app):
                    raw_prompt = (f"IMPROVEMENT ({surface}, target {it.get('expected_multiplier','')}): "
                                  f"{it.get('proposal')}\nContext/gap: {it.get('current_state')}\n"
                                  f"Make a concrete, well-tested change and ensure the prod build stays green.")
                    db.insert("tasks", {"project_id": pid[app], "slug": slug, "state": "QUEUED",
                        "kind": "build", "deps": [], "base_branch": "main", "material": False,
                        "prompt": pipeline_contract.wrap_prompt(raw_prompt, project=app,
                                                                kind="build",
                                                                source=f"improvement_miner:{surface}",
                                                                slug=slug, material=False),
                        "note": pipeline_contract.note(source=f"improvement_miner:{surface}")})
                    row["status"] = "queued"; row["task_slug"] = slug
                    db.insert("improvement_proposals", row)
                    queued += 1
            seen.add((app, surface, title.lower()))
    print(f"improvement_miner: auto-queued {queued} improvements, {review} business-model ideas for review")
    return {"queued": queued, "for_review": review}


if __name__ == "__main__":
    run()
