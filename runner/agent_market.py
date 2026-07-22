#!/usr/bin/env python3
"""Role-aware multi-model agent market for the portfolio mesh.

This is the shared kernel for Orchestrator, Tomorrow, Apparently, and Smarter.
It does not replace the existing router; it gives the router a richer shape:
apps have domain-specific settlement functions, and models compete for explicit
roles such as scout, drafter, verifier, red-team, judge, treasurer, and privacy
officer. The recurring job also queues one concrete mesh implementation batch
per core app so the portfolio gets the same competitive-agent structure.
"""
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import db
import model_catalog
import model_gateway


APP_MESHES = {
    "beethoven": {
        "aliases": ("orchestrator", "claude-orchestrator"),
        "domain": "autonomous code orchestration",
        "settlement": "rollback_free_deployed_diff_per_dollar_minute",
        "default_sensitivity": "confidential",
        "north_star": "merged and deployed improvements per dollar-minute with zero rollback",
    },
    "tomorrow": {
        "aliases": ("tomorrow-otc",),
        "domain": "OTC exchange execution and negotiation mesh",
        "settlement": "compliant_fill_or_safe_no_trade_execution_value_per_dollar",
        "default_sensitivity": "confidential",
        "north_star": "best compliant execution after fees, risk, liquidity, and auditability",
    },
    "apparently": {
        "aliases": (),
        "domain": "regulatory intelligence and filing automation",
        "settlement": "verified_regulatory_artifact_or_accepted_filing_per_dollar",
        "default_sensitivity": "confidential",
        "north_star": "verified facts, accepted packets, lower deficiency rate, faster approvals",
    },
    "smarter": {
        "aliases": (),
        "domain": "legal work-product and principal-fit assistant",
        "settlement": "accepted_low_edit_privilege_safe_work_product_per_dollar",
        "default_sensitivity": "crown_jewel",
        "north_star": "accepted legal output with low edit distance, no missed obligations, no privilege mistakes",
    },
    "vigil": {
        "aliases": ("publius",),
        "domain": "civic discourse analysis and truth verification",
        "settlement": "verified_civic_insight_or_debunked_claim_per_dollar",
        "default_sensitivity": "standard",
        "north_star": "verified claims, debunked misinformation, civic pulse accuracy, source reliability",
    },
    "hisanta": {
        "aliases": ("santas-secret-workshop",),
        "domain": "Christmas-themed gamified experience with advent and economy",
        "settlement": "safe_child_appropriate_engagement_event_per_dollar",
        "default_sensitivity": "standard",
        "north_star": "safe engaging child experience with balanced economy and zero inappropriate content",
    },
    "galop": {
        "aliases": ("racefeed",),
        "domain": "horse racing data aggregation and intelligence feed",
        "settlement": "accurate_race_insight_or_prediction_per_dollar",
        "default_sensitivity": "standard",
        "north_star": "accurate race data, reliable form analysis, verified results, timely odds",
    },
    "pareto": {
        "aliases": ("2080", "pareto-2080"),
        "domain": "Pareto-optimal portfolio analysis and resource allocation",
        "settlement": "actionable_optimization_insight_per_dollar",
        "default_sensitivity": "confidential",
        "north_star": "efficient resource allocation on the Pareto frontier with validated trade-offs",
    },
    "darwn": {
        "aliases": (),
        "domain": "evolutionary and adaptive learning system",
        "settlement": "validated_adaptive_improvement_per_dollar",
        "default_sensitivity": "standard",
        "north_star": "converging adaptive improvements with maintained diversity and generalization",
    },
    "sustainable-barks": {
        "aliases": ("sustainable_barks",),
        "domain": "B2B hotel-shelter partnership and sustainable pet toy commerce",
        "settlement": "completed_shelter_partnership_order_per_dollar",
        "default_sensitivity": "standard",
        "north_star": "partner retention, shelter impact, fulfilled orders, sustainable growth",
    },
}

