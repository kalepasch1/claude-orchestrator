"""
cowork_assemble.py - CLI bridge from cowork executor sessions to runner intelligence stack.

Called by cowork executor (Step 3b) to get enriched prompt, model suggestion,
cross-project hints, EV score, and Vercel config — without needing runner.py running.

Usage:
    python3 cowork_assemble.py \
        --task-id <uuid> \
        --slug <slug> \
        --kind <kind> \
        --attempt <N> \
        --repo-path <path> \
        --project-id <uuid> \
        --project-name <name>

Returns JSON to stdout:
{
  "enriched_prompt": "...",
  "layers_used": [...],
  "model_suggestion": "claude-haiku-4-5-20251001",
  "model_reason": "...",
  "cross_project_hints": [...],
  "reuse_notes": "...",
  "ev_score": 0.0,
  "vercel_token": "...",
  "vercel_project_map": {...},
  "vercel_team_id": "...",
  "context_pack_summary": "...",
  "preopt_available": false
}
"""
import sys, os, json, argparse, time, re

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Load .env from runner dir
_env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.exists(_env_path):
    with open(_env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _safe_import(name):
    """Import a module by name, returning None on any failure.

    Used to optionally pull in runner-internal modules (db, prompt_assembler,
    etc.) that may not be available when called outside the runner venv.
    """
    try:
        return __import__(name)
    except Exception:
        return None


def get_vercel_config():
    """Read non-secret Vercel metadata for Cowork agents.

    Cowork tasks must never receive the account token: direct CLI deployments
    bypass Git branch gates, release batching, and production verification.
    """
    token = os.environ.get("VERCEL_TOKEN", "")
    team_id = os.environ.get("VERCEL_TEAM_ID", "")
    project_map = {}

    # Collect VERCEL_PROJECT_* from env
    for k, v in os.environ.items():
        if k.startswith("VERCEL_PROJECT_") and k != "VERCEL_PROJECT_ID":
            proj_name = k[len("VERCEL_PROJECT_"):].lower()
            project_map[proj_name] = v

    # Try to supplement from fleet_config
    try:
        db = _safe_import("db")
        if db:
            rows = db.select("fleet_config", {"select": "key,value"}) or []
            for row in rows:
                k = row.get("key", "")
                v = row.get("value")
                if k == "VERCEL_TOKEN" and not token:
                    token = str(v).strip('"')
                elif k == "VERCEL_TEAM_ID" and not team_id:
                    team_id = str(v).strip('"')
                elif k.startswith("VERCEL_PROJECT_"):
                    proj_name = k[len("VERCEL_PROJECT_"):].lower()
                    if proj_name not in project_map and v:
                        project_map[proj_name] = str(v).strip('"')
    except Exception:
        pass

    return {"token": "", "team_id": team_id, "project_map": project_map}


def get_enriched_prompt(task_id, slug, kind, attempt, repo_path, project_id, project_name):
    """Build enriched prompt using prompt_assembler if available."""
    layers_used = []

    # Try full prompt_assembler first
    try:
        import prompt_assembler
        task_dict = {
            "id": task_id,
            "slug": slug,
            "kind": kind,
            "attempt": attempt,
            "repo_path": repo_path,
            "project_id": project_id,
            "project_name": project_name,
        }
        # Fetch real task from DB
        db = _safe_import("db")
        if db:
            rows = db.select("tasks", {"select": "*", "id": f"eq.{task_id}"}) or []
            if rows:
                task_dict.update(rows[0])

        enriched = prompt_assembler.assemble(task_dict)
        if enriched and enriched.get("prompt"):
            layers_used = enriched.get("layers", [])
            return enriched["prompt"], layers_used
    except Exception as e:
        pass

    # Fallback: fetch raw prompt from DB
    prompt = ""
    try:
        db = _safe_import("db")
        if db:
            rows = db.select("tasks", {"select": "prompt,kind,slug", "id": f"eq.{task_id}"}) or []
            if rows:
                row = rows[0]
                prompt = row.get("prompt", "")
                if not kind:
                    kind = row.get("kind", "")
    except Exception:
        pass

    layers_used = ["raw_prompt"]

    # Add minimal context layers manually
    if repo_path and os.path.exists(repo_path):
        layers_used.append("repo_path_verified")

    if project_name:
        prompt = f"[Project: {project_name}]\n\n{prompt}"
        layers_used.append("project_context")

    return prompt, layers_used


def get_model_suggestion(kind, attempt, slug):
    """Suggest model based on task kind and attempt number."""
    try:
        import model_router
        task_dict = {"kind": kind, "attempt": attempt, "slug": slug}
        result = model_router.route(task_dict)
        if result:
            return result.get("model", ""), result.get("reason", "")
    except Exception:
        pass

    # Fallback heuristic
    attempt = int(attempt or 0)
    default = os.environ.get("ORCH_DEFAULT_MODEL", "claude-haiku-4-5-20251001")
    escalation = os.environ.get("ORCH_ESCALATION_MODEL", "claude-sonnet-5")
    hard = os.environ.get("ORCH_HARD_MODEL", "claude-opus-4-8")

    kind = (kind or "").lower()
    heavy_kinds = {"improve-architecture", "improve-ux", "improve-performance", "build"}

    if attempt >= 3:
        return hard, "attempt>=3: escalate to hard model"
    elif attempt >= 1 or kind in heavy_kinds:
        return escalation, f"attempt={attempt} or heavy kind={kind}"
    else:
        return default, "haiku-first: cheapest capable model"


def get_cross_project_hints(slug, kind, prompt):
    """Get reuse hints from cross-project template library."""
    hints = []
    try:
        import cross_project_templates
        task_dict = {"slug": slug, "kind": kind, "prompt": prompt}
        result = cross_project_templates.find_templates(task_dict)
        if result:
            hints = result.get("hints", [])
    except Exception:
        pass

    if not hints:
        try:
            import reuse_first
            task_dict = {"slug": slug, "kind": kind, "prompt": prompt}
            result = reuse_first.check(task_dict)
            if result and result.get("matches"):
                hints = [f"reuse: {m}" for m in result["matches"][:5]]
        except Exception:
            pass

    return hints


def get_reuse_notes(slug, kind, prompt):
    """Check for existing implementations to reuse."""
    try:
        import reuse_first
        task_dict = {"slug": slug, "kind": kind, "prompt": prompt}
        result = reuse_first.check(task_dict)
        if result:
            return result.get("summary", "")
    except Exception:
        pass
    return ""


def get_ev_score(task_id):
    """Get EV score from ev_scheduler or tasks.confidence."""
    try:
        import ev_scheduler
        score = ev_scheduler.score(task_id)
        if score is not None:
            return float(score)
    except Exception:
        pass

    # Fallback: read from DB
    try:
        db = _safe_import("db")
        if db:
            rows = db.select("tasks", {"select": "confidence", "id": f"eq.{task_id}"}) or []
            if rows and rows[0].get("confidence") is not None:
                return float(rows[0]["confidence"])
    except Exception:
        pass

    return 0.0


def get_preopt_cache(task_id):
    """Check if queue_preopt has cached data for this task."""
    try:
        import queue_preopt
        cached = queue_preopt.get_cache(task_id)
        if cached:
            summary = []
            if cached.get("context_pack"):
                summary.append("context_pack")
            if cached.get("precedent"):
                summary.append("precedent")
            if cached.get("unified_knowledge"):
                summary.append("unified_knowledge")
            if cached.get("ensemble_predictor"):
                summary.append("ensemble_predictor")
            return True, ", ".join(summary)
    except Exception:
        pass
    return False, ""


def main():
    parser = argparse.ArgumentParser(description="Cowork intelligence assembler")
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--slug", default="")
    parser.add_argument("--kind", default="")
    parser.add_argument("--attempt", type=int, default=0)
    parser.add_argument("--repo-path", default="")
    parser.add_argument("--project-id", default="")
    parser.add_argument("--project-name", default="")
    args = parser.parse_args()

    result = {}

    # 1. Enriched prompt
    enriched_prompt, layers_used = get_enriched_prompt(
        args.task_id, args.slug, args.kind, args.attempt,
        args.repo_path, args.project_id, args.project_name
    )
    result["enriched_prompt"] = enriched_prompt
    result["layers_used"] = layers_used

    # 2. Model suggestion
    model, model_reason = get_model_suggestion(args.kind, args.attempt, args.slug)
    result["model_suggestion"] = model
    result["model_reason"] = model_reason

    # 3. Cross-project hints
    result["cross_project_hints"] = get_cross_project_hints(
        args.slug, args.kind, enriched_prompt
    )

    # 4. Reuse notes
    result["reuse_notes"] = get_reuse_notes(args.slug, args.kind, enriched_prompt)

    # 5. EV score
    result["ev_score"] = get_ev_score(args.task_id)

    # 6. Vercel config
    vercel = get_vercel_config()
    result["vercel_token"] = vercel["token"]
    result["vercel_project_map"] = vercel["project_map"]
    result["vercel_team_id"] = vercel["team_id"]

    # 7. Preopt cache
    preopt_available, context_pack_summary = get_preopt_cache(args.task_id)
    result["preopt_available"] = preopt_available
    result["context_pack_summary"] = context_pack_summary

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
