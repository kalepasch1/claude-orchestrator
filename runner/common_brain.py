#!/usr/bin/env python3
"""Deployable Common Brain bridge for the orchestrator queue.

The TypeScript Darwin kernel is the portable runtime/import surface. This Python
bridge is the orchestrator-side seeder: it turns the shared brain pattern into
app-specific implementation tasks for Orchestrator, Tomorrow, Apparently, and
Smarter, then lets the normal queue/routing/merge/deploy machinery handle them.
"""
import json
import os
import re
import sys
import time

os.environ.setdefault("ORCH_SUPABASE_TIMEOUT", "12")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import db


COMMON_STAGES = [
    "sense: canonical spine + adaptive intake",
    "decompose: CADE contestable units + digital twin",
    "retrieve: reusable intent library + shared artifact ledger",
    "deliberate: competence-matched CADE panel + dissent + red team",
    "route: role-aware agent market by privacy/cost/quality",
    "act: reversible autopilot, human gate for material/irreversible",
    "verify: independent verifier marketplace + repair loop",
    "prove: signed proof pack/trust receipt",
    "learn: outcome flywheel + federated privacy gates",
    "reuse: publish a capability/pattern for the next surface",
]

APP_RECIPES = {
    "beethoven": {
        "aliases": ("orchestrator", "claude-orchestrator"),
        "surface": "queue-priority-merge-release-model-routing",
        "domain": "autonomous code orchestration",
        "settlement": "rollback-free deployed improvement per dollar-minute",
        "cade": {
            "target": "task priority, model route, implementation plan, merge train, and release gate",
            "roster": "repo maintainer, build verifier, security reviewer, release engineer, cost treasurer",
            "adversary": "red build, stale branch, unsafe merge, rollback, wasted model spend",
            "reviewer": "merge train, Vercel deployment, production telemetry, owner priority",
            "proof": "deployed-diff proof pack",
        },
    },
    "predictions": {
        "aliases": ("prediction-markets",),
        "surface": "cross-app-temporal-prediction-engine",
        "domain": "causal forecasting and prediction consensus",
        "settlement": "calibrated verified forecast per dollar-minute",
        "cade": {
            "target": "forecast horizon, causal driver, calibration, consensus, and anomaly response",
            "roster": "causal analyst, calibration auditor, market forecaster, adversarial scenario generator, verifier",
            "adversary": "regime shift, leakage, spurious correlation, stale prior, consensus cascade",
            "reviewer": "forecast scoring ledger, outcome reconciler, and calibration audit",
            "proof": "forecast-calibration proof pack",
        },
    },
    "illuminati": {
        "aliases": ("cross-app-intelligence",),
        "surface": "federated-holographic-intelligence-mesh",
        "domain": "privacy-aware cross-application intelligence federation",
        "settlement": "reused verified cross-app insight per dollar-minute",
        "cade": {
            "target": "memory federation, provenance, access policy, cross-app retrieval, and consensus",
            "roster": "memory curator, privacy guard, provenance verifier, federation operator, anomaly auditor",
            "adversary": "cross-tenant leak, poisoned memory, stale correlation, provenance loss, access bypass",
            "reviewer": "federation policy, retrieval audit, and downstream outcome ledger",
            "proof": "federated-memory proof pack",
        },
    },
    "tomorrow": {
        "aliases": ("tomorrow-otc",),
        "surface": "negotiation-execution-risk-router",
        "domain": "OTC exchange bot mesh",
        "settlement": "compliant fill or safe no-trade value per dollar",
        "cade": {
            "target": "trade path, negotiation stance, counterparty route, risk hedge, and safe no-trade",
            "roster": "liquidity scout, maker/taker strategist, risk officer, compliance counsel, settlement engineer",
            "adversary": "toxic flow, adverse selection, settlement failure, regulatory breach",
            "reviewer": "compliance officer, market operator, and post-trade audit",
            "proof": "execution optimality receipt",
        },
    },
    "apparently": {
        "aliases": (),
        "surface": "regulatory-determination-hive",
        "domain": "regulatory intelligence and filing automation",
        "settlement": "verified regulatory artifact or accepted filing per dollar",
        "cade": {
            "target": "regulatory fact, legal opinion, filing packet, autonomy tier, and living supplement",
            "roster": "primary-source verifier, jurisdiction specialist, regulatory historian, operator counsel",
            "adversary": "opposing counsel, regulator deficiency reviewer, stale-law detector",
            "reviewer": "customer counsel, regulator, financial-institution reviewer",
            "proof": "regulatory determination proof pack",
        },
    },
    "smarter": {
        "aliases": (),
        "surface": "now-approve-legal-work-product",
        "domain": "legal work product and principal-fit assistant",
        "settlement": "accepted low-edit privilege-safe work product per dollar",
        "cade": {
            "target": "legal draft, principal-fit, privilege posture, citation support, obligation handling",
            "roster": "assigning principal model, citation verifier, privilege guard, opposing counsel, best associate",
            "adversary": "toughest partner, opposing counsel, court clerk, privilege waiver critic",
            "reviewer": "assigning partner, counsel, client, and later audit",
            "proof": "defensible-work receipt",
        },
    },
    "vigil": {
        "aliases": ("publius",),
        "surface": "civic-intelligence-truth-verification",
        "domain": "civic discourse analysis and truth verification",
        "settlement": "verified civic insight or debunked claim per dollar",
        "cade": {
            "target": "claim verification, source triangulation, bias detection, civic pulse, misinformation flag",
            "roster": "fact-checker, source verifier, bias auditor, civic analyst, historical context expert",
            "adversary": "misinformation advocate, selective framing critic, source reliability challenger",
            "reviewer": "editorial board, fact-check consortium, and public interest audit",
            "proof": "civic-truth proof pack",
        },
    },
    "hisanta": {
        "aliases": ("santas-secret-workshop",),
        "surface": "gamified-advent-experience-engine",
        "domain": "Christmas-themed gamified experience with advent calendar and economy",
        "settlement": "safe child-appropriate engagement event per dollar",
        "cade": {
            "target": "content safety, economy balance, advent progression, loot fairness, purchase guard",
            "roster": "content safety reviewer, economy balancer, UX tester, age-gate enforcer, fun factor scout",
            "adversary": "inappropriate content injector, economy exploiter, purchase bypass attacker",
            "reviewer": "child safety board, parent perspective, and engagement quality audit",
            "proof": "child-safe experience receipt",
        },
    },
    "galop": {
        "aliases": ("racefeed",),
        "surface": "racing-data-intelligence-feed",
        "domain": "horse racing data aggregation and intelligence",
        "settlement": "accurate race insight or prediction per dollar",
        "cade": {
            "target": "race data accuracy, odds analysis, form assessment, track condition integration, result verification",
            "roster": "data scout, form analyst, odds compiler, track specialist, result verifier",
            "adversary": "stale data injector, odds manipulation detector, false form critic",
            "reviewer": "racing authority, data integrity audit, and historical accuracy check",
            "proof": "racing-intelligence proof pack",
        },
    },
    "pareto": {
        "aliases": ("2080", "pareto-2080"),
        "surface": "portfolio-optimization-engine",
        "domain": "Pareto-optimal portfolio analysis and resource allocation",
        "settlement": "actionable optimization insight per dollar",
        "cade": {
            "target": "resource allocation, efficiency frontier, trade-off analysis, constraint satisfaction, outcome projection",
            "roster": "optimization analyst, constraint modeler, trade-off evaluator, efficiency auditor, projection verifier",
            "adversary": "overfitting critic, constraint violation detector, false optimum challenger",
            "reviewer": "portfolio committee, efficiency audit, and outcome tracking",
            "proof": "optimization-proof pack",
        },
    },
    "darwn": {
        "aliases": (),
        "surface": "evolutionary-learning-platform",
        "domain": "evolutionary and adaptive learning system",
        "settlement": "validated adaptive improvement per dollar",
        "cade": {
            "target": "fitness evaluation, mutation strategy, selection pressure, adaptation tracking, convergence verification",
            "roster": "fitness evaluator, mutation designer, selection analyst, convergence auditor, diversity guardian",
            "adversary": "premature convergence critic, overfitting detector, diversity collapse challenger",
            "reviewer": "evolution committee, adaptation audit, and generalization check",
            "proof": "evolutionary-fitness proof pack",
        },
    },
    "sustainable-barks": {
        "aliases": ("sustainable_barks",),
        "surface": "shelter-partnership-commerce-engine",
        "domain": "B2B hotel-shelter partnership and sustainable pet toy commerce",
        "settlement": "completed shelter partnership order per dollar",
        "cade": {
            "target": "order fulfillment, shelter impact tracking, partner onboarding, renewal management, bundle pricing",
            "roster": "partnership scout, fulfillment coordinator, impact tracker, renewal manager, pricing analyst",
            "adversary": "supply chain disruptor, churn predictor, margin erosion critic",
            "reviewer": "partner satisfaction, shelter impact audit, and revenue sustainability check",
            "proof": "shelter-impact proof pack",
        },
    },
}


