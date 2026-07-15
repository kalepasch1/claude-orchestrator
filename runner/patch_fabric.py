#!/usr/bin/env python3
"""Content-addressed, verified patch execution fabric.

API model output is inventory, not completed work.  This module turns a unified
diff into an immutable artifact, applies it only inside an isolated worktree,
runs the project's real test command, and commits ``agent/<slug>``.  The normal
integration sweeper/merge train can then integrate it exactly like Cowork or CLI
work.  No successful result is reported without a materialized, tested branch.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import time
from typing import Any


def extract_diff(text: str) -> str:
    raw = str(text or "").strip()
    fences = re.findall(r"```(?:diff|patch)?\s*\n(.*?)```", raw, re.S | re.I)
    candidates = fences + [raw]
    for candidate in candidates:
        starts = [i for i in (candidate.find("diff --git "), candidate.find("--- a/")) if i >= 0]
        if starts:
            diff=candidate[min(starts):].strip()
            lines=diff.splitlines()
            # Local code models often indent every line after the first as if the
            # patch were Markdown. Infer that wrapper indent from Git metadata and
            # remove it uniformly, preserving indentation inside hunk content.
            indents=[]
            for line in lines[1:]:
                stripped=line.lstrip(" ")
                if stripped.startswith(("diff --git ","new file mode ","deleted file mode ",
                                        "index ","--- ","+++ ","@@ ")):
                    n=len(line)-len(stripped)
                    if n:indents.append(n)
            if indents:
                n=min(indents);prefix=" "*n
                lines=[lines[0]]+[line[n:] if line.startswith(prefix) else line for line in lines[1:]]
            return "\n".join(lines).strip() + "\n"
    return ""


def artifact_id(base_sha: str, diff_text: str) -> str:
    return hashlib.sha256((str(base_sha) + "\0" + str(diff_text)).encode("utf-8")).hexdigest()


def _git(repo: str, *args: str, timeout: int = 60, input_text: str | None = None):
    return subprocess.run(
        ["git", *args], cwd=repo, input=input_text, capture_output=True,
        text=True, timeout=timeout,
    )


def _safe_slug(slug: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "-", str(slug or "patch"))[:100]


def _artifact_dir() -> str:
    home = os.environ.get(
        "CLAUDE_ORCH_HOME",
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".runtime"),
    )
    return os.path.join(home, "patch-fabric")


def _reset_isolated_worktree(wt: str):
    """Discard only this fabric-owned worktree's failed attempt, including new files."""
    _git(wt, "reset", "--hard", "HEAD")
    _git(wt, "clean", "-fd")


def _borrow_dependencies(repo: str, wt: str):
    """Temporarily share immutable dependency trees with an isolated worktree.

    Git worktrees intentionally omit ignored node_modules directories. Reinstalling
    them per patch is both slow and a common false-negative source. Symlinks are
    removed before commit, so dependency contents never enter the patch artifact.
    """
    shared_names = ("node_modules", ".nuxt", ".next")
    candidates = [(os.path.join(repo, name), os.path.join(wt, name)) for name in shared_names]
    try:
        for name in os.listdir(repo):
            for shared in shared_names:
                src = os.path.join(repo, name, shared)
                if os.path.isdir(src):
                    candidates.append((src, os.path.join(wt, name, shared)))
    except OSError:
        pass
    linked = []
    for src, dst in candidates:
        if not os.path.isdir(src) or os.path.lexists(dst):
            continue
        try:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            os.symlink(src, dst, target_is_directory=True)
            linked.append(dst)
        except OSError:
            pass
    return linked


def _release_dependencies(paths):
    for path in paths:
        try:
            if os.path.islink(path):
                os.unlink(path)
        except OSError:
            pass


def _persist(aid: str, payload: dict):
    try:
        root = _artifact_dir()
        os.makedirs(root, exist_ok=True)
        path = os.path.join(root, aid + ".json")
        tmp = path + f".{os.getpid()}.tmp"
        with open(tmp, "w") as f:
            json.dump(payload, f, sort_keys=True, indent=2)
        os.replace(tmp, path)
        return path
    except OSError:
        return ""