ROLE_SPECS = {
    "scout": {
        "task_class": "plan",
        "need": 5,
        "goal": "find relevant facts, code, market signals, or prior artifacts cheaply",
        "review_required": True,
    },
    "planner": {
        "task_class": "plan",
        "need": 7,
        "goal": "compose a minimal implementation or execution plan",
        "review_required": True,
    },
    "drafter": {
        "task_class": "build",
        "need": 7,
        "goal": "draft the artifact, patch, trade plan, filing packet, or work product",
        "review_required": True,
    },
    "verifier": {
        "task_class": "review",
        "need": 7,
        "goal": "independently verify the drafter output against tests, sources, policy, or acceptance",
        "different_provider": True,
        "review_required": False,
    },
    "red_team": {
        "task_class": "security",
        "need": 8,
        "goal": "attack the output as adversary, regulator, opposing counsel, or production incident",
        "different_provider": True,
        "review_required": False,
    },
    "judge": {
        "task_class": "rating",
        "need": 7,
        "goal": "settle the debate using the app-specific outcome function",
        "different_provider": True,
        "review_required": False,
    },
    "repairer": {
        "task_class": "build",
        "need": 7,
        "goal": "repair only the minimal failing slice after verifier or judge rejection",
        "review_required": True,
    },
    "treasurer": {
        "task_class": "rating",
        "need": 5,
        "goal": "track cost, latency, tokens avoided, and expected value per minute",
        "review_required": False,
    },
    "privacy_officer": {
        "task_class": "security",
        "need": 8,
        "goal": "enforce provider terms, local-only routing, privilege, and IP minimization",
        "sensitivity": "crown_jewel",
        "different_provider": True,
        "review_required": False,
    },
}

