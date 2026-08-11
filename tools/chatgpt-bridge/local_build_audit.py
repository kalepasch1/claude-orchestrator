#!/usr/bin/env python3
"""Find local ChatGPT/Codex build residue and register it with orchestrator intake.

The patch bridge previously handled only files a user manually copied into
``~/Documents/chatgpt-dropbox``.  Code left in a Codex worktree, a local-only
branch, a stash, an output bundle, or the bridge's ``_failed`` directory could
remain invisible to the task queue forever.  This scanner closes that gap.

It is deliberately conservative:

* source artifacts and worktrees are read-only and are never deleted or reset;
* one deterministic reconciliation task is emitted per app/snapshot;
* evidence is old enough to be considered abandoned unless ``--force`` is used;
* task prompts require item-by-item classification before any code is applied;
* a local registry plus deterministic task slugs make repeated sweeps idempotent.

The normal caller is ``watch-dropbox.sh``.  Run ``--force --stale-hours 0`` for
an explicit legacy sweep.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
ORCH_ROOT = HERE.parent.parent
BINDINGS = ORCH_ROOT / "runner" / "deployment_bindings.json"
DEFAULT_CODEX_ROOT = Path.home() / "Documents" / "Codex"
DEFAULT_DOCUMENTS_ROOT = Path.home() / "Documents"
DEFAULT_DROPBOX = Path.home() / "Documents" / "chatgpt-dropbox"
DEFAULT_INTAKE = ORCH_ROOT / "intake"
DEFAULT_STATE = DEFAULT_DROPBOX / "_logs" / "local-build-audit.json"

ARTIFACT_SUFFIXES = (".patch", ".diff", ".zip", ".tgz", ".tar.gz")
SKIP_DIRS = {
    ".git", "node_modules", ".nuxt", ".output", "dist", "build", "coverage",
    ".pytest_cache", "__pycache__", ".next", ".turbo",
}
ALIASES = {
    "claude-orchestrator": "beethoven",
    "orchestrator": "beethoven",
    "madeus": "beethoven",
    "2080": "pareto-2080",
    "pareto": "pareto-2080",
    "pmi": "prediction-markets-institute",
    "hisanta": "santas-secret-workshop",
    "galop": "racefeed",
    "pasch": "kalepasch-com",
    "trojun": "illuminati",
    "darwinlife": "darwn",
}


def _git(path: Path, *args: str, timeout: int = 90) -> tuple[int, str]:
    env = dict(os.environ)
    # A sandboxed audit must not fail merely because the user's global config is
    # outside its read grant. Repository-local config is still honored.
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    try:
        proc = subprocess.run(
            ["git", *args], cwd=str(path), env=env, capture_output=True, text=True,
            errors="replace", timeout=timeout, check=False,
        )
        return proc.returncode, (proc.stdout or "").strip()
    except (OSError, subprocess.SubprocessError):
        return -1, ""


def _json_read(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return default


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _acquire_run_lock(state_path: Path):
    """Hold one scanner writer per registry; return None when another run owns it."""
    lock_path = state_path.with_name(state_path.name + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        return None
    return handle


def _slug(text: str, limit: int = 64) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")[:limit] or "unknown"


def _fingerprint(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()


def _file_sha(path: Path) -> str:
    h = hashlib.sha256()
    try:
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return "unreadable"


def load_targets(bindings_path: Path = BINDINGS) -> dict[str, Path]:
    data = _json_read(bindings_path, {})
    targets: dict[str, Path] = {}
    for row in data.get("targets", []) if isinstance(data, dict) else []:
        app, raw = row.get("app"), row.get("repo_path")
        if app and raw:
            targets[str(app)] = Path(str(raw)).expanduser()
    return targets


def infer_project(path: Path, targets: dict[str, Path], hint: str = "") -> str:
    try:
        resolved = path.resolve(strict=False)
    except OSError:
        resolved = path
    for app, root in sorted(targets.items(), key=lambda item: len(str(item[1])), reverse=True):
        try:
            if resolved == root.resolve(strict=False) or resolved.is_relative_to(root.resolve(strict=False)):
                return app
        except (OSError, ValueError, AttributeError):
            if str(resolved).startswith(str(root).rstrip("/") + "/"):
                return app

    haystack = " ".join((hint, path.name, str(path))).lower()
    candidates = list(targets) + list(ALIASES)
    for name in sorted(candidates, key=len, reverse=True):
        variants = {name, name.replace("-", "_"), name.replace("-", " "), name.replace("-", "")}
        if any(v and v in haystack for v in variants):
            return ALIASES.get(name, name)
    return "beethoven"


def infer_artifact_project(path: Path, targets: dict[str, Path]) -> str:
    """Resolve bridge/output artifacts from their explicit filename prefix first."""
    base = path.name.lower()
    # The watcher archives files as YYYYMMDD-HHMMSS--<original-name>.
    base = re.sub(r"^\d{8}-\d{6}--", "", base)
    explicit = base.split("--", 1)[0]
    explicit = re.sub(r"\.(patch|diff|zip|tgz|tar\.gz)$", "", explicit)
    if explicit in targets:
        return explicit
    if explicit in ALIASES and ALIASES[explicit] in targets:
        return ALIASES[explicit]
    # Conventional output names such as illuminati-fixed.zip have a single dash.
    first = re.split(r"[-_.]", explicit, maxsplit=1)[0]
    if first in targets:
        return first
    if first in ALIASES and ALIASES[first] in targets:
        return ALIASES[first]
    return infer_project(path, targets)


def _changed_files(worktree: Path) -> list[str]:
    names: set[str] = set()
    for args in (("diff", "--name-only"), ("diff", "--cached", "--name-only"),
                 ("ls-files", "--others", "--exclude-standard")):
        rc, out = _git(worktree, *args)
        if rc == 0:
            names.update(
                line.strip() for line in out.splitlines()
                if line.strip() and not _is_scanner_output(line.strip())
            )
    return sorted(names)


def _is_scanner_output(name: str) -> bool:
    """True for audit intake files emitted by this scanner itself.

    Without this exclusion, an old untracked intake manifest eventually becomes
    stale evidence in the orchestrator worktree; processing or replacing that
    manifest then changes the dirty snapshot and recursively creates another
    audit task.
    """
    normalized = str(name or "").replace("\\", "/").lstrip("./")
    return (normalized.startswith("intake/")
            and "chatgpt-local-audit" in Path(normalized).name)


def _newest_file_mtime(worktree: Path, names: list[str]) -> float:
    stamps = []
    for name in names:
        try:
            stamps.append((worktree / name).stat().st_mtime)
        except OSError:
            continue
    return max(stamps) if stamps else 0.0


def _tree_newest_mtime(root: Path) -> float:
    """Newest readable file mtime without failing on protected secret/env paths."""
    newest = 0.0
    for current, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for filename in files:
            # The audit never needs secret-bearing local configuration to decide
            # whether a code tree is stale.
            if filename == ".env" or filename.startswith(".env."):
                continue
            try:
                newest = max(newest, (Path(current) / filename).stat().st_mtime)
            except OSError:
                continue
    return newest


def _worktrees(repo: Path) -> list[Path]:
    rc, out = _git(repo, "worktree", "list", "--porcelain")
    if rc != 0:
        return [repo]
    paths = [Path(line.split(" ", 1)[1]) for line in out.splitlines() if line.startswith("worktree ")]
    return paths or [repo]


def _default_branch(repo: Path) -> str:
    rc, out = _git(repo, "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD")
    if rc == 0 and out:
        return out.removeprefix("origin/")
    return "main"


def scan_repo(app: str, repo: Path, cutoff: float) -> tuple[list[dict[str, Any]], set[Path]]:
    evidence: list[dict[str, Any]] = []
    known_worktrees: set[Path] = set()
    if not (repo / ".git").exists():
        return evidence, known_worktrees

    for wt in _worktrees(repo):
        known_worktrees.add(wt.resolve(strict=False))
        if not wt.is_dir():
            continue
        names = _changed_files(wt)
        newest = _newest_file_mtime(wt, names)
        if names and (not cutoff or newest <= cutoff):
            _rc, branch = _git(wt, "symbolic-ref", "--quiet", "--short", "HEAD")
            _rc, head = _git(wt, "rev-parse", "HEAD")
            evidence.append({
                "kind": "dirty_worktree", "path": str(wt), "branch": branch or "DETACHED",
                "head": head[:40], "change_count": len(names), "changes": names[:100],
                "changes_digest": _fingerprint(names),
                "newest_change_mtime": int(newest),
            })

    # Branch tips that contain commits not reachable from any remote are durable
    # only on this machine. Record tips, not every ancestor, to keep prompts compact.
    rc, out = _git(repo, "rev-list", "--branches", "--not", "--remotes=*")
    local_oids = set(out.splitlines()) if rc == 0 else set()
    rc, refs = _git(
        repo, "for-each-ref",
        "--format=%(refname:short)%1f%(objectname)%1f%(committerdate:unix)%1f%(subject)",
        "refs/heads",
    )
    branch_rows = []
    if rc == 0:
        for line in refs.splitlines():
            parts = line.split("\x1f", 3)
            if len(parts) != 4:
                continue
            name, oid, stamp, subject = parts
            when = int(stamp or 0)
            if oid in local_oids and (not cutoff or when <= cutoff):
                branch_rows.append({"ref": name, "sha": oid, "committed_at": when,
                                    "subject": subject[:240]})
    if branch_rows:
        evidence.append({"kind": "local_only_branch_tips", "repo": str(repo),
                         "count": len(branch_rows), "branches": branch_rows[:300]})

    # Remote ChatGPT/Codex branches can still be absent from the orchestrator queue.
    # Only record ones not merged into the default remote branch.
    default_ref = "origin/" + _default_branch(repo)
    session_rows = []
    if rc == 0:
        for line in refs.splitlines():
            parts = line.split("\x1f", 3)
            if len(parts) != 4 or not parts[0].startswith(("chatgpt/", "codex/")):
                continue
            name, oid, stamp, subject = parts
            when = int(stamp or 0)
            if cutoff and when > cutoff:
                continue
            merged_rc, _ = _git(repo, "merge-base", "--is-ancestor", oid, default_ref)
            if merged_rc != 0:
                session_rows.append({"ref": name, "sha": oid, "committed_at": when,
                                     "subject": subject[:240]})
    if session_rows:
        evidence.append({"kind": "unmerged_chatgpt_codex_branches", "repo": str(repo),
                         "count": len(session_rows), "branches": session_rows[:300]})

    rc, stashes = _git(repo, "stash", "list", "--format=%H%x1f%ct%x1f%gd%x1f%gs")
    stash_rows = []
    if rc == 0:
        for line in stashes.splitlines():
            parts = line.split("\x1f", 3)
            if len(parts) == 4 and (not cutoff or int(parts[1] or 0) <= cutoff):
                stash_rows.append({"sha": parts[0], "created_at": int(parts[1] or 0),
                                   "ref": parts[2], "subject": parts[3][:240]})
    if stash_rows:
        evidence.append({"kind": "stashes", "repo": str(repo), "count": len(stash_rows),
                         "items": stash_rows[:300]})

    rc, rescues = _git(
        repo, "for-each-ref",
        "--format=%(refname)%1f%(objectname)%1f%(creatordate:unix)%1f%(subject)",
        "refs/orch-rescue",
    )
    rescue_rows = []
    if rc == 0:
        for line in rescues.splitlines():
            parts = line.split("\x1f", 3)
            if len(parts) == 4 and (not cutoff or int(parts[2] or 0) <= cutoff):
                rescue_rows.append({"ref": parts[0], "sha": parts[1],
                                    "created_at": int(parts[2] or 0), "subject": parts[3][:240]})
    if rescue_rows:
        evidence.append({"kind": "orchestrator_rescue_refs", "repo": str(repo),
                         "count": len(rescue_rows), "items": rescue_rows})
    return evidence, known_worktrees


def _walk_codex_git_roots(codex_root: Path) -> list[Path]:
    roots = []
    if not codex_root.is_dir():
        return roots
    for current, dirs, files in os.walk(codex_root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        if ".git" in dirs or ".git" in files:
            roots.append(Path(current))
            if ".git" in dirs:
                dirs.remove(".git")
    return roots


def scan_codex(
    codex_root: Path, targets: dict[str, Path], known_worktrees: set[Path], cutoff: float,
) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for root in _walk_codex_git_roots(codex_root):
        resolved = root.resolve(strict=False)
        if resolved in known_worktrees:
            continue
        rc, top = _git(root, "rev-parse", "--show-toplevel")
        project = infer_project(root, targets, top)
        if rc != 0:
            newest = _tree_newest_mtime(root)
            if not cutoff or newest <= cutoff:
                grouped.setdefault(project, []).append({
                    "kind": "broken_codex_git_worktree", "path": str(root),
                    "error": "git metadata no longer resolves", "newest_mtime": int(newest),
                })
            continue
        names = _changed_files(root)
        newest = _newest_file_mtime(root, names)
        if names and (not cutoff or newest <= cutoff):
            _rc, branch = _git(root, "symbolic-ref", "--quiet", "--short", "HEAD")
            _rc, head = _git(root, "rev-parse", "HEAD")
            grouped.setdefault(project, []).append({
                "kind": "detached_codex_worktree", "path": str(root),
                "branch": branch or "DETACHED", "head": head[:40],
                "change_count": len(names), "changes": names[:100],
                "changes_digest": _fingerprint(names),
                "newest_change_mtime": int(newest),
            })

    # Only treat explicit session outputs as standalone artifacts. Patches inside
    # a copied repository are source files owned by that repository snapshot.
    for current, dirs, files in os.walk(codex_root) if codex_root.is_dir() else []:
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        base = Path(current)
        if "outputs" not in base.parts:
            continue
        for filename in files:
            path = base / filename
            low = filename.lower()
            if not low.endswith(ARTIFACT_SUFFIXES) or low.endswith("-src.tar.gz"):
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            if cutoff and stat.st_mtime > cutoff:
                continue
            project = infer_artifact_project(path, targets)
            grouped.setdefault(project, []).append({
                "kind": "codex_output_artifact", "path": str(path), "size": stat.st_size,
                "mtime": int(stat.st_mtime), "sha256": _file_sha(path),
            })
    return grouped


def scan_unregistered_repos(
    documents_root: Path,
    targets: dict[str, Path],
    known_worktrees: set[Path],
    cutoff: float,
) -> dict[str, list[dict[str, Any]]]:
    """Find legacy/renamed repositories outside the canonical deployment registry."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    if not documents_root.is_dir():
        return grouped
    target_roots = {p.resolve(strict=False) for p in targets.values()}
    excluded_roots = set(known_worktrees) | target_roots
    hard_excludes = {
        (documents_root / "Codex").resolve(strict=False),
        (documents_root / "chatgpt-dropbox").resolve(strict=False),
    }
    for current, dirs, _files in os.walk(documents_root):
        root = Path(current)
        resolved = root.resolve(strict=False)
        if resolved in hard_excludes or resolved in excluded_roots:
            dirs[:] = []
            continue
        kept = []
        for name in dirs:
            child = (root / name).resolve(strict=False)
            if name == ".git":
                kept.append(name)
                continue
            if name in SKIP_DIRS or name.endswith("-wt") or child in excluded_roots or child in hard_excludes:
                continue
            kept.append(name)
        dirs[:] = kept
        if ".git" not in dirs:
            continue
        dirs.remove(".git")
        project = infer_project(root, targets)
        rows, attached = scan_repo(project, root, cutoff)
        known_worktrees.update(attached)
        if rows:
            grouped.setdefault(project, []).append({
                "kind": "unregistered_local_repo", "path": str(root),
                "routing": project,
                "note": "repo is not present in runner/deployment_bindings.json; verify canonical ownership",
            })
            grouped[project].extend(rows)
        # A base checkout may contain generated trees but should not contain another
        # independent application unless it is explicitly registered as a target.
        dirs[:] = []
    return grouped


