#!/usr/bin/env python3
"""Compile Common Brain deployment tasks into repo-specific patch plans.

The compiler is deliberately deterministic and retrieval-only. It runs before
strategy/coder model calls so Common Brain tasks start from concrete local repo
facts instead of asking a model to rediscover the filesystem.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


COMMON_BRAIN_MARKERS = (
    "common brain",
    "cade adaptation",
    "shared brain stages",
    "improve-common-brain-",
)


def is_common_brain_task(task):
    text = " ".join(str((task or {}).get(k) or "") for k in ("slug", "prompt", "note")).lower()
    return any(m in text for m in COMMON_BRAIN_MARKERS)


def _exists(repo, *parts):
    return os.path.exists(os.path.join(repo, *parts))


def _repo_profile(repo):
    files = {
        "package": _exists(repo, "package.json"),
        "nuxt": _exists(repo, "nuxt.config.ts") or _exists(repo, "nuxt.config.js"),
        "next": _exists(repo, "next.config.js") or _exists(repo, "next.config.mjs") or _exists(repo, "next.config.ts"),
        "vite": _exists(repo, "vite.config.ts") or _exists(repo, "vite.config.js"),
        "supabase": _exists(repo, "supabase", "migrations"),
        "server_api": _exists(repo, "server", "api"),
        "app_router": _exists(repo, "app"),
        "pages": _exists(repo, "pages"),
        "src": _exists(repo, "src"),
        "tests": _exists(repo, "tests") or _exists(repo, "test") or _exists(repo, "__tests__"),
    }
    framework = "generic"
    if files["nuxt"]:
        framework = "nuxt"
    elif files["next"]:
        framework = "next"
    elif files["vite"]:
        framework = "vite"
    return {"framework": framework, "files": files}


def _target_surface(task):
    slug = str((task or {}).get("slug") or "").lower()
    prompt = str((task or {}).get("prompt") or "").lower()
    text = f"{slug} {prompt}"
    if "tomorrow" in text or "negotiation-execution" in text:
        return "tomorrow"
    if "apparently" in text or "regulatory-determination" in text:
        return "apparently"
    if "smarter" in text or "legal-work-product" in text:
        return "smarter"
    return "orchestrator"


def compile_for_task(task, repo="", project=""):
    if not is_common_brain_task(task):
        return {"has_plan": False, "plan_text": "", "patches": [], "profile": {}}
    profile = _repo_profile(repo) if repo and os.path.isdir(repo) else {"framework": "generic", "files": {}}
    surface = _target_surface(task)
    patches = []

    if profile["files"].get("package"):
        patches.append("Add/import @darwin/kernel/commonBrain where this app can consume the shared package.")
    if profile["files"].get("server_api"):
        patches.append("Expose a small server/api common-brain route for recipe/proof-pack retrieval.")
    if profile["files"].get("supabase"):
        patches.append("Add or reuse migrations/tables for Common Brain receipts, deployment outcomes, and proof-pack digests.")
    if profile["files"].get("pages") or profile["files"].get("app_router") or profile["files"].get("src"):
        patches.append("Add the Common Brain status/proof surface to the existing ops/admin UI, not a duplicate landing page.")
    if profile["files"].get("tests"):
        patches.append("Add tests covering one accepted path, one red-team rejection, and one guardrail stop.")
    else:
        patches.append("Add a focused smoke test or unit test for the new adapter.")

    product_specific = {
        "orchestrator": "Wire settlement to rollback-free deployed diff per dollar-minute.",
        "tomorrow": "Wire settlement to compliant fill or safe no-trade execution value per dollar.",
        "apparently": "Wire settlement to verified regulatory artifact or accepted filing per dollar.",
        "smarter": "Wire settlement to accepted low-edit privilege-safe work product per dollar.",
    }[surface]
    patches.insert(0, product_specific)

    plan_text = "\n".join([
        "COMMON BRAIN COMPILER PLAN",
        f"Target surface: {surface}",
        f"Detected framework: {profile['framework']}",
        "Repo-specific patch sequence:",
        *[f"- {p}" for p in patches],
        "Keep the diff small: adapter + tests + proof/outcome receipt wiring first; defer visual polish unless already present.",
    ])
    return {
        "has_plan": True,
        "surface": surface,
        "profile": profile,
        "patches": patches,
        "plan_text": plan_text,
    }


def inject_plan(prompt, plan):
    if not plan or not plan.get("has_plan"):
        return prompt
    if "COMMON BRAIN COMPILER PLAN" in str(prompt or ""):
        return prompt
    return f"{plan['plan_text']}\n\n---\n\n{prompt}"


def task_slug_from_prompt(prompt):
    text = re.sub(r"[^a-z0-9]+", "-", str(prompt or "").lower()).strip("-")
    return text[:64] or "common-brain"
