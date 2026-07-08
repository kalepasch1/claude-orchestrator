#!/usr/bin/env python3
"""
model_portfolios.py — Domain-specific model portfolios (50X routing accuracy).

A model great at CSS isn't necessarily great at database migrations. Instead of
one global Elo/reputation, maintain separate portfolios per domain:

  frontend  — CSS, HTML, Vue/React components, UI tests
  backend   — API routes, server logic, middleware, database queries
  infra     — CI/CD, Docker, deployment, monitoring, config
  data      — migrations, schema, seeds, data transforms
  docs      — README, comments, docstrings, markdown
  security  — auth, permissions, encryption, secrets, compliance
  testing   — unit tests, integration tests, e2e tests

Each domain has its own Elo, merge rate, cost-per-merge, and promotion status.
The colosseum picks the best model FOR THE SPECIFIC DOMAIN of each task.

Usage:
    import model_portfolios
    domain = model_portfolios.classify(task, diff_files)
    best = model_portfolios.best_for_domain(domain)
"""
import os, sys, json, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

DOMAINS = ("frontend", "backend", "infra", "data", "docs", "security", "testing")

# File-extension and path-based domain classification
DOMAIN_SIGNALS = {
    "frontend": {
        "extensions": {".vue", ".jsx", ".tsx", ".css", ".scss", ".less", ".html", ".svg"},
        "paths": {"components/", "pages/", "layouts/", "assets/", "public/", "styles/"},
        "keywords": {"component", "template", "style", "css", "tailwind", "ui", "button",
                     "modal", "form", "input", "responsive", "layout"},
    },
    "backend": {
        "extensions": {".py", ".ts", ".js", ".go", ".rs"},
        "paths": {"server/", "api/", "routes/", "middleware/", "services/", "utils/"},
        "keywords": {"api", "route", "handler", "middleware", "service", "controller",
                     "endpoint", "request", "response", "query"},
    },
    "infra": {
        "extensions": {".yml", ".yaml", ".toml", ".dockerfile", ".sh"},
        "paths": {"docker/", ".github/", "scripts/", "deploy/", "ci/", "infra/"},
        "keywords": {"docker", "ci", "deploy", "pipeline", "terraform", "k8s", "helm",
                     "nginx", "vercel", "supabase", "environment"},
    },
    "data": {
        "extensions": {".sql", ".prisma"},
        "paths": {"migrations/", "prisma/", "seeds/", "schema/", "db/"},
        "keywords": {"migration", "schema", "table", "column", "index", "seed",
                     "database", "alter", "create table", "prisma"},
    },
    "docs": {
        "extensions": {".md", ".mdx", ".txt", ".rst"},
        "paths": {"docs/", "wiki/"},
        "keywords": {"readme", "documentation", "docstring", "comment", "jsdoc",
                     "changelog", "contributing"},
    },
    "security": {
        "extensions": set(),
        "paths": {"auth/", "security/", "permissions/"},
        "keywords": {"auth", "permission", "credential", "secret", "encrypt", "token",
                     "jwt", "oauth", "rbac", "rls", "policy", "compliance", "gdpr"},
    },
    "testing": {
        "extensions": {".test.ts", ".test.js", ".spec.ts", ".spec.js", ".test.py"},
        "paths": {"test/", "tests/", "__tests__/", "spec/"},
        "keywords": {"test", "spec", "assert", "expect", "mock", "stub", "fixture",
                     "vitest", "jest", "pytest", "coverage"},
    },
}


