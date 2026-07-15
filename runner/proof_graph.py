#!/usr/bin/env python3
"""Content/dependency-addressed verification proofs shared across patch flows."""
from __future__ import annotations
import hashlib, json, os, threading, time

_lock = threading.Lock()
LOCKFILES = ("package-lock.json", "pnpm-lock.yaml", "yarn.lock", "uv.lock",
             "poetry.lock", "requirements.txt", "Cargo.lock", "go.sum")

def _home():
    return os.environ.get("CLAUDE_ORCH_HOME", os.path.join(os.path.dirname(__file__), "..", ".runtime"))

def _path(): return os.path.join(_home(), "patch-proof-graph.jsonl")

def dependency_fingerprint(repo: str) -> str:
    h = hashlib.sha256()
    found = False
    for root, dirs, files in os.walk(repo):
        dirs[:] = [d for d in dirs if d not in {".git", "node_modules", ".nuxt", ".next", "dist", "build"}]
        for name in sorted(files):
            if name not in LOCKFILES: continue
            path = os.path.join(root, name); found = True
            h.update(os.path.relpath(path, repo).encode() + b"\0")
            try:
                with open(path, "rb") as f: h.update(f.read())
            except OSError: pass
    return h.hexdigest() if found else hashlib.sha256(b"no-lockfile").hexdigest()

def record(repo: str, artifact: dict, files) -> dict:
    row = {"at": time.time(), "artifact_id": artifact.get("artifact_id"),
           "commit": artifact.get("commit"), "branch": artifact.get("branch"),
           "repo": os.path.basename(repo.rstrip(os.sep)),
           "dependency_fingerprint": dependency_fingerprint(repo),
           "test_cmd": artifact.get("test_cmd"), "files": sorted(files or []),
           "batch": bool(artifact.get("batch")), "patches": int(artifact.get("patches") or 1)}
    os.makedirs(os.path.dirname(_path()), exist_ok=True)
    with _lock, open(_path(), "a") as f:
        f.write(json.dumps(row, separators=(",", ":")) + "\n")
    return row

def record_release(repo: str, release: dict, success: bool, provider="", url="") -> dict:
    """Attach deployment evidence to the same dependency-addressed proof graph."""
    row = {"at": time.time(), "type": "release", "release_id": release.get("id"),
           "commit": release.get("to_sha"), "repo": os.path.basename(repo.rstrip(os.sep)) if repo else release.get("project"),
           "dependency_fingerprint": dependency_fingerprint(repo) if repo and os.path.isdir(repo) else None,
           "success": bool(success), "provider": provider, "url": url,
           "deploy_status": release.get("deploy_status")}
    os.makedirs(os.path.dirname(_path()), exist_ok=True)
    with _lock, open(_path(), "a") as f:
        f.write(json.dumps(row, separators=(",", ":")) + "\n")
    return row

def record_verification(repo: str, commit: str, command: str, kind: str, success: bool) -> dict:
    """Record an exact commit+dependency proof for safe verification reuse."""
    row = {"at": time.time(), "type": "verification", "repo": os.path.basename(repo.rstrip(os.sep)),
           "commit": commit, "dependency_fingerprint": dependency_fingerprint(repo),
           "command": command, "kind": kind, "success": bool(success)}
    os.makedirs(os.path.dirname(_path()), exist_ok=True)
    with _lock, open(_path(), "a") as f:
        f.write(json.dumps(row, separators=(",", ":")) + "\n")
    try:
        import remote_cas
        remote_cas.put(remote_cas.key(repo, commit, row["dependency_fingerprint"], command, kind), row, success)
    except Exception:
        pass
    return row

def reusable_verification(repo: str, commit: str, command: str, kind: str, limit=5000):
    dep = dependency_fingerprint(repo)
    try:
        import remote_cas
        cached = remote_cas.get(remote_cas.key(repo, commit, dep, command, kind))
        if cached:
            return cached
    except Exception:
        pass
    try:
        with open(_path()) as f:
            rows = [json.loads(x) for x in f if x.strip()][-limit:]
    except Exception:
        return None
    for row in reversed(rows):
        if (row.get("type") == "verification" and row.get("success")
                and row.get("repo") == os.path.basename(repo.rstrip(os.sep))
                and row.get("commit") == commit and row.get("command") == command
                and row.get("kind") == kind and row.get("dependency_fingerprint") == dep):
            return row
    return None

def reusable(repo: str, test_cmd: str, files, limit=5000):
    dep = dependency_fingerprint(repo); target = set(files or [])
    try:
        with open(_path()) as f: rows = [json.loads(x) for x in f if x.strip()][-limit:]
    except Exception: return []
    return [r for r in reversed(rows) if r.get("dependency_fingerprint") == dep
            and r.get("test_cmd") == test_cmd and target.issubset(set(r.get("files") or []))]

def stats(limit=5000):
    try:
        with open(_path()) as f: rows = [json.loads(x) for x in f if x.strip()][-limit:]
    except Exception: rows = []
    return {"proofs": len(rows), "batch_proofs": sum(bool(r.get("batch")) for r in rows),
            "verification_proofs": sum(r.get("type") == "verification" and r.get("success") for r in rows),
            "dependency_fingerprints": len({r.get("dependency_fingerprint") for r in rows})}