def affected_files(model_output: str) -> set[str]:
    diff = extract_diff(model_output)
    files = set()
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            files.add(line[6:].strip())
        elif line.startswith("diff --git a/"):
            parts = line.split()
            if len(parts) >= 4 and parts[3].startswith("b/"):
                files.add(parts[3][2:])
    return files


def conflict_free_groups(items: list[dict], max_size: int = 8) -> list[list[dict]]:
    """Greedily partition generated patches so no batch writes the same path."""
    groups: list[list[dict]] = []
    occupied: list[set[str]] = []
    for item in items:
        files = affected_files(item.get("model_output") or item.get("text") or "")
        placed = False
        if files:
            for idx, used in enumerate(occupied):
                if len(groups[idx]) < max_size and not (files & used):
                    groups[idx].append(item); used.update(files); placed = True; break
        if not placed:
            groups.append([item]); occupied.append(set(files))
    return groups


def _load(aid: str) -> dict:
    try:
        with open(os.path.join(_artifact_dir(), aid + ".json")) as f:
            row = json.load(f)
        return row if isinstance(row, dict) else {}
    except Exception:
        return {}


def materialize(
    task: dict,
    repo: str,
    base: str,
    model_output: str,
    test_cmd: str,
    timeout: int = 600,
) -> dict[str, Any]:
    """Apply, test, and commit a model-produced patch in an isolated worktree."""
    started = time.time()
    slug = _safe_slug(task.get("slug") or task.get("id") or "patch")
    branch = f"agent/{slug}"
    diff_text = extract_diff(model_output)
    if not diff_text:
        return {"ok": False, "stage": "extract", "reason": "model returned no unified diff"}
    if "GIT binary patch" in diff_text or "../" in diff_text:
        return {"ok": False, "stage": "safety", "reason": "unsafe or binary patch"}

    requested_base = base
    base_sha_r = _git(repo, "rev-parse", base)
    # Project metadata can lag a repository's main/master migration.  Falling
    # back to the checked-out HEAD keeps the canary and normal fast lane alive
    # without guessing a remote branch or mutating the primary checkout.
    if base_sha_r.returncode != 0:
        base = "HEAD"
        base_sha_r = _git(repo, "rev-parse", base)
    if base_sha_r.returncode != 0:
        return {"ok": False, "stage": "base", "reason": (base_sha_r.stderr or "unknown base")[-500:]}
    base_sha = base_sha_r.stdout.strip()
    aid = artifact_id(base_sha, diff_text)

    # Content-addressed replay: the exact transformation against the exact base was
    # already tested and committed. Reuse the proof if the commit still exists.
    cached = _load(aid)
    if cached.get("commit"):
        exists = _git(repo, "cat-file", "-e", f"{cached['commit']}^{{commit}}")
        if exists.returncode == 0:
            return {"ok": True, **cached, "reused": True, "artifact_path": os.path.join(_artifact_dir(), aid + ".json"),
                    "wall_s": round(time.time() - started, 3)}

    check = _git(repo, "apply", "--check", "--3way", input_text=diff_text)
    if check.returncode != 0:
        return {"ok": False, "stage": "apply-check", "reason": (check.stderr or check.stdout)[-1000:], "artifact_id": aid}

    wt = os.path.join(os.path.dirname(repo), os.path.basename(repo) + "-wt", slug)
    os.makedirs(os.path.dirname(wt), exist_ok=True)
    # Reuse a valid worktree/branch; otherwise recreate only this task's isolated path.
    if not os.path.isdir(wt):
        existing = _git(repo, "show-ref", "--verify", "--quiet", f"refs/heads/{branch}")
        args = ["worktree", "add", "-f", wt, branch] if existing.returncode == 0 else ["worktree", "add", "-b", branch, wt, base]
        added = _git(repo, *args, timeout=120)
        if added.returncode != 0:
            return {"ok": False, "stage": "worktree", "reason": (added.stderr or added.stdout)[-1000:], "artifact_id": aid}

    applied = _git(wt, "apply", "--3way", input_text=diff_text)
    if applied.returncode != 0:
        _reset_isolated_worktree(wt)
        return {"ok": False, "stage": "apply", "reason": (applied.stderr or applied.stdout)[-1000:], "artifact_id": aid}

    changed = _git(wt, "status", "--porcelain")
    if not changed.stdout.strip():
        return {"ok": False, "stage": "empty", "reason": "patch produced no changes", "artifact_id": aid}

    borrowed = _borrow_dependencies(repo, wt)
    try:
        test = subprocess.run(
            test_cmd or "true", cwd=wt, shell=True, capture_output=True, text=True,
            timeout=max(30, int(timeout)), env={**os.environ, "CI": "true"},
        )
    finally:
        _release_dependencies(borrowed)
    test_log = ((test.stdout or "") + "\n" + (test.stderr or ""))[-12000:]
    if test.returncode != 0:
        _reset_isolated_worktree(wt)
        return {
            "ok": False, "stage": "test", "reason": test_log[-2000:],
            "artifact_id": aid, "test_returncode": test.returncode,
            "wall_s": round(time.time() - started, 3),
        }

    _git(wt, "add", "-A")
    committed = _git(wt, "commit", "-m", f"[patch-fabric] {slug}", timeout=120)
    if committed.returncode != 0:
        return {"ok": False, "stage": "commit", "reason": (committed.stderr or committed.stdout)[-1000:], "artifact_id": aid}
    commit = _git(wt, "rev-parse", "HEAD").stdout.strip()
    stat = _git(wt, "diff", "--stat", f"{base}...HEAD").stdout[-4000:]
    payload = {
        "artifact_id": aid, "base_sha": base_sha, "base": base,
        "repository": repo,
        "requested_base": requested_base, "branch": branch, "commit": commit,
        "task_id": task.get("id"), "slug": slug, "diff_sha256": hashlib.sha256(diff_text.encode()).hexdigest(),
        "diff_bytes": len(diff_text.encode()), "stat": stat, "test_cmd": test_cmd,
        "test_log": test_log[-5000:], "created_at": time.time(),
    }
    try:
        import hermetic_cas, merge_certificate, transformation_market
        hermetic_cas.store(repo,commit,test_cmd,True,artifact_id=aid)
        payload["merge_certificate"]=merge_certificate.issue(repo,payload,affected_files(diff_text))
        transformation_market.record(task,diff_text,payload)
    except Exception:
        pass
    path = _persist(aid, payload)
    try:
        import proof_graph
        proof_graph.record(repo, payload, affected_files(diff_text))
        import symbol_context
        symbol_context.precompute(repo, commit=commit)
        import activation_proof
        activation_proof.record("patch_fabric", "outcome", True, task_id=task.get("id"),
                                artifact_id=aid, commit=commit, reused=False)
    except Exception:
        pass
    return {
        "ok": True, **payload, "artifact_path": path,
        "wall_s": round(time.time() - started, 3),
    }