def scan_dropbox(dropbox: Path, targets: dict[str, Path], cutoff: float) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for state in ("pending", "failed", "applied"):
        root = dropbox if state == "pending" else dropbox / ("_" + state)
        if not root.is_dir():
            continue
        for path in root.iterdir():
            low = path.name.lower()
            if not path.is_file() or not low.endswith(ARTIFACT_SUFFIXES) or low.endswith("-src.tar.gz"):
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            if cutoff and stat.st_mtime > cutoff:
                continue
            project = infer_artifact_project(path, targets)
            row = {"kind": "chatgpt_bridge_artifact", "status": state, "path": str(path),
                   "size": stat.st_size, "mtime": int(stat.st_mtime), "sha256": _file_sha(path)}
            sidecar = Path(str(path) + (".error.txt" if state == "failed" else ".result.txt"))
            if sidecar.is_file():
                try:
                    row["bridge_result_tail"] = sidecar.read_text(
                        encoding="utf-8", errors="replace"
                    )[-4000:]
                except OSError:
                    pass
            grouped.setdefault(project, []).append(row)
    return grouped


def artifact_evidence(
    path: Path, status: str, targets: dict[str, Path], result_file: Path | None = None,
) -> tuple[str, dict[str, Any]]:
    stat = path.stat()
    row: dict[str, Any] = {
        "kind": "chatgpt_bridge_artifact", "status": status, "path": str(path),
        "size": stat.st_size, "mtime": int(stat.st_mtime), "sha256": _file_sha(path),
    }
    if result_file and result_file.is_file():
        row["bridge_result_tail"] = result_file.read_text(
            encoding="utf-8", errors="replace"
        )[-4000:]
    return infer_artifact_project(path, targets), row