APP_BATCHES = {
    "beethoven": {
        "slug": "improve-mesh-orchestrator-agent-market-kernel",
        "title": "Implement role-aware model mesh across all orchestrator lanes",
        "prompt": """Implement the Orchestrator-side Agent Market Kernel end to end.

Acceptance:
- every coding/improvement task has explicit role receipts: scout, planner, drafter, verifier, red_team, judge, repairer, treasurer, privacy_officer;
- route selection optimizes settled rollback-free deployed diff per dollar-minute, not raw task completion;
- verifier/red-team/judge prefer a different provider/model family than the drafter;
- crown-jewel/IP-sensitive prompts route local-only or enterprise/no-training only;
- dashboard/control output shows role bids, winners, penalties, tokens avoided, minutes avoided, and weakest-model demotions;
- canaries use real historical merged tasks and feed the same reputation ledger;
- queue thermal rank incorporates expected settled value per minute and downstream merge/deploy gates.

Keep the change mock-degradable and covered by tests.""",
    },
    "tomorrow": {
        "slug": "improve-mesh-tomorrow-negotiation-execution-market",
        "title": "Implement competitive negotiation/execution bot mesh",
        "prompt": """Implement Tomorrow's OTC bot mesh using the same Agent Market Kernel pattern.

Acceptance:
- maker/taker, liquidity scout, execution planner, compliance verifier, risk red-team, settlement judge, and treasurer bots compete by expected compliant execution value;
- bots negotiate/review each proposed trade path and record bids, objections, no-trade rationales, and final settlement;
- weak bots lose allocation share, strong cheap/local bots gain canary share;
- manual IOI/counsel gates stay hard stops for regulated or money-moving actions;
- Tomorrow can export anonymized outcome signals back to the orchestrator without leaking counterparties or proprietary strategy.""",
    },
    "apparently": {
        "slug": "improve-mesh-apparently-regulatory-intelligence-market",
        "title": "Implement regulatory intelligence mesh and verifier market",
        "prompt": """Implement Apparently's regulatory intelligence mesh using the shared Agent Market Kernel pattern.

Acceptance:
- scout, cartographer, verifier, arbitrage, packet, privacy/federation, and judge bots compete by verified regulatory artifact or accepted filing value per dollar;
- unverified reg_facts cannot affect autonomy until a different-provider verifier confirms a primary source;
- deficiency, filing, renewal, and living-opinion outputs include provenance, confidence, and settlement receipts;
- k-anonymity, DP noise, consent state, and content-level aggregation gates are enforced before any cross-customer learning;
- model routing learns from deficiency-rate reduction, approval speed, stale-source catches, and accepted packet outcomes.""",
    },
    "smarter": {
        "slug": "improve-mesh-smarter-legal-work-product-market",
        "title": "Implement legal work-product swarm market",
        "prompt": """Implement Smarter's legal work-product mesh using the shared Agent Market Kernel pattern.

Acceptance:
- intake, principal-fit, drafter, citation verifier, red-team, privilege guard, judge, and standing learner bots compete by accepted low-edit work product per dollar;
- reviewer/judge bots must be independent from the drafter provider where provider terms allow;
- all learning passes through distillation/dataPosture and never persists client identifiers;
- settlement uses partner edit distance, principal-fit, missed-obligation count, privilege flags, trust receipts, and assignment-won signals;
- email remains only a rail: bots ingest/resolve work into Now/Ask/Approve rather than creating another inbox.""",
    },
    "vigil": {
        "slug": "improve-mesh-vigil-civic-intelligence-market",
        "title": "Implement civic intelligence verification mesh",
        "prompt": """Implement Vigil's civic intelligence mesh using the shared Agent Market Kernel pattern.

Acceptance:
- fact-checker, source verifier, bias auditor, civic analyst, and historical context bots compete by verified civic insight per dollar;
- claims require multi-source triangulation before verification status changes;
- misinformation flags require independent verifier confirmation from a different provider;
- publius hive integration feeds civic pulse data back into the mesh for continuous learning;
- all learning respects editorial independence and avoids partisan bias in verification.""",
    },
    "hisanta": {
        "slug": "improve-mesh-hisanta-gamified-experience-market",
        "title": "Implement gamified experience safety and balance mesh",
        "prompt": """Implement HiSanta's gamified experience mesh using the shared Agent Market Kernel pattern.

Acceptance:
- content safety reviewer, economy balancer, UX tester, age-gate enforcer, and fun factor scout bots compete by safe child-appropriate engagement per dollar;
- all AI-generated content passes through checkContent() safety filter before display;
- economy changes require balancer verification to prevent exploit or inflation;
- purchase flows enforce childCanPurchasePass() guard with age < 18 blocks;
- advent progression and loot fairness verified by independent auditor bot.""",
    },
    "galop": {
        "slug": "improve-mesh-galop-racing-intelligence-market",
        "title": "Implement racing data intelligence mesh",
        "prompt": """Implement Galop's racing intelligence mesh using the shared Agent Market Kernel pattern.

Acceptance:
- data scout, form analyst, odds compiler, track specialist, and result verifier bots compete by accurate race insight per dollar;
- race data accuracy verified against official sources before publication;
- odds analysis includes confidence intervals and historical calibration;
- stale data detection flags outdated form or track conditions automatically;
- result verification cross-references multiple official racing authorities.""",
    },
    "pareto": {
        "slug": "improve-mesh-pareto-optimization-market",
        "title": "Implement portfolio optimization mesh",
        "prompt": """Implement Pareto's optimization mesh using the shared Agent Market Kernel pattern.

Acceptance:
- optimization analyst, constraint modeler, trade-off evaluator, efficiency auditor, and projection verifier bots compete by actionable optimization insight per dollar;
- Pareto frontier calculations verified by independent constraint checker;
- resource allocation recommendations include sensitivity analysis;
- false optimum detection flags local optima that miss global efficiency;
- all projections include uncertainty bounds and assumption documentation.""",
    },
    "darwn": {
        "slug": "improve-mesh-darwn-evolutionary-learning-market",
        "title": "Implement evolutionary learning mesh",
        "prompt": """Implement Darwn's evolutionary learning mesh using the shared Agent Market Kernel pattern.

Acceptance:
- fitness evaluator, mutation designer, selection analyst, convergence auditor, and diversity guardian bots compete by validated adaptive improvement per dollar;
- premature convergence detection halts optimization and diversifies population;
- overfitting detection compares training vs holdout fitness metrics;
- diversity collapse alerts trigger automatic population expansion;
- all evolutionary runs maintain genealogy for reproducibility audit.""",
    },
    "sustainable-barks": {
        "slug": "improve-mesh-sustainable-barks-commerce-market",
        "title": "Implement shelter partnership commerce mesh",
        "prompt": """Implement Sustainable Barks' commerce mesh using the shared Agent Market Kernel pattern.

Acceptance:
- partnership scout, fulfillment coordinator, impact tracker, renewal manager, and pricing analyst bots compete by completed shelter partnership order per dollar;
- order fulfillment tracked end-to-end with shelter impact metrics;
- renewal predictions flag at-risk partnerships before churn;
- bundle pricing validated against margin targets and shelter donation commitments;
- partner onboarding quality verified by satisfaction survey integration.""",
    },
}