def normalize_app(app):
    raw = str(app or "").strip().lower()
    if raw in APP_RECIPES:
        return raw
    for name, cfg in APP_RECIPES.items():
        if raw in cfg.get("aliases", ()):
            return name
    return raw or "beethoven"


def recipe_for(app):
    name = normalize_app(app)
    cfg = APP_RECIPES.get(name) or {
        "surface": "common-brain-optimization-surface",
        "domain": "general platform optimization",
        "settlement": "accepted outcome value per dollar-minute",
        "cade": {
            "target": "priority, plan, action, verification, and reuse decisions",
            "roster": "domain expert, operator, verifier, red-team reviewer, cost treasurer",
            "adversary": "wrong action, stale context, unsafe automation, wasted model spend",
            "reviewer": "owner acceptance, production telemetry, and later audit",
            "proof": "common-brain proof pack",
        },
    }
    return {
        "app": name,
        "surface": cfg["surface"],
        "domain": cfg["domain"],
        "settlement": cfg["settlement"],
        "stages": list(COMMON_STAGES),
        "cade": cfg["cade"],
        "guardrails": [
            "route crown-jewel, privileged, or proprietary context only to local or approved no-training providers",
            "never auto-execute irreversible/material actions without human gate",
            "record dissent, red-team hits, verifier receipts, and proof-pack digest",
            "persist only distilled patterns unless explicit consent allows more",
        ],
        "metrics": [
            cfg["settlement"],
            "tokens avoided by reuse",
            "minutes avoided by prebuild/cache",
            "review failures per accepted artifact",
            "rollback/escalation rate",
            "privacy/guardrail violations",
        ],
    }


