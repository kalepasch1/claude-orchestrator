#!/usr/bin/env python3
"""Continuously find fleet apps whose documented control adapter is absent or incomplete."""
import os
import re
import db
import evidence_bus

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXPECTED = ("adapter", "execute", "ingest")


def _scan(repo):
    hits = set()
    for base, dirs, files in os.walk(repo):
        dirs[:] = [d for d in dirs if d not in {"node_modules", ".git", ".nuxt", "dist", "build"}]
        for name in files:
            if name.endswith((".ts", ".js", ".py")):
                try:
                    with open(os.path.join(base, name), errors="ignore") as src: text = src.read(200000)
                    lower = text.lower()
                    if "fleet" in lower and "adapter" in lower: hits.add("adapter")
                    if "fleet" in lower and "execute" in lower: hits.add("execute")
                    if "orchestrator_ingest_url" in lower: hits.add("ingest")
                except OSError: pass
    return sorted(set(EXPECTED) - hits)


def run():
    try:
        projects = db.select("projects", {"select": "name,repo_path"}) or []
    except Exception as exc:
        print(f"fleet_e2e_audit: projects unavailable ({exc})")
        return []
    findings = []
    for project in projects:
        repo = project.get("repo_path") or ""
        if not os.path.isdir(repo):
            continue
        missing = _scan(repo)
        payload = {"repo": repo, "missing": missing, "status": "ready" if not missing else "incomplete"}
        evidence_bus.append(project["name"], "fleet.adapter.audit", project["name"], payload)
        try: db.insert("fleet_app_audits", {"app": project["name"], **payload})
        except Exception: pass
        findings.append({"app": project["name"], **payload})
    print(f"fleet_e2e_audit: audited={len(findings)} incomplete={sum(bool(x['missing']) for x in findings)}")
    return findings