def normalize_app(app):
    raw = str(app or "").strip().lower()
    if raw in APP_MESHES:
        return raw
    for name, cfg in APP_MESHES.items():
        if raw in cfg.get("aliases", ()):
            return name
    return raw or "beethoven"


def app_profile(app):
    key = normalize_app(app)
    return {"app": key, **APP_MESHES.get(key, {
        "aliases": (),
        "domain": "portfolio application",
        "settlement": "accepted_outcome_per_dollar_minute",
        "default_sensitivity": "standard",
        "north_star": "accepted value per dollar-minute",
    })}


def role_spec(role):
    return ROLE_SPECS.get(str(role or "").strip().lower(), ROLE_SPECS["planner"])


def _provider_from_model(model):
    return model_gateway.provider_for_model(model or "")


def _candidate_score(candidate, spec, profile):
    cap = int(candidate.get("cap") or 0)
    need = int(spec.get("need") or 0)
    tier = candidate.get("tier") or "unknown"
    provider = candidate.get("provider") or ""
    price = 0.0 if provider == "local" else {"free": 0.0, "cheap": 0.2, "sub": 0.35, "mid": 1.2, "expensive": 3.0}.get(tier, 1.0)
    surplus_penalty = max(0, cap - need) * (0.02 if provider == "local" else 0.06)
    privacy_bonus = 0.4 if provider == "local" and profile.get("default_sensitivity") == "crown_jewel" else 0.0
    fit = max(0.0, cap - need + 1.0)
    return round(fit + privacy_bonus - price - surplus_penalty, 4)


def route_role(app, role, objective="", author_model="", sensitivity=None, record=True):
    """Pick the best provider/model for an app-specific mesh role.

    Reviewer roles can exclude the provider family that authored the draft, which
    gives us real cross-model review instead of same-model self-grading.
    """
    profile = app_profile(app)
    spec = role_spec(role)
    level = sensitivity or spec.get("sensitivity") or profile.get("default_sensitivity") or "standard"
    exclude = _provider_from_model(author_model) if spec.get("different_provider") and author_model else None
    pick = model_catalog.choose(spec["task_class"], need=spec["need"],
                                sensitivity=level, exclude_provider=exclude,
                                use_empirical=False)
    if not pick and exclude:
        pick = model_catalog.choose(spec["task_class"], need=spec["need"], sensitivity=level,
                                    use_empirical=False)
    if not pick:
        bid = {
            "app": profile["app"],
            "role": str(role or "planner"),
            "provider": None,
            "model": None,
            "score": -999.0,
            "reason": f"no allowed model for sensitivity={level}",
            "sensitivity": level,
            "settlement": profile["settlement"],
            "objective": objective,
        }
    else:
        bid = {
            "app": profile["app"],
            "role": str(role or "planner"),
            "provider": pick["provider"],
            "model": pick["model"],
            "cap": pick.get("cap"),
            "tier": pick.get("tier"),
            "score": _candidate_score(pick, spec, profile),
            "reason": f"{spec['goal']} -> {pick['provider']}:{pick['model']}",
            "sensitivity": level,
            "settlement": profile["settlement"],
            "objective": objective,
            "author_provider_excluded": exclude,
        }
    if record:
        _record_bid(bid)
    return bid