def deployment_prompt(recipe):
    cade = recipe["cade"]
    return f"""Deploy the reusable Common Brain into {recipe['app']}/{recipe['surface']}.

Objective: optimize {recipe['settlement']}.

Shared brain stages:
{chr(10).join('- ' + s for s in recipe['stages'])}

CADE adaptation:
- target: {cade['target']}
- roster: {cade['roster']}
- adversary: {cade['adversary']}
- reviewer: {cade['reviewer']}
- proof: {cade['proof']}

Implementation requirements:
- import or vendor @darwin/kernel/commonBrain where the app can consume the shared TS kernel;
- wire CADE as the high-stakes decision/proof layer, not as a landing page;
- wire the agent market roles so scout/planner/drafter/verifier/red_team/judge/treasurer/privacy_officer compete by settled outcome;
- feed every accepted/rejected/edited/rolled-back outcome into the local outcome flywheel;
- publish any reusable pattern back to the capability/reuse library;
- use existing app surfaces first (Now/Approve, ops dashboard, hive admin, or release dashboard) rather than building a duplicate UI;
- add tests for at least one happy path, one red-team failure, and one guardrail stop.

Guardrails:
{chr(10).join('- ' + g for g in recipe['guardrails'])}

Metrics:
{chr(10).join('- ' + m for m in recipe['metrics'])}
"""


def _runtime_dir():
    root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".runtime")
    os.makedirs(root, exist_ok=True)
    return root


def _write_pending(payload):
    path = os.path.join(_runtime_dir(), "common_brain_pending_deployments.json")
    with open(path, "w") as f:
        json.dump(payload, f, indent=2, default=str)
    return path


def _write_snapshot(payload):
    path = os.path.join(_runtime_dir(), "common_brain_snapshot.json")
    with open(path, "w") as f:
        json.dump(payload, f, indent=2, default=str)
    return path


def _project_index():
    rows = db.select("projects", {"select": "id,name,repo_path,prod_branch"}) or []
    out = {}
    for p in rows:
        key = str(p.get("name") or "").lower()
        out[key] = p
        for canonical, cfg in APP_RECIPES.items():
            if key == canonical or key in cfg.get("aliases", ()):
                out[canonical] = p
    return out


def _already_open(project_id, slug):
    try:
        rows = db.select("tasks", {"select": "id,state", "project_id": f"eq.{project_id}",
                                   "slug": f"eq.{slug}", "limit": "1"}) or []
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
    raise last or RuntimeError("task insert failed")


def _record_deployment(recipe, project, slug, status="queued", metadata=None):
    row = {
        "recipe_key": f"{recipe['app']}:{recipe['surface']}",
        "product": recipe["app"],
        "project_id": project.get("id") if project else None,
        "task_slug": slug,
        "status": status,
        "metadata": metadata or {"surface": recipe.get("surface"), "domain": recipe.get("domain")},
    }
    try:
        db.insert("common_brain_deployments", row, upsert=True)
    except Exception:
        pass