def _compact_evidence_for_prompt(evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep queue prompts bounded while preserving a digest of the complete snapshot."""
    compact = []
    for original in evidence:
        row = dict(original)
        for key in ("changes", "branches", "items"):
            value = row.get(key)
            if isinstance(value, list) and len(value) > 30:
                row[key + "_total"] = len(value)
                row[key + "_digest"] = _fingerprint(value)
                row[key + "_sample"] = value[:30]
                del row[key]
        compact.append(row)
    return compact


def _render_task(project: str, evidence: list[dict[str, Any]], fp: str) -> str:
    slug = f"chatgpt-local-reconcile-{_slug(project, 30)}-{fp[:12]}"
    evidence_json = json.dumps(_compact_evidence_for_prompt(evidence), indent=2, sort_keys=True)
    return f"""PROJECT: {project}

- id: {slug}
  title: Reconcile local ChatGPT/Codex build evidence for {project}
  material: yes
  depends: []
  proof: every evidence item is classified and all still-useful absent code is durably queued or integrated
  prompt: |
    Reconcile the local ChatGPT/Codex build evidence below without destroying or overwriting it.

    This is a recovery-and-consideration task, not permission to prefer legacy code over current code.
    Treat every source path, stash, rescue ref, and worktree as read-only. Compare each item against
    the current default branch, remote branches, merged history, and live orchestrator tasks. Classify
    each item as ALREADY_PRESENT, SUPERSEDED_BY_NEWER, ACTIVE_IN_ANOTHER_TASK, RECOVERABLE_VALUE, or
    CONFLICTED_NEEDS_FOCUSED_TASK. The newest/most complete implementation wins.

    For RECOVERABLE_VALUE, work only in a newly allocated isolated worktree, apply the minimum coherent
    diff, run relevant tests, and deliver through the normal agent branch + merge train. For conflicts,
    queue a focused follow-up rather than forcing an overwrite. Do not delete, reset, clean, pop, or move
    the evidence source. Do not duplicate work already represented by a live task or remote branch.

    Write one `coordination_tasks` recovery-ledger record per evidence item using audit fingerprint
    `{fp}`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
{chr(10).join('    ' + line for line in evidence_json.splitlines())}
"""


def queue_groups(
    groups: dict[str, list[dict[str, Any]]], intake: Path, state_path: Path,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    state = _json_read(state_path, {"schema": 1, "queued": {}, "last_run": 0})
    state.setdefault("queued", {})
    legacy_migration = "evidence" not in state
    state.setdefault("evidence", {})
    queued, duplicates = [], []
    intake.mkdir(parents=True, exist_ok=True)
    for project, items in sorted(groups.items()):
        if not items:
            continue
        ordered = sorted(items, key=lambda row: (str(row.get("kind")), str(row.get("path", row.get("repo", "")))))
        legacy_fp = _fingerprint({"project": project, "evidence": ordered})
        item_rows = [
            (_fingerprint({"project": project, "evidence": item}), item)
            for item in ordered
        ]
        # Upgrade schema-1 registries without replaying an identical historical
        # group. If the old aggregate fingerprint matches, every member was
        # already represented by that queued manifest.
        if legacy_migration and legacy_fp in state["queued"]:
            prior = state["queued"][legacy_fp]
            for item_fp, item in item_rows:
                state["evidence"].setdefault(item_fp, {
                    "project": project, "slug": prior.get("slug"),
                    "kind": item.get("kind"), "migrated_from": legacy_fp,
                })
            duplicates.append({"project": project, "fingerprint": legacy_fp,
                               "slug": prior.get("slug")})
            continue
        unseen = [(item_fp, item) for item_fp, item in item_rows
                  if item_fp not in state["evidence"]]
        if not unseen:
            prior_slug = next((state["evidence"][item_fp].get("slug")
                               for item_fp, _ in item_rows), None)
            duplicates.append({"project": project, "fingerprint": legacy_fp,
                               "slug": prior_slug or "already-covered"})
            continue
        new_items = [item for _, item in unseen]
        fp = _fingerprint({"project": project, "evidence": new_items})
        slug = f"chatgpt-local-reconcile-{_slug(project, 30)}-{fp[:12]}"
        filename = f"chatgpt-local-audit-{_slug(project, 40)}-{fp[:12]}.md"
        path = intake / filename
        if not path.exists():
            tmp = path.with_name(path.name + ".tmp")
            tmp.write_text(_render_task(project, new_items, fp), encoding="utf-8")
            os.replace(tmp, path)
        state["queued"][fp] = {"project": project, "slug": slug, "intake": str(path),
                                "created_at": int(time.time()), "items": len(new_items)}
        for item_fp, item in unseen:
            state["evidence"][item_fp] = {
                "project": project, "slug": slug, "kind": item.get("kind"),
                "intake": str(path), "created_at": int(time.time()),
            }
        queued.append({"project": project, "fingerprint": fp, "slug": slug, "intake": str(path)})
    state["schema"] = 2
    state["last_run"] = int(time.time())
    _atomic_json(state_path, state)
    return queued, duplicates


def write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == ".md":
        lines = ["# ChatGPT/Codex local build audit", "", f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S %Z')}", ""]
        counts = report.get("counts", {})
        lines.extend([
            f"- Registered repositories scanned: {counts.get('repositories', 0)}",
            f"- Evidence items found: {counts.get('evidence_items', 0)}",
            f"- Queue intake tasks created: {len(report.get('queued', []))}",
            f"- Duplicate snapshots skipped: {len(report.get('duplicates', []))}", "",
            "## Queue registrations", "",
        ])
        for row in report.get("queued", []):
            lines.append(f"- `{row['project']}` → `{row['slug']}` ({row['intake']})")
        lines.extend(["", "## Evidence by project", ""])
        for project, items in sorted((report.get("evidence") or {}).items()):
            kinds: dict[str, int] = {}
            for item in items:
                kinds[item.get("kind", "unknown")] = kinds.get(item.get("kind", "unknown"), 0) + 1
            lines.append(f"- `{project}`: " + ", ".join(f"{k}={v}" for k, v in sorted(kinds.items())))
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    else:
        _atomic_json(path, report)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex-root", type=Path, default=DEFAULT_CODEX_ROOT)
    parser.add_argument("--documents-root", type=Path, default=DEFAULT_DOCUMENTS_ROOT)
    parser.add_argument("--dropbox", type=Path, default=DEFAULT_DROPBOX)
    parser.add_argument("--intake", type=Path, default=DEFAULT_INTAKE)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--bindings", type=Path, default=BINDINGS)
    parser.add_argument("--stale-hours", type=float, default=6.0)
    parser.add_argument("--min-interval-minutes", type=float, default=30.0)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--artifact", type=Path)
    parser.add_argument("--artifact-status", choices=("pending", "failed", "applied"), default="pending")
    parser.add_argument("--result-file", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)

    # launchd may start the bridge while an explicit deep audit is still walking
    # the fleet. Both runs write the same registry at completion, so serialize the
    # entire scan rather than relying only on atomic replace for the final write.
    _run_lock = _acquire_run_lock(args.state)
    if _run_lock is None:
        print(json.dumps({"status": "already_running", "state": str(args.state)}))
        return 0

    prior = _json_read(args.state, {"last_run": 0})
    due = time.time() - float(prior.get("last_run", 0)) >= args.min_interval_minutes * 60
    if not args.force and not args.artifact and not due:
        print(json.dumps({"status": "rate_limited", "last_run": prior.get("last_run", 0)}))
        return 0

    targets = load_targets(args.bindings)
    groups: dict[str, list[dict[str, Any]]] = {}
    if args.artifact:
        project, row = artifact_evidence(args.artifact, args.artifact_status, targets, args.result_file)
        groups[project] = [row]
    else:
        cutoff = 0.0 if args.stale_hours <= 0 else time.time() - args.stale_hours * 3600
        known_worktrees: set[Path] = set()
        for app, repo in targets.items():
            rows, worktrees = scan_repo(app, repo, cutoff)
            known_worktrees.update(worktrees)
            if rows:
                groups.setdefault(app, []).extend(rows)
        for source in (
            scan_codex(args.codex_root, targets, known_worktrees, cutoff),
            scan_unregistered_repos(args.documents_root, targets, known_worktrees, cutoff),
            scan_dropbox(args.dropbox, targets, cutoff),
        ):
            for app, rows in source.items():
                groups.setdefault(app, []).extend(rows)

    queued, duplicates = queue_groups(groups, args.intake, args.state)
    report = {
        "schema": 1, "generated_at": int(time.time()), "stale_hours": args.stale_hours,
        "counts": {"repositories": len(targets),
                   "evidence_items": sum(len(items) for items in groups.values())},
        "evidence": groups, "queued": queued, "duplicates": duplicates,
    }
    if args.report:
        write_report(args.report, report)
    print(json.dumps({"status": "ok", "projects": len(groups),
                      "evidence_items": report["counts"]["evidence_items"],
                      "queued": len(queued), "duplicates": len(duplicates)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