def _record_bid(bid):
    try:
        db.insert("app_operations", {
            "app": bid["app"],
            "operation": f"mesh:{bid['role']}",
            "task_class": role_spec(bid["role"])["task_class"],
            "provider": bid.get("provider") or "none",
            "model": bid.get("model") or "none",
            "prompt_chars": len(bid.get("objective") or ""),
            "cost_usd": 0.0,
            "latency_ms": 0,
            "ok": bool(bid.get("provider")),
        })
    except Exception:
        pass
    try:
        db.insert("agent_bids", {
            "app": bid["app"],
            "role": bid["role"],
            "provider": bid.get("provider"),
            "model": bid.get("model"),
            "score": bid.get("score"),
            "sensitivity": bid.get("sensitivity"),
            "settlement": bid.get("settlement"),
            "objective": (bid.get("objective") or "")[:2000],
            "reason": bid.get("reason"),
        })
    except Exception:
        pass


def market_snapshot(apps=None, roles=None, objective="portfolio mesh calibration"):
    apps = [normalize_app(a) for a in (apps or APP_MESHES.keys())]
    roles = list(roles or ROLE_SPECS.keys())
    record_bids = os.environ.get("ORCH_AGENT_MARKET_RECORD_BIDS", "false").lower() in ("1", "true", "yes", "on")
    rows = []
    for app in apps:
        author_model = ""
        for role in roles:
            bid = route_role(app, role, objective=objective, author_model=author_model,
                             record=record_bids)
            rows.append(bid)
            if role in ("drafter", "repairer") and bid.get("model"):
                author_model = bid["model"]
    snap = {
        "generated_at": int(time.time()),
        "apps": {a: app_profile(a) for a in apps},
        "bids": rows,
        "additional_20x_500x": suggestions(),
    }
    _write_control("agent_market_snapshot", snap)
    return snap


def cade_tournament(app, objective, author_model="", sensitivity=None, roles=None, record=True):
    """Build a CADE panel as a model/vendor tournament.

    Each role receives an independent bid. Review roles exclude the drafter's
    provider where possible, so GPT/Gemini/Ollama/Claude compete on proof quality
    and accepted outcome cost instead of grading their own work.
    """
    profile = app_profile(app)
    panel_roles = roles or ("scout", "planner", "drafter", "verifier", "red_team", "judge", "treasurer", "privacy_officer")
    bids = []
    current_author = author_model
    for role in panel_roles:
        bid = route_role(profile["app"], role, objective=objective, author_model=current_author,
                         sensitivity=sensitivity, record=record)
        bids.append(bid)
        if role == "drafter" and bid.get("model"):
            current_author = bid["model"]
    proof_pack = {
        "app": profile["app"],
        "settlement": profile["settlement"],
        "north_star": profile["north_star"],
        "objective": objective,
        "panel": bids,
        "proof_requirements": [
            "record consensus and dissent",
            "record verifier/red-team objections",
            "settle against app-specific outcome function",
            "write outcome to model/domain reputation and slashing ledgers",
        ],
    }
    if record:
        _write_control(f"cade_tournament_{profile['app']}", proof_pack)
    return proof_pack


def _write_control(key, value):
    try:
        db.insert("controls", {"key": key, "value": json.dumps(value), "updated_at": "now()"}, upsert=True)
    except Exception:
        pass


def _write_pending_file(name, payload):
    try:
        root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".runtime")
        os.makedirs(root, exist_ok=True)
        path = os.path.join(root, name)
        with open(path, "w") as f:
            json.dump(payload, f, indent=2, default=str)
    except Exception:
        pass


def _project_index():
    rows = db.select("projects", {"select": "id,name,repo_path,prod_branch"}) or []
    out = {}
    for p in rows:
        name = str(p.get("name") or "").lower()
        out[name] = p
        for canonical, cfg in APP_MESHES.items():
            if name == canonical or name in cfg.get("aliases", ()):
                out[canonical] = p
    return out


def _already_open(project_id, slug):
    try:
        rows = db.select("tasks", {"select": "id,state",
                                   "project_id": f"eq.{project_id}",
                                   "slug": f"eq.{slug}",
                                   "limit": "1"}) or []
        return bool(rows)
    except Exception:
        return False


def _insert_task(row):
    variants = [
        row,
        {k: v for k, v in row.items() if k not in ("priority", "confidence", "material")},
        {k: v for k, v in row.items() if k not in ("priority", "confidence", "material", "base_branch", "deps")},
    ]
    last = None
    for candidate in variants:
        try:
            return db.insert("tasks", candidate)
        except Exception as e:
            last = e
            continue
    raise last or RuntimeError("task insert failed")