def record_outcome(task, project="", slug="", status="queued", outcome="", tokens_avoided=0,
                   minutes_avoided=0.0, review_failures=0, rollback=False, metadata=None):
    """Update Common Brain deployment outcome if this task is one of the brain deployment jobs."""
    text = " ".join(str((task or {}).get(k) or "") for k in ("slug", "note", "prompt")).lower()
    if "common brain" not in text and not str(slug or "").startswith("improve-common-brain-"):
        return False
    patch = {
        "status": status,
        "outcome": outcome,
        "tokens_avoided": int(tokens_avoided or 0),
        "minutes_avoided": float(minutes_avoided or 0.0),
        "review_failures": int(review_failures or 0),
        "rollback": bool(rollback),
        "metadata": metadata or {},
        "updated_at": "now()",
    }
    try:
        db.update("common_brain_deployments", {"task_slug": slug or task.get("slug")}, patch)
        return True
    except Exception:
        return False


def seed_deployments(apps=None):
    recipes = [recipe_for(a) for a in (apps or APP_RECIPES.keys())]
    snapshot = {"recipes": recipes, "generated_at": int(time.time())}
    _write_snapshot(snapshot)
    try:
        projects = _project_index()
    except Exception as e:
        path = _write_pending({"error": str(e), **snapshot})
        return {"queued": [], "skipped": [], "missing": [r["app"] for r in recipes],
                "pending_file": path, "error": str(e)}

    queued, skipped, missing = [], [], []
    for recipe in recipes:
        project = projects.get(recipe["app"])
        if not project:
            missing.append(recipe["app"])
            continue
        slug = "improve-common-brain-" + re.sub(r"[^a-z0-9]+", "-", recipe["surface"].lower()).strip("-")
        if _already_open(project["id"], slug):
            _record_deployment(recipe, project, slug, status="queued",
                               metadata={"surface": recipe.get("surface"), "domain": recipe.get("domain"), "backfilled": True})
            skipped.append(slug)
            continue
        _insert_task({
            "project_id": project["id"],
            "slug": slug,
            "kind": "build",
            "state": "QUEUED",
            "prompt": deployment_prompt(recipe),
            "deps": [],
            "base_branch": project.get("prod_branch") or "main",
            "priority": 1,
            "confidence": 0.84,
            "material": False,
            "note": f"common brain deployment: {recipe['surface']}",
        })
        _record_deployment(recipe, project, slug, status="queued")
        queued.append(slug)
    result = {"queued": queued, "skipped": skipped, "missing": missing}
    try:
        db.insert("controls", {"key": "common_brain_deployments",
                               "value": json.dumps({**snapshot, **result}),
                               "updated_at": "now()"}, upsert=True)
    except Exception:
        pass
    return result


def cade_review():
    return {
        "apparently_cade": "Consensus & Adversarial Determination Engine: decompose, assemble competence roster, recursive councils, evidence weighting, blinded debate, factions/synthesis, red team, and proof pack.",
        "orchestrator_use": "Use CADE for high-stakes self-improvement, model-routing, merge/release, and queue-priority decisions with deployed-diff proof packs.",
        "tomorrow_use": "Use CADE for trade/no-trade, execution route, negotiation stance, and compliance-risk determinations with execution optimality receipts.",
        "smarter_use": "Use CADE for legal work product, principal-fit, citation, privilege, and obligation decisions with defensible-work receipts.",
        "vigil_use": "Use CADE for claim verification, source triangulation, bias detection, and civic pulse determinations with civic-truth proof packs.",
        "hisanta_use": "Use CADE for content safety, economy balance, purchase guards, and advent progression with child-safe experience receipts.",
        "galop_use": "Use CADE for race data accuracy, form assessment, odds analysis, and result verification with racing-intelligence proof packs.",
        "pareto_use": "Use CADE for resource allocation, efficiency frontier, constraint satisfaction, and outcome projection with optimization-proof packs.",
        "darwn_use": "Use CADE for fitness evaluation, mutation strategy, selection pressure, and convergence verification with evolutionary-fitness proof packs.",
        "sustainable_barks_use": "Use CADE for order fulfillment, shelter impact, partner onboarding, and renewal management with shelter-impact proof packs.",
        "common_brain_use": "CADE becomes the deliberate/prove stage inside the reusable brain, surrounded by retrieval, agent market routing, verification, outcome learning, and reuse publication.",
    }


def run():
    result = seed_deployments()
    review = cade_review()
    print(f"common_brain: queued={len(result['queued'])} skipped={len(result['skipped'])} missing={result['missing']}")
    if result.get("pending_file"):
        print(f"common_brain: pending deployments written to {result['pending_file']}")
    return {**result, "cade_review": review}


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, default=str))