def materialize_batch(items: list[dict], repo: str, base: str, test_cmd: str,
                      timeout: int = 900) -> dict[str, Any]:
    """Compose non-conflicting patches in a branchless Git index and test once.

    No branch or ordinary worktree exists until every patch applies to the same
    base. The aggregate commit is tested detached; only a passing proof receives
    an ``agent/batch-*`` ref.
    """
    started = time.time()
    if not items:
        return {"ok": False, "stage": "empty", "reason": "no batch items"}
    normalized = []
    used = set()
    for item in items:
        diff = extract_diff(item.get("model_output") or item.get("text") or "")
        files = affected_files(diff)
        if not diff:
            return {"ok": False, "stage": "extract", "reason": "batch item returned no diff"}
        if not files or files & used:
            return {"ok": False, "stage": "conflict", "reason": "overlapping or unknown patch paths"}
        if "GIT binary patch" in diff or "../" in diff:
            return {"ok": False, "stage": "safety", "reason": "unsafe or binary batch patch"}
        used.update(files)
        normalized.append((item, diff, files))

    requested_base = base
    base_r = _git(repo, "rev-parse", base)
    if base_r.returncode != 0:
        base = "HEAD"; base_r = _git(repo, "rev-parse", base)
    if base_r.returncode != 0:
        return {"ok": False, "stage": "base", "reason": base_r.stderr[-500:]}
    base_sha = base_r.stdout.strip()
    digest_input = base_sha + "\0" + "\0".join(
        hashlib.sha256(diff.encode()).hexdigest() for _item, diff, _files in normalized)
    aid = hashlib.sha256(digest_input.encode()).hexdigest()
    cached = _load(aid)
    if cached.get("commit") and _git(repo, "cat-file", "-e", f"{cached['commit']}^{{commit}}").returncode == 0:
        # A batch proof is shared, but delivery is task-addressed.  Recreate the
        # task aliases on cache hits as refs may have been pruned since proof.
        task_branches = {}
        for item, _diff, _files in normalized:
            task = item.get("task") or {}
            slug = task.get("slug")
            if slug:
                alias = f"agent/{slug}"
                if _git(repo, "branch", "-f", alias, cached["commit"]).returncode == 0:
                    task_branches[str(task.get("id"))] = alias
        cached["task_branches"] = task_branches
        return {"ok": True, **cached, "reused": True,
                "wall_s": round(time.time() - started, 3)}

    root = _artifact_dir()
    os.makedirs(os.path.join(root, "indexes"), exist_ok=True)
    index_path = os.path.join(root, "indexes", aid + ".index")
    try:
        os.remove(index_path)
    except FileNotFoundError:
        pass
    env = {**os.environ, "GIT_INDEX_FILE": index_path}
    def git_index(*args, input_text=None, limit=120):
        return subprocess.run(["git", *args], cwd=repo, env=env, input=input_text,
                              capture_output=True, text=True, timeout=limit)
    read = git_index("read-tree", base_sha)
    if read.returncode != 0:
        return {"ok": False, "stage": "overlay", "reason": read.stderr[-1000:]}
    for item, diff, _files in normalized:
        applied = git_index("apply", "--cached", "--3way", input_text=diff)
        if applied.returncode != 0:
            return {"ok": False, "stage": "overlay-apply", "task_id": (item.get("task") or {}).get("id"),
                    "reason": (applied.stderr or applied.stdout)[-1200:]}
    tree_r = git_index("write-tree")
    if tree_r.returncode != 0:
        return {"ok": False, "stage": "write-tree", "reason": tree_r.stderr[-1000:]}
    author = {**os.environ, "GIT_AUTHOR_NAME": "Orchestrator Patch Fabric",
              "GIT_AUTHOR_EMAIL": "orchestrator@local",
              "GIT_COMMITTER_NAME": "Orchestrator Patch Fabric",
              "GIT_COMMITTER_EMAIL": "orchestrator@local"}
    commit_r = subprocess.run(
        ["git", "commit-tree", tree_r.stdout.strip(), "-p", base_sha,
         "-m", f"[patch-fabric batch] {aid[:16]}"], cwd=repo, env=author,
        capture_output=True, text=True, timeout=120)
    if commit_r.returncode != 0:
        return {"ok": False, "stage": "commit-tree", "reason": commit_r.stderr[-1000:]}
    commit = commit_r.stdout.strip()

    try:
        import hermetic_cas
        cas_hit=hermetic_cas.lookup(repo,commit,test_cmd)
    except Exception: cas_hit=None
    wt = os.path.join(os.path.dirname(repo), os.path.basename(repo) + "-wt", "batch-" + aid[:16])
    remote=None
    if not cas_hit and os.environ.get("ORCH_VERIFICATION_REMOTE","false").lower() in ("1","true","yes"):
        try:
            import verification_client
            remote=verification_client.verify(repo,commit,test_cmd,
                timeout=int(os.environ.get("ORCH_VERIFICATION_REMOTE_WAIT","20")),
                image=os.environ.get("ORCH_VERIFICATION_OCI_IMAGE",""))
            if remote.get("passed"):
                cas_hit={**(remote.get("result") or {}),
                         "key":remote.get("result_digest") or remote.get("action_digest") or "remote"}
        except Exception:remote=None
    if cas_hit:
        test_log=f"verified by hermetic CAS {cas_hit['key']}"
    else:
        if os.path.isdir(wt):
            _git(repo, "worktree", "remove", "--force", wt, timeout=120)
        add = _git(repo, "worktree", "add", "--detach", wt, commit, timeout=120)
        if add.returncode != 0:
            return {"ok": False, "stage": "worktree", "reason": add.stderr[-1000:]}
        borrowed = _borrow_dependencies(repo, wt)
        try:
            test = subprocess.run(test_cmd or "true", cwd=wt, shell=True, capture_output=True,
                                  text=True, timeout=max(30, timeout), env={**os.environ, "CI": "true"})
        finally:
            _release_dependencies(borrowed)
        test_log = ((test.stdout or "") + "\n" + (test.stderr or ""))[-12000:]
        if test.returncode != 0:
            _git(repo, "worktree", "remove", "--force", wt, timeout=120)
            return {"ok": False, "stage": "test", "reason": test_log[-2500:],
                    "test_returncode": test.returncode, "artifact_id": aid,
                    "wall_s": round(time.time() - started, 3)}
    branch = "agent/batch-" + aid[:16]
    branch_r = _git(repo, "branch", "-f", branch, commit)
    if os.path.isdir(wt): _git(repo, "worktree", "remove", "--force", wt, timeout=120)
    if branch_r.returncode != 0:
        return {"ok": False, "stage": "branch", "reason": branch_r.stderr[-1000:]}
    # Materialize per-task delivery aliases only after the aggregate commit has
    # passed.  Merge/release trains consume task-addressed refs, while all aliases
    # retain the exact same proven commit and CAS certificate.
    task_branches = {}
    for item, _diff, _files in normalized:
        task = item.get("task") or {}
        slug = task.get("slug")
        if not slug:
            continue
        alias = f"agent/{slug}"
        alias_r = _git(repo, "branch", "-f", alias, commit)
        if alias_r.returncode != 0:
            return {"ok": False, "stage": "task-branch", "task_id": task.get("id"),
                    "reason": alias_r.stderr[-1000:]}
        task_branches[str(task.get("id"))] = alias
    payload = {
        "artifact_id": aid, "batch": True, "base": base, "requested_base": requested_base,
        "repository": repo,
        "base_sha": base_sha, "branch": branch, "commit": commit,
        "task_ids": [(x.get("task") or {}).get("id") for x, _d, _f in normalized],
        "slugs": [(x.get("task") or {}).get("slug") for x, _d, _f in normalized],
        "affected_files": sorted(used), "patches": len(normalized),
        "diff_bytes": sum(len(d.encode()) for _x, d, _f in normalized),
        "test_cmd": test_cmd, "test_log": test_log[-5000:], "created_at": time.time(),
        "cas_hit":bool(cas_hit), "remote_verification":remote, "task_branches": task_branches,
    }
    try:
        import hermetic_cas,merge_certificate,transformation_market
        if not cas_hit: hermetic_cas.store(repo,commit,test_cmd,True,artifact_id=aid,batch=True)
        payload["merge_certificate"]=merge_certificate.issue(repo,payload,used)
        components=[]
        for item,diff,files in normalized:
            transformation_market.record(item.get("task") or {},diff,payload)
            components.append(merge_certificate.issue(repo,payload,files))
        payload["component_certificates"]=components
        payload["certificates_composable"]=merge_certificate.composable(components)
    except Exception: pass
    _persist(aid, payload)
    try:
        import proof_graph
        proof_graph.record(repo, payload, used)
        import symbol_context
        symbol_context.precompute(repo, commit=commit)
        import activation_proof
        activation_proof.record("patch_fabric", "outcome", True, artifact_id=aid,
                                patches=len(normalized), commit=commit)
    except Exception:
        pass
    return {"ok": True, **payload, "wall_s": round(time.time() - started, 3)}


if __name__ == "__main__":
    print("patch_fabric is a library; call materialize(task, repo, base, output, test_cmd)")