def classify(task, touched_files=None):
    """Classify a task into its primary domain.

    Uses prompt keywords, file extensions, and path patterns. Returns the
    domain with the highest signal score.
    """
    prompt = (task.get("prompt") or "").lower()
    slug = (task.get("slug") or "").lower()
    files = touched_files or []

    scores = {d: 0 for d in DOMAINS}

    for domain, signals in DOMAIN_SIGNALS.items():
        # Keyword hits in prompt
        for kw in signals["keywords"]:
            if kw in prompt:
                scores[domain] += 2
            if kw in slug:
                scores[domain] += 1

        # File extension hits
        for f in files:
            f_lower = f.lower()
            for ext in signals["extensions"]:
                if f_lower.endswith(ext):
                    scores[domain] += 3
            for path in signals["paths"]:
                if path in f_lower:
                    scores[domain] += 2

    # Return highest-scoring domain (default to "backend")
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "backend"


def _portfolios():
    """Load per-domain model portfolios from controls."""
    try:
        rows = db.select("controls", {"select": "value", "key": "eq.model_portfolios"})
        if rows and rows[0].get("value"):
            v = rows[0]["value"]
            return json.loads(v) if isinstance(v, str) else v
    except Exception:
        pass
    return {}


def _save_portfolios(portfolios):
    try:
        db.upsert("controls", {"key": "model_portfolios", "value": json.dumps(portfolios)})
    except Exception:
        pass


def update(agent_id, domain, merged, cost_usd=0, wall_s=0):
    """Update a model's portfolio entry for a specific domain."""
    portfolios = _portfolios()
    key = f"{agent_id}:{domain}"

    entry = portfolios.get(key, {
        "agent_id": agent_id, "domain": domain,
        "elo": 1200, "merged": 0, "total": 0,
        "total_cost": 0, "avg_cost": 0, "avg_time_s": 0,
    })

    entry["total"] = entry.get("total", 0) + 1
    entry["total_cost"] = entry.get("total_cost", 0) + cost_usd
    entry["avg_cost"] = entry["total_cost"] / entry["total"]

    old_time = entry.get("avg_time_s", 0)
    entry["avg_time_s"] = old_time + (wall_s - old_time) / entry["total"]

    if merged:
        entry["merged"] = entry.get("merged", 0) + 1

    entry["merge_rate"] = entry["merged"] / entry["total"]
    entry["cost_per_merge"] = entry["total_cost"] / max(entry["merged"], 1)

    portfolios[key] = entry
    _save_portfolios(portfolios)
    return entry


def best_for_domain(domain, exclude_vendors=None):
    """Find the best model for a specific domain by $/merged-diff."""
    portfolios = _portfolios()
    exclude = set(exclude_vendors or [])

    candidates = []
    for key, entry in portfolios.items():
        if entry.get("domain") != domain:
            continue
        if entry.get("total", 0) < 3:
            continue  # Need enough data
        vendor = entry.get("agent_id", "").split(":")[0]
        if vendor in exclude:
            continue

        # Score: merge_rate / cost_per_merge (higher is better)
        merge_rate = entry.get("merge_rate", 0)
        cost_per_merge = entry.get("cost_per_merge", 1.0)
        score = merge_rate / max(cost_per_merge, 0.01)

        candidates.append({
            "agent_id": entry["agent_id"],
            "domain": domain,
            "score": round(score, 3),
            "merge_rate": round(merge_rate, 3),
            "cost_per_merge": round(cost_per_merge, 4),
            "elo": entry.get("elo", 1200),
            "total": entry["total"],
        })

    candidates.sort(key=lambda c: -c["score"])
    return candidates[0] if candidates else None


def domain_standings():
    """Get the best model per domain — the portfolio champions."""
    standings = {}
    for domain in DOMAINS:
        best = best_for_domain(domain)
        if best:
            standings[domain] = best
    return standings


def run():
    """Periodic: compute and log domain standings."""
    standings = domain_standings()
    if standings:
        for domain, champ in standings.items():
            print(f"[portfolios] {domain}: {champ['agent_id']} "
                  f"merge={champ['merge_rate']:.0%} $/merge=${champ['cost_per_merge']:.3f}")

        try:
            db.upsert("controls", {
                "key": "domain_standings",
                "value": json.dumps(standings, default=str)
            })
        except Exception:
            pass