def seed_improvement_batches(apps=None):
    """Queue one idempotent app-specific mesh implementation batch per core app."""
    try:
        projects = _project_index()
    except Exception as e:
        pending = {
            "error": str(e),
            "apps": [normalize_app(a) for a in (apps or APP_BATCHES.keys())],
            "batches": APP_BATCHES,
            "written_at": int(time.time()),
        }
        _write_pending_file("agent_market_pending_batches.json", pending)
        return {"queued": [], "skipped": [], "missing_projects": pending["apps"],
                "error": f"project lookup failed; wrote .runtime/agent_market_pending_batches.json: {e}"}
    queued, skipped, missing = [], [], []
    for app in [normalize_app(a) for a in (apps or APP_BATCHES.keys())]:
        spec = APP_BATCHES.get(app)
        project = projects.get(app)
        if not spec or not project:
            missing.append(app)
            continue
        if _already_open(project["id"], spec["slug"]):
            skipped.append(spec["slug"])
            continue
        profile = app_profile(app)
        prompt = (
            f"{spec['prompt']}\n\n"
            f"Shared settlement function: {profile['settlement']}.\n"
            f"North star: {profile['north_star']}.\n"
            "Implementation constraint: reuse the app's existing hive/swarm/bot primitives; "
            "do not create a parallel UI if an existing Now/Approve/dashboard surface exists. "
            "Every new autonomous action must have a verifier/judge receipt and rollback or human-gate path."
        )
        row = {
            "project_id": project["id"],
            "slug": spec["slug"],
            "kind": "build",
            "state": "QUEUED",
            "prompt": prompt,
            "deps": [],
            "base_branch": project.get("default_branch") or project.get("prod_branch") or "main",
            "priority": 1,
            "confidence": 0.82,
            "material": False,
            "note": f"agent-market mesh batch: {spec['title']}",
        }
        _insert_task(row)
        queued.append(spec["slug"])
    result = {"queued": queued, "skipped": skipped, "missing_projects": missing}
    _write_control("agent_market_seed_result", result)
    return result


def suggestions():
    """Additional 20X-500X+ compounding improvements for the next loop."""
    return [
        {
            "title": "Outcome-Based Prompt Bankruptcy",
            "multiplier": "50x",
            "proposal": "Automatically retire prompt/task templates that consume tokens without producing settled outcomes, then regenerate them from the top merged-diff patterns.",
        },
        {
            "title": "Cross-App Domain Skill ETF",
            "multiplier": "100x",
            "proposal": "Maintain per-domain model portfolios rather than one global ranking: code, OTC execution, regulatory facts, and legal drafting each get separate allocation weights.",
        },
        {
            "title": "Multi-Agent Debate Compression",
            "multiplier": "20x",
            "proposal": "Store only objections, deltas, citations, tests, and settlement receipts from debates so reviewers get maximum signal with minimal tokens.",
        },
        {
            "title": "Pre-Settlement Simulators",
            "multiplier": "100x",
            "proposal": "Run cheap deterministic simulations before model calls: build/test dry-run for code, market/rebate simulation for Tomorrow, filing deficiency simulation for Apparently, principal-fit simulation for Smarter.",
        },
        {
            "title": "Model Slashing Rules",
            "multiplier": "50x",
            "proposal": "Penalize models that hallucinate citations, cause rollbacks, leak sensitive context, miss obligations, or pass bad branches; require canary probation before they regain share.",
        },
        {
            "title": "Reusable Intent Graph",
            "multiplier": "500x",
            "proposal": "Index every successful artifact by acceptance intent, AST/schema/entity symbols, source citations, and settlement result so new tasks start by adapting proven work, not drafting from scratch.",
        },
    ]


def run():
    snap = market_snapshot()
    seeded = seed_improvement_batches()
    print(f"agent_market: bids={len(snap['bids'])} queued={len(seeded['queued'])} skipped={len(seeded['skipped'])} missing={seeded['missing_projects']}")
    return {"bids": len(snap["bids"]), **seeded}


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, default=str))
