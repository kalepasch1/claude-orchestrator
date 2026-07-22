#!/usr/bin/env python3
"""
improvement_miner.py - bakes "how can I make this 20-500X better?" into the learning loop. For each app
and each SURFACE (feature, product, api, backend, frontend, ux, function, growth), it asks a strong model
for concrete, high-leverage improvements, then:

  * NON-DIVERGENT ideas -> measurability admission -> committee scrutiny. Only committee survivors
    become build tasks, with pre-mortem/canary/rollback conditions carried into the implementation spec.
  * DIVERGENT ideas (new pricing, new product line, new market, changed core value prop, regulatory) ->
    NOT built. Stored as improvement_proposals(status='for_review') WITH a written rationale/presentation
    for the owner to approve later — nothing high-leverage is ever discarded.

Rotates apps+surfaces so over time it re-examines everything. Costless-first (subscription models = $0).
Bounded: a few (app,surface) pairs per run. Schedule ~hourly (heavier in the 2-5am research window).
"""
import os, sys, json, re
import collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

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
QUEUE_FLOOR = int(os.environ.get("IMPROVE_QUEUE_FLOOR", "12"))
BOTTLENECK_SURFACES = ("integration", "reliability", "orchestration-layer", "cost-efficiency", "observability")

PROMPT = """You are a world-class product+engineering+systems strategist. For the target below, propose 3
concrete, high-leverage hypotheses to make its {surface} 20x-500x better — MORE EFFICIENT, faster, cheaper,
higher-quality, or more autonomous. This can be the app itself OR the autonomous system that builds it
(how the bots, the swarm, the hive-mind, and the cross-app coordination work). A multiplier is a hypothesis,
not an achieved result. Ground it in current telemetry and make it falsifiable. Return ONE JSON array; each item:
{"title":"...","current_state":"what exists / the gap","proposal":"the concrete change to build",
 "expected_multiplier":"20x|50x|100x|500x","impact":1-10,"feasibility":1-10,"divergent":true|false,
 "multiplier_basis":"baseline math showing how the multiplier could occur",
 "baseline_metric":"named current metric and value/source","target_metric":"named target and value",
 "acceptance_tests":["deterministic test", "integration/behavior test"],
 "measurement_plan":"before/after or controlled post-deploy measurement window",
 "rollback_plan":"specific reversible rollback trigger and action",
 "rationale":"why this is high leverage (2-3 sentences)"}
Set divergent=true ONLY if it changes the BUSINESS MODEL (new pricing/product line/market/core value
prop/regulated activity) — those need owner sign-off. Everything else (features, UX, perf, quality,
reliability, APIs, and improvements to the orchestration/bots/swarm itself) is divergent=false.
TARGET: {app}
CONTEXT: {context}"""


def _bottleneck_context():
    try:
        tasks = db.select("tasks", {"select": "state,slug,kind,note,project_id",
                                    "limit": "1000"}) or []
    except Exception:
        tasks = []
    states = collections.Counter(t.get("state") for t in tasks)
    blocked = collections.Counter((t.get("note") or "")[:90] for t in tasks
                                  if t.get("state") in ("BLOCKED", "TESTFAIL", "CONFLICT"))
    recovery = collections.Counter(t.get("state") for t in tasks
                                   if str(t.get("slug") or "").startswith("recover-missing-branch-"))
    passed_waiting = 0
    pressure = ""
    try:
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            ".runtime", "merge_train_pressure.json")
        if os.path.isfile(path):
            pressure = open(path).read()[:2000]
    except Exception:
        pass
    return (
        "LIVE ORCHESTRATOR BOTTLENECKS:\n"
        f"Queue states: {dict(states)}\n"
        f"Recovery backlog states: {dict(recovery)}\n"
        f"Top blocked/test/conflict notes: {blocked.most_common(8)}\n"
        f"Merge train pressure: {pressure or '(not available)'}\n"
        "Prioritize improvements that increase tests-passed -> merged -> deployed conversion, "
        "recover missing branches, reduce build failures, and improve routing by deployed value/minute."
    )[:5000]


