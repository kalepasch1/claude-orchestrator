#!/usr/bin/env python3
"""Continuously detect local/GitHub/Vercel/Supabase deployment-binding drift."""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from urllib.parse import urlparse

import db

_DIR = Path(__file__).resolve().parent
DEFAULT_MANIFEST = _DIR / "deployment_bindings.json"


def load_manifest(path=DEFAULT_MANIFEST):
    with open(path) as f:
        return json.load(f)


def _git(repo, *args):
    result = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, timeout=20)
    return result.stdout.strip() if result.returncode == 0 else ""


def _remote_identity(remote):
    """Return owner/repo for HTTPS or SSH remotes, rejecting embedded credentials."""
    value = (remote or "").strip()
    if value.startswith("git@github.com:"):
        return value.split(":", 1)[1].removesuffix(".git"), False
    parsed = urlparse(value)
    credentialed = bool(parsed.username or parsed.password)
    identity = parsed.path.strip("/").removesuffix(".git") if parsed.hostname == "github.com" else ""
    return identity, credentialed


def check_local_binding(target):
    app = target["app"]
    repo = Path(target["repo_path"]).expanduser()
    issues = []
    if not repo.is_dir():
        return [f"{app}: canonical repository is missing: {repo}"]

    remote = _git(repo, "remote", "get-url", "origin")
    identity, credentialed = _remote_identity(remote)
    if credentialed:
        issues.append(f"{app}: origin embeds credentials; use a credential-manager-backed URL")
    if identity.lower() != target["github_repo"].lower():
        issues.append(f"{app}: GitHub remote is {identity or 'unreadable'}, expected {target['github_repo']}")

    link_file = repo / ".vercel" / "project.json"
    try:
        link = json.loads(link_file.read_text())
    except (OSError, json.JSONDecodeError):
        link = {}
    linked_name = link.get("projectName")
    if linked_name != target["vercel_project"]:
        issues.append(
            f"{app}: local Vercel link is {linked_name or 'missing'}, expected {target['vercel_project']}"
        )

    expected_ref = target.get("supabase_project_ref")
    if expected_ref:
        ref_file = repo / "supabase" / ".temp" / "project-ref"
        try:
            actual_ref = ref_file.read_text().strip()
        except OSError:
            actual_ref = ""
        if actual_ref != expected_ref:
            issues.append(f"{app}: local Supabase link is {actual_ref or 'missing'}, expected {expected_ref}")
    return issues


def check_registry(targets):
    issues = []
    try:
        rows = db.select("projects", {
            "select": "name,repo_path,prod_branch,vercel_project",
            "limit": "5000",
        }) or []
    except Exception as exc:
        return [f"registry: could not read projects table: {exc}"]
    by_name = {row.get("name"): row for row in rows}
    for target in targets:
        app = target["app"]
        row = by_name.get(app)
        if not row:
            issues.append(f"{app}: missing from Orchestrator projects registry")
            continue
        checks = {
            "repo_path": target["repo_path"],
            "prod_branch": target["branch"],
            "vercel_project": target["vercel_project"],
        }
        for field, expected in checks.items():
            if row.get(field) != expected:
                issues.append(f"{app}: registry {field}={row.get(field)!r}, expected {expected!r}")
    return issues


def _file_cards(issues):
    grouped = {}
    for issue in issues:
        app = issue.split(":", 1)[0]
        grouped.setdefault(app, []).append(issue)
    for app, app_issues in grouped.items():
        title = f"Deployment binding drift: {app}"
        try:
            existing = db.select("approvals", {
                "select": "id", "project": f"eq.{app}", "status": "eq.pending",
                "title": f"eq.{title}", "limit": "1",
            }) or []
            patch = {
                "why": "\n".join(app_issues)[:1500],
                "value": "Restore the canonical GitHub/Vercel/Supabase binding before the next deploy.",
                "risk": "An improvement may deploy to a stale project or fail to reach production.",
            }
            if existing:
                db.update("approvals", {"id": existing[0]["id"]}, patch)
            else:
                db.insert("approvals", {"project": app, "kind": "ops", "title": title, **patch})
        except Exception:
            pass


def run(manifest_path=DEFAULT_MANIFEST, file_cards=True):
    manifest = load_manifest(manifest_path)
    targets = manifest.get("targets") or []
    issues = []
    for target in targets:
        issues.extend(check_local_binding(target))
    issues.extend(check_registry(targets))
    if issues and file_cards:
        _file_cards(issues)
    if issues:
        for issue in issues:
            print(f"fleet_deploy_doctor: DRIFT {issue}")
    else:
        print(f"fleet_deploy_doctor: healthy ({len(targets)} canonical bindings)")
    return issues


if __name__ == "__main__":
    raise SystemExit(1 if run() else 0)
