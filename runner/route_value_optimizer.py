#!/usr/bin/env python3
"""Confidence-gated routing objective based on verified deployment value.

Small samples stay in exploration.  Production allocation begins only after a
route has enough observations, and scores favor verified deployment evidence
over tests or merges.  Release attribution is conservative: an integrated
outcome only receives deployment credit when the same project has a successful
release after that outcome within the attribution window.
"""
import math
import os
import time

MIN_SAMPLES = int(os.environ.get("ROUTE_VALUE_MIN_SAMPLES", "20"))
MIN_DEPLOYS = int(os.environ.get("ROUTE_VALUE_MIN_DEPLOYS", "2"))
ATTRIBUTION_DAYS = int(os.environ.get("ROUTE_VALUE_ATTRIBUTION_DAYS", "14"))
_CACHE = {"t": 0.0, "rows": []}


def wilson_lower(successes, total, z=1.96):
    if total <= 0:
        return 0.0
    p = max(0.0, min(1.0, float(successes) / total))
    den = 1.0 + z * z / total
    center = p + z * z / (2.0 * total)
    margin = z * math.sqrt((p * (1.0 - p) + z * z / (4.0 * total)) / total)
    return max(0.0, (center - margin) / den)


def provider_of(model):
    value = str(model or "").lower()
    if value.startswith("cowork"):
        return "cowork"
    if value.startswith("swarm:"):
        parts = value.split(":")
        return parts[1] if len(parts) > 1 else "swarm"
    if not value or value == "none":
        return "unknown"
    if value.startswith("ollama") or any(tag in value for tag in (":3b", ":7b", ":8b", ":14b", ":16b", ":22b", ":30b", ":32b", ":70b")):
        return "local"
    if "deepseek" in value:
        return "deepseek"
    if "grok" in value:
        return "xai"
    if "gemini" in value:
        return "google"
    if value.startswith(("gpt", "o1", "o3", "o4", "o5", "codex")):
        return "openai"
    if value.startswith(("claude", "sonnet", "opus", "haiku")):
        return "claude"
    if "groq" in value:
        return "groq"
    return "local"


def attach_release_evidence(outcomes, releases):
    """Return copies of outcomes with conservative inferred deployment flags."""
    import datetime
    success = {}
    for release in releases or []:
        if str(release.get("deploy_status") or "").lower() not in ("success", "ready", "deployed", "green"):
            continue
        project = str(release.get("project") or "").strip().lower()
        at = str(release.get("deployed_at") or release.get("created_at") or "")
        if project and at:
            success.setdefault(project, []).append(at)
    horizon = datetime.timedelta(days=ATTRIBUTION_DAYS)
    result = []
    for original in outcomes or []:
        row = dict(original)
        if row.get("deployed") or str(row.get("deploy_status") or "").lower() in ("success", "ready", "deployed", "green"):
            row["deployment_evidence"] = "outcome"
            result.append(row); continue
        project = str(row.get("project") or "").strip().lower()
        created = str(row.get("created_at") or "")
        if not row.get("integrated"):
            result.append(row)
            continue
        try:
            start = datetime.datetime.fromisoformat(created.replace("Z", "+00:00"))
            for value in success.get(project, []):
                deployed = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
                if deployed >= start and deployed - start <= horizon:
                    row["deployed"] = True
                    row["deployment_evidence"] = "project-release-window"
                    break
        except Exception:
            pass
        result.append(row)
    return result


def summarize(rows, provider=None):
    selected = [r for r in rows or [] if provider is None or provider_of(r.get("model")) == provider]
    n = len(selected)
    deployed = sum(1 for r in selected if r.get("deployed") or str(r.get("deploy_status") or "").lower() in ("success", "ready", "deployed", "green"))
    integrated = sum(1 for r in selected if r.get("integrated"))
    tested = sum(1 for r in selected if r.get("tests_passed"))
    minutes = sum(max(0.01, float(r.get("wall_ms") or 0) / 60000.0) for r in selected)
    usd = sum(float(r.get("usd") or 0) for r in selected)
    # Deployment is the objective. Merge/test credit is deliberately tiny and
    # only keeps new routes comparable while they collect deployment samples.
    value = deployed + 0.15 * max(0, integrated - deployed) + 0.02 * max(0, tested - integrated)
    lower = wilson_lower(deployed, n)
    confident = n >= MIN_SAMPLES and deployed >= MIN_DEPLOYS
    value_per_min = value / max(1.0, minutes)
    usd_per_value = usd / max(0.25, value)
    score = lower * math.log1p(value_per_min * 10.0) / (1.0 + usd_per_value) if confident else 0.0
    return {"n": n, "deployed": deployed, "integrated": integrated, "tested": tested,
            "deployment_lower_bound": round(lower, 5), "value_per_min": round(value_per_min, 5),
            "usd_per_value": round(usd_per_value, 5), "confident": confident,
            "score": round(score, 5)}


def live_rows():
    if time.time() - _CACHE["t"] < 300:
        return _CACHE["rows"]
    try:
        import db
        try:
            outcomes = db.select("outcomes", {"select": "id,task_id,slug,model,project,kind,integrated,tests_passed,usd,wall_ms,deployed,deploy_status,created_at", "order": "created_at.desc", "limit": "5000"}) or []
        except Exception:
            outcomes = db.select("outcomes", {"select": "id,task_id,slug,model,project,kind,integrated,tests_passed,usd,wall_ms,created_at", "order": "created_at.desc", "limit": "5000"}) or []
        releases = db.select("releases", {"select": "project,deploy_status,deployed_at,created_at", "order": "created_at.desc", "limit": "1000"}) or []
        _CACHE["rows"] = attach_release_evidence(outcomes, releases)
        try:
            import release_attribution
            _CACHE["rows"] = release_attribution.apply(_CACHE["rows"])
        except Exception:
            pass
    except Exception:
        _CACHE["rows"] = []
    _CACHE["t"] = time.time()
    return _CACHE["rows"]


def provider_score(provider):
    return summarize(live_rows(), provider).get("score", 0.0)