def _context(app):
    parts = []
    parts.append(_bottleneck_context())
    rev = (db.select("app_revenue", {"select": "*", "app": f"eq.{app}"}) or [None])[0]
    if rev:
        parts.append(f"MRR ${rev.get('mrr_usd')}, users {rev.get('active_users')}")
    p = (db.select("projects", {"select": "id,repo_path,name", "name": f"eq.{app}"}) or [{}])[0]
    repo = p.get("repo_path", "")
    for f in ("SPEC.md", "README.md"):
        fp = os.path.join(repo, f)
        if repo and os.path.isfile(fp):
            try:
                parts.append(f"# {f}\n" + open(fp).read()[:1500])
            except Exception:
                pass
    try:
        merged = db.select("tasks", {"select": "slug", "project_id": f"eq.{p.get('id','')}",
                                     "state": "eq.MERGED", "order": "updated_at.desc", "limit": "8"}) or []
    except Exception:
        merged = []
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
    urgent = []
    apps = list(dict.fromkeys(apps))
    for surface in BOTTLENECK_SURFACES:
        urgent.append(("beethoven", surface))
    out = []
    seen = set()
    for pair in urgent + [pairs[(i + k) % len(pairs)] for k in range(min(PER_RUN, len(pairs)))]:
        if pair in seen:
            continue
        seen.add(pair); out.append(pair)
        if len(out) >= PER_RUN:
            break
    try:
        json.dump({"i": (i + PER_RUN) % len(pairs)}, open(cur_file, "w"))
    except Exception:
        pass
    return out


def _mine(app, surface):
    if os.environ.get("IMPROVE_USE_MODEL", "true").lower() in ("0", "false", "no", "off"):
        return _fallback_ideas(surface)
    prompt = PROMPT.replace("{surface}", surface).replace("{app}", app).replace("{context}", _context(app))
    try:
        import model_policy, model_gateway
        prov, model, _ = model_policy.choose("plan", agentic=False, need=8)  # strong model; $0 on subscription
        r = model_gateway.complete(prov, model, prompt,
                                   timeout=int(os.environ.get("IMPROVE_MODEL_TIMEOUT", "45")),
                                   operation="improvement_mining", task_class="plan",
                                   project=app)
        m = re.search(r"\[.*\]", r.get("text") or "", re.S)
        ideas = json.loads(m.group(0)) if m else []
        return ideas or _fallback_ideas(surface)
    except Exception:
        return _fallback_ideas(surface)


def _fallback_ideas(surface):
    return [
        {"title": "Prioritize recovery backlog ahead of speculative work",
         "current_state": "Recovery and passed-but-not-merged tasks compete with broad build tasks.",
         "proposal": "Add/verify queue ranking that boosts recover-missing-branch tasks, approved train cards, and build-fix tasks until pressure is near zero.",
         "expected_multiplier": "50x", "impact": 9, "feasibility": 9, "divergent": False,
         "multiplier_basis": "Reduce median recovery wait from 50 queue cycles to 1 prioritized cycle: 50/1 = 50x.",
         "baseline_metric": "median queue cycles from recovery task creation to executor claim",
         "target_metric": "median recovery claim latency <= 1 scheduler cycle",
         "acceptance_tests": ["ranking test places recovery work ahead of speculative work", "live canary shows recovery latency without lowering merge success"],
         "measurement_plan": "Compare 7 days before and after canary; require at least 20 recovery tasks.",
         "rollback_plan": "Disable the ranking weight if merge success falls by >5% or starvation exceeds two cycles.",
         "rationale": "These tasks already contain much of the value and need less model work than net-new drafting."},
        {"title": "Attribute train and deploy outcomes back to coder routing",
         "current_state": "Routing can over-reward tests-passed attempts that later fail train/deploy.",
         "proposal": "Record train/deploy status on outcomes and make router_stats optimize by stage-specific deployed value per minute.",
         "expected_multiplier": "100x", "impact": 9, "feasibility": 8, "divergent": False,
         "multiplier_basis": "If only 1 in 100 test-passing attempts deploys, optimizing the 1% conversion bottleneck can recover up to 100/1 = 100x deployed yield.",
         "baseline_metric": "tests-passed to production-deployed conversion by provider/model",
         "target_metric": "deployed-value/minute and conversion tracked for every route",
         "acceptance_tests": ["deployment status is attributed to the originating route", "router excludes routes below the deployment-quality floor"],
         "measurement_plan": "Run a 14-day shadow comparison against current routing before enabling allocation changes.",
         "rollback_plan": "Restore the prior routing weights if deployed conversion or rollback rate regresses by >5%.",
         "rationale": "The biggest loss is tests-passed work not becoming deployed value; routing must learn from that downstream truth."},
        {"title": f"Reduce {surface} bottleneck with a small self-healing loop",
         "current_state": "Bottleneck telemetry exists but not every failure class has an automatic repair loop.",
         "proposal": f"Implement the smallest self-healing loop for the current {surface} bottleneck using existing queue notes and merge pressure metrics.",
         "expected_multiplier": "20x", "impact": 8, "feasibility": 8, "divergent": False,
         "multiplier_basis": "Replace up to 20 repeated manual remediation cycles with one bounded automatic detect-repair-verify cycle: 20/1 = 20x.",
         "baseline_metric": f"manual/repeated remediation attempts per recurring {surface} failure class",
         "target_metric": "one automatic repair attempt with verified resolution or quarantine",
         "acceptance_tests": ["known failure fixture triggers exactly one bounded repair", "failed repair quarantines without requeue loop"],
         "measurement_plan": "Compare repeated attempts per failure signature for 7 days before/after a 10% canary.",
         "rollback_plan": "Disable the repair hook if false-positive quarantine exceeds 2% or any task is mutated twice.",
         "rationale": "Automating one repeated blocker compounds across every app and frees expensive model lanes."},
    ]


