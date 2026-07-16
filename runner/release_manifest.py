#!/usr/bin/env python3
"""Content-addressed, immutable release manifests and gate receipts."""
import hashlib
import json
import os
import subprocess
import time


def _home():
    return os.environ.get("CLAUDE_ORCH_HOME", os.path.join(os.path.dirname(__file__), "..", ".runtime"))


def _dir():
    path = os.path.join(_home(), "release-manifests")
    os.makedirs(path, exist_ok=True)
    return path


def _git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, timeout=60)


def dependency_fingerprint(repo, ref=None):
    digest = hashlib.sha256()
    found = False
    for name in ("package-lock.json", "pnpm-lock.yaml", "yarn.lock", "uv.lock", "poetry.lock",
                 "requirements.txt", "Cargo.lock", "go.sum"):
        if ref:
            shown = subprocess.run(["git", "show", f"{ref}:{name}"], cwd=repo, capture_output=True, timeout=60)
            content = shown.stdout if shown.returncode == 0 else None
        else:
            path = os.path.join(repo, name)
            content = open(path, "rb").read() if os.path.isfile(path) else None
        if content is not None:
            found = True; digest.update(name.encode() + b"\0"); digest.update(content)
    return digest.hexdigest() if found else "none"


def changed_files(repo, base_sha, candidate_sha):
    result = _git(repo, "diff", "--name-only", f"{base_sha}..{candidate_sha}")
    return sorted(x for x in result.stdout.splitlines() if x) if result.returncode == 0 else []


def _commit_in_range(repo, commit, base_sha, candidate_sha):
    if not commit:
        return False
    inside = _git(repo, "merge-base", "--is-ancestor", str(commit), candidate_sha).returncode == 0
    already = _git(repo, "merge-base", "--is-ancestor", str(commit), base_sha).returncode == 0
    return inside and not already


def discover_tasks(database, project_id, repo, base_sha, candidate_sha, limit=5000):
    """Bind the frozen candidate to the exact merged task artifacts it contains."""
    if not project_id:
        return []
    rows = database.select("tasks", {
        "select": "id,slug,state,artifact_commit,artifact_ref,model,execution_lane",
        "project_id": f"eq.{project_id}", "state": "eq.MERGED",
        "order": "updated_at.desc", "limit": str(limit),
    }) or []
    found = []
    for row in rows:
        if _commit_in_range(repo, row.get("artifact_commit"), base_sha, candidate_sha):
            found.append({key: row.get(key) for key in
                          ("id", "slug", "artifact_commit", "artifact_ref", "model", "execution_lane")
                          if row.get(key) is not None})
    return sorted(found, key=lambda row: str(row.get("slug") or row.get("id") or ""))


def find_candidate(project, candidate_sha):
    """Find a frozen manifest by release identity without relying on DB schema changes."""
    try:
        names = os.listdir(_dir())
    except OSError:
        return None
    for name in names:
        if not name.endswith(".json") or name.endswith(".gates.json"):
            continue
        try:
            with open(os.path.join(_dir(), name), encoding="utf-8") as source:
                manifest = json.load(source)
            if manifest.get("project") == project and manifest.get("candidate_sha") == candidate_sha:
                return manifest
        except (OSError, ValueError):
            continue
    return None


def create(project, repo, base_sha, candidate_sha, *, test_cmd="", build_cmd="", tasks=None):
    body = {
        "schema": 1, "project": project, "repo": os.path.basename(repo.rstrip(os.sep)),
        "base_sha": base_sha, "candidate_sha": candidate_sha,
        "changed_files": changed_files(repo, base_sha, candidate_sha),
        "dependency_fingerprint": dependency_fingerprint(repo, candidate_sha),
        "test_cmd": test_cmd or "", "build_cmd": build_cmd or "",
        "tasks": sorted(tasks or [], key=lambda x: str(x.get("slug") or x.get("id") or "")),
    }
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"))
    manifest_id = hashlib.sha256(canonical.encode()).hexdigest()
    body.update({"id": manifest_id, "created_at": time.time(), "gates": {}})
    path = os.path.join(_dir(), manifest_id + ".json")
    if not os.path.exists(path):
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as target:
            json.dump(body, target, indent=2, sort_keys=True)
        os.replace(tmp, path)
    return body


def load(manifest_id):
    with open(os.path.join(_dir(), manifest_id + ".json"), encoding="utf-8") as source:
        return json.load(source)


def record_gate(manifest_id, gate, ok, *, command="", duration_ms=0, detail=""):
    manifest = load(manifest_id)
    manifest.setdefault("gates", {})[gate] = {
        "ok": bool(ok), "command": command, "duration_ms": int(duration_ms or 0),
        "detail": str(detail or "")[-1000:], "at": time.time(),
    }
    path = os.path.join(_dir(), manifest_id + ".json")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as target:
        json.dump(manifest, target, indent=2, sort_keys=True)
    os.replace(tmp, path)
    return manifest


def validate(repo, manifest):
    current = _git(repo, "rev-parse", manifest.get("candidate_sha", ""))
    if current.returncode != 0:
        return False, "candidate commit missing"
    if dependency_fingerprint(repo, manifest.get("candidate_sha")) != manifest.get("dependency_fingerprint"):
        return False, "dependency lock fingerprint changed"
    actual = changed_files(repo, manifest.get("base_sha"), manifest.get("candidate_sha"))
    if actual != manifest.get("changed_files", []):
        return False, "candidate file set changed"
    return True, "immutable candidate verified"