def _draft_slots(capacity):
    """Keep discovery moving without adding work to a saturated review lane."""
    if capacity.get("limited"):
        return PER_RUN
    return min(PER_RUN, int(capacity.get("slots") or 0))


def run():
    import improvement_scrutiny, improvement_optimizer
    capacity = improvement_optimizer.capacity(db)
    if capacity["limited"]:
        print("improvement_miner: capacity-limited; draining scrutiny/build backlog before drafting")
        return {"queued": 0, "for_review": 0, "needs_revision": 0,
                "capacity_limited": True, "capacity": capacity}
    pid = {p["name"]: p["id"] for p in (db.select("projects", {"select": "id,name"}) or [])}
    # don't re-propose the same title for the same app+surface
    existing = db.select("improvement_proposals", {
        "select": "id,app,surface,title,current_state,proposal,rationale", "limit": "2000"}) or []
    seen = {(r["app"], r.get("surface"), (r.get("title") or "").lower()) for r in existing}
    import math
    mrr = {r["app"]: float(r.get("mrr_usd") or 0) for r in (db.select("app_revenue", {"select": "*"}) or [])}
    queued_now = 0
    try:
        queued_now = sum(1 for t in (db.select("tasks", {"select": "slug,state", "state": "eq.QUEUED",
                                                         "slug": "like.improve-%", "limit": "200"}) or [])
                         if str(t.get("slug") or "").startswith("improve-"))
    except Exception:
        queued_now = 0
    # gather + SCORE all candidates first (impact x feasibility x revenue-fit), then build highest-EV first
    cands = []
    novelty_rejected = 0
    for app0, surface in _next_pairs():
        # meta surfaces improve the AUTONOMOUS SYSTEM itself -> target the orchestrator repo
        app = "beethoven" if surface in META_SURFACES else app0
        for it in (_mine(app, surface) or [])[:3]:
            title = (it.get("title") or "").strip()
            if not title or (app, surface, title.lower()) in seen:
                continue
            novelty = improvement_optimizer.novel(it, existing + [x[3] for x in cands])
            if not novelty["novel"]:
                novelty_rejected += 1
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
    queued = review = revision = 0
    for score, app, surface, it, title in cands[:capacity["slots"]]:
            divergent = bool(it.get("divergent"))
            row = {"app": app, "surface": surface, "title": title[:200],
                   "current_state": (it.get("current_state") or "")[:600],
                   "proposal": (it.get("proposal") or "")[:1500],
                   "expected_multiplier": it.get("expected_multiplier", ""), "score": score,
                   "divergent": divergent, "rationale": (it.get("rationale") or "")[:800]}
            scrutiny = improvement_scrutiny.assess(it)
            row["rationale"] = (row["rationale"] + "\n\nDraft scrutiny: " +
                                scrutiny["label"] + "; " + ", ".join(scrutiny["reasons"]))[:800]
            if not scrutiny["pass"]:
                row["status"] = "proposed"
                db.insert("improvement_proposals", row)
                revision += 1
            elif divergent:
                row["status"] = "proposed" if proposal_only else "for_review"
                db.insert("improvement_proposals", row)
                review += int(not proposal_only)
                deferred += int(proposal_only)
            elif score < MIN_SCORE:
                # below the auto-build bar -> keep as a proposal (visible) but don't spend on it yet
                row["status"] = "proposed"
                db.insert("improvement_proposals", row)
            else:
                # Every high-leverage draft now enters the independent committee QA path.
                # committees.run() composes the final implementation spec and is the only
                # component allowed to turn a surviving proposal into a build task.
                row["status"] = "proposed" if proposal_only else "for_review"
                if not proposal_only:
                    row["proposal"] = improvement_scrutiny.implementation_spec(
                        it, surface, _bottleneck_context())[:1500]
                db.insert("improvement_proposals", row)
                review += int(not proposal_only)
                deferred += int(proposal_only)
            seen.add((app, surface, title.lower()))
    print(f"improvement_miner: queued 0 directly; {review} scrutiny-ready, {revision} need revision")
    return {"queued": queued, "for_review": review, "needs_revision": revision,
            "novelty_rejected": novelty_rejected, "capacity": capacity}


if __name__ == "__main__":
    run()
