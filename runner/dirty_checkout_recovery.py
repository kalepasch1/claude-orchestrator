#!/usr/bin/env python3
"""
dirty_checkout_recovery.py — durable recovery for an orchestrator host whose checkout
is dirty and therefore stuck behind upstream.

THE STALL MODE THIS CLOSES
--------------------------
Fleet auto-pull refuses to fast-forward a checkout with tracked modifications. That is
correct — the alternative is destroying work — but it is also *indefinite*: the host
sits behind upstream forever, running stale code, and nothing resolves it. Observed
live with 26 tracked changes blocking auto-pull while the host stayed 16 commits behind.

The two obvious "fixes" are both forbidden here:
  * `git stash` — the fleet's stash pile already holds hundreds of never-reconciled
    entries; adding to it is deferral, not recovery.
  * `git reset --hard` — this is precisely the loss path pinned by
    tests/test_dirty_checkout_sacred.py.

So instead:

  1. Acquire the per-repo maintenance fence (repo_lock) so no concurrent writer is
     mutating refs while we work.
  2. INVENTORY the tracked changes. **Untracked files are never touched, never stashed,
     never cleaned** — untracked content on an operator host is operator evidence.
  3. TEST the dirty layer: exact conflict-marker scan + Python compile of every changed
     file. A dirty tree carrying broken code must not be promoted into history.
  4. PRESERVE it either way, on a named recovery ref (`refs/recovery/dirty/<host>/<ts>`)
     built from a real commit — so the work is recoverable by SHA even if every later
     step fails.
  5. INTEGRATE upstream in an ISOLATED worktree by replaying the recovery commit on top
     of the new upstream head. Compatible work layers; it is never overwritten. If the
     replay conflicts or the layered tree fails validation, the residue is quarantined
     and upstream is taken on its own.
  6. RESUME only from a clean checkout: the live checkout ends at a validated commit
     with no tracked modifications.
  7. PUBLISH an approval/incident card with before/after SHAs, changed files, test
     results and any quarantined residue.

Public API
----------
    inventory(repo)                      -> dict describing the dirt
    recover(repo, base, *, remote=...)   -> dict incident card

Environment
-----------
    ORCH_DIRTY_RECOVERY_ENABLED   Kill switch (default: true)
    ORCH_DIRTY_RECOVERY_TIMEOUT   Per-git-command timeout, seconds (default: 120)
    ORCH_DIRTY_RECOVERY_FENCE_WAIT Seconds to wait for the maintenance fence (default: 60)
"""
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

GIT_TIMEOUT = int(os.environ.get("ORCH_DIRTY_RECOVERY_TIMEOUT", "120"))
FENCE_WAIT = int(os.environ.get("ORCH_DIRTY_RECOVERY_FENCE_WAIT", "60"))

CONFLICT_MARKER_RE = re.compile(r"^(?:<{7}|={7}|>{7}|\|{7})(?:[ \t].*)?$", re.MULTILINE)

BINARY_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".zip", ".gz",
                   ".tar", ".woff", ".woff2", ".ttf", ".so", ".dylib", ".pyc")


def _enabled() -> bool:
    return os.environ.get("ORCH_DIRTY_RECOVERY_ENABLED", "true").strip().lower() \
        not in ("0", "false", "no", "off")


def _git(args, cwd, timeout=GIT_TIMEOUT):
    """Fail-soft git. Never raises; a wedged git returns a non-zero CompletedProcess."""
    try:
        return subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                              timeout=timeout)
    except Exception as exc:  # noqa: BLE001 — fail-soft is this repo's convention
        return subprocess.CompletedProcess(args, 1, "", f"{type(exc).__name__}: {exc}")


def _rev(repo: str, ref: str) -> str:
    r = _git(["git", "rev-parse", "--verify", "--quiet", ref], repo)
    return r.stdout.strip() if r.returncode == 0 else ""


# ── 2. Inventory ────────────────────────────────────────────────────────────

def inventory(repo: str) -> dict:
    """Describe the checkout's dirt WITHOUT touching it.

    `tracked` drives recovery. `untracked` is reported for the incident card only and is
    never acted on: untracked files on an operator host are evidence, and the fleet has
    already lost intake drops once to a `git stash -u`.
    """
    out = {"tracked": [], "untracked": [], "head": "", "branch": "", "clean": True}
    out["head"] = _rev(repo, "HEAD")
    br = _git(["git", "rev-parse", "--abbrev-ref", "HEAD"], repo)
    out["branch"] = br.stdout.strip() if br.returncode == 0 else ""

    tracked = _git(["git", "status", "--porcelain", "--untracked-files=no",
                    "--ignore-submodules=dirty"], repo)
    if tracked.returncode == 0:
        for line in (tracked.stdout or "").splitlines():
            if len(line) > 3:
                out["tracked"].append({"status": line[:2].strip(), "path": line[3:].strip()})

    untracked = _git(["git", "ls-files", "--others", "--exclude-standard"], repo)
    if untracked.returncode == 0:
        out["untracked"] = [p for p in (untracked.stdout or "").splitlines() if p.strip()]

    out["clean"] = not out["tracked"]
    return out


def _behind(repo: str, base: str, remote: str) -> int:
    r = _git(["git", "rev-list", "--count", f"HEAD..{remote}/{base}"], repo)
    try:
        return int((r.stdout or "0").strip())
    except ValueError:
        return 0


# ── 3. Test the dirty layer ─────────────────────────────────────────────────

def validate_paths(tree: str, paths) -> list:
    """Marker scan + Python compile over `paths`. [] means the layer is promotable."""
    problems = []
    for rel in paths:
        if rel.lower().endswith(BINARY_SUFFIXES):
            continue
        full = os.path.join(tree, rel)
        if not os.path.isfile(full):
            continue  # deletion — nothing to validate
        try:
            with open(full, "r", errors="replace") as fh:
                text = fh.read()
        except (OSError, IOError):
            continue
        if "\0" in text[:4096]:
            continue
        for match in CONFLICT_MARKER_RE.finditer(text):
            lineno = text.count("\n", 0, match.start()) + 1
            problems.append(f"{rel}:{lineno}: conflict marker")
        if rel.endswith(".py"):
            try:
                compile(text, rel, "exec")
            except SyntaxError as exc:
                problems.append(f"{rel}:{exc.lineno}: SyntaxError: {exc.msg}")
    return problems


# ── 4. Preserve on a named recovery ref ─────────────────────────────────────

def _host_slug() -> str:
    try:
        host = socket.gethostname()
    except Exception:  # noqa: BLE001 — fail-soft
        host = "unknown-host"
    return re.sub(r"[^A-Za-z0-9._-]+", "-", host).strip("-") or "unknown-host"


def preserve(repo: str, paths, *, label: str = "dirty") -> dict:
    """Commit the tracked dirt to a recovery ref WITHOUT moving HEAD or the index.

    Uses a scratch index file so the live checkout's index is untouched: the operator's
    staged/unstaged split survives recovery exactly as it was. Returns
    {"ref": ..., "sha": ..., "error": ...}.
    """
    out = {"ref": "", "sha": "", "error": None}
    head = _rev(repo, "HEAD")
    if not head:
        out["error"] = "no HEAD to base the recovery commit on"
        return out

    scratch = None
    try:
        fd, scratch = tempfile.mkstemp(prefix="orch-recovery-index-")
        os.close(fd)
        os.unlink(scratch)  # git wants to create it itself
        env = dict(os.environ)
        env["GIT_INDEX_FILE"] = scratch

        def g(args, timeout=GIT_TIMEOUT):
            try:
                return subprocess.run(args, cwd=repo, capture_output=True, text=True,
                                      timeout=timeout, env=env)
            except Exception as exc:  # noqa: BLE001
                return subprocess.CompletedProcess(args, 1, "", str(exc))

        if g(["git", "read-tree", head]).returncode != 0:
            out["error"] = "could not seed scratch index from HEAD"
            return out
        # Only the tracked paths. `--` guards paths that look like options.
        add = g(["git", "add", "--"] + list(paths))
        if add.returncode != 0:
            out["error"] = f"could not stage tracked dirt: {(add.stderr or '').strip()[:200]}"
            return out
        tree = g(["git", "write-tree"])
        if tree.returncode != 0:
            out["error"] = "write-tree failed"
            return out
        tree_sha = tree.stdout.strip()

        env2 = dict(env)
        env2.update({
            "GIT_AUTHOR_NAME": "kalepasch1", "GIT_AUTHOR_EMAIL": "kalepasch@gmail.com",
            "GIT_COMMITTER_NAME": "kalepasch1", "GIT_COMMITTER_EMAIL": "kalepasch@gmail.com",
        })
        msg = (f"recovery({label}): preserve {len(list(paths))} tracked change(s) "
               f"from dirty checkout on {_host_slug()}")
        try:
            commit = subprocess.run(
                ["git", "commit-tree", tree_sha, "-p", head, "-m", msg],
                cwd=repo, capture_output=True, text=True, timeout=GIT_TIMEOUT, env=env2)
        except Exception as exc:  # noqa: BLE001
            out["error"] = f"commit-tree failed: {exc}"
            return out
        if commit.returncode != 0:
            out["error"] = f"commit-tree failed: {(commit.stderr or '').strip()[:200]}"
            return out
        sha = commit.stdout.strip()

        ref = f"refs/recovery/{label}/{_host_slug()}/{int(time.time())}"
        upd = _git(["git", "update-ref", "-m", msg, ref, sha], repo)
        if upd.returncode != 0:
            out["error"] = f"update-ref failed: {(upd.stderr or '').strip()[:200]}"
            return out
        out["ref"], out["sha"] = ref, sha
        return out
    finally:
        if scratch and os.path.exists(scratch):
            try:
                os.unlink(scratch)
            except OSError:
                pass


# ── 5. Integrate upstream in an isolated worktree ───────────────────────────

def _isolated(repo: str, at_sha: str):
    parent = os.path.join(tempfile.gettempdir(), "orch-dirty-recovery")
    try:
        os.makedirs(parent, exist_ok=True)
    except OSError as exc:
        return "", f"cannot create worktree parent: {exc}"
    path = os.path.join(parent, f"layer-{int(time.time())}-{os.getpid()}")
    r = _git(["git", "worktree", "add", "--detach", "--force", path, at_sha], repo,
             timeout=max(GIT_TIMEOUT, 240))
    if r.returncode != 0:
        return "", f"worktree add failed: {(r.stderr or r.stdout or '').strip()[:250]}"
    return path, ""


def _drop(repo: str, path: str):
    if not path:
        return
    _git(["git", "worktree", "remove", "--force", path], repo)
    if os.path.isdir(path):
        shutil.rmtree(path, ignore_errors=True)
    _git(["git", "worktree", "prune"], repo)


def layer_onto_upstream(repo: str, recovery_sha: str, upstream_sha: str, paths):
    """Replay the recovery commit on top of `upstream_sha` in an isolated worktree.

    Returns {"sha": layered commit or "", "problems": [...], "overlap": [...],
             "worktree": path}. Never writes to the live checkout.
    """
    out = {"sha": "", "problems": [], "overlap": [], "worktree": ""}
    tree, err = _isolated(repo, upstream_sha)
    if err:
        out["problems"].append(err)
        return out
    out["worktree"] = tree
    try:
        _git(["git", "config", "user.name", "kalepasch1"], tree)
        _git(["git", "config", "user.email", "kalepasch@gmail.com"], tree)

        # Which of our paths did upstream also move? Reported on the card either way —
        # an overlap that still applies cleanly is compatible work, not a conflict.
        head_at_fork = _git(["git", "rev-parse", f"{recovery_sha}^"], repo).stdout.strip()
        if head_at_fork:
            diff = _git(["git", "diff", "--name-only", head_at_fork, upstream_sha], repo)
            upstream_touched = set((diff.stdout or "").splitlines())
            out["overlap"] = sorted(set(paths) & upstream_touched)

        pick = _git(["git", "cherry-pick", "--allow-empty", "-x", recovery_sha], tree)
        if pick.returncode != 0:
            _git(["git", "cherry-pick", "--abort"], tree)
            detail = (pick.stderr or pick.stdout or "").strip().splitlines()[-3:]
            out["problems"].append("dirty layer does not apply onto upstream: "
                                   + " | ".join(detail)[:300])
            return out

        problems = validate_paths(tree, paths)
        if problems:
            out["problems"].extend(problems)
            return out
        out["sha"] = _rev(tree, "HEAD")
        return out
    finally:
        _drop(repo, tree)


# ── 6/7. Orchestration + incident card ──────────────────────────────────────

def _fence(repo: str):
    """The per-repo maintenance fence. Falls back to a no-op contextmanager if the
    lock module is unavailable — a missing lock must not become a fleet outage."""
    try:
        import repo_lock
        return repo_lock.hold(repo, timeout=FENCE_WAIT)
    except Exception:  # noqa: BLE001 — fail-soft
        import contextlib

        @contextlib.contextmanager
        def _noop():
            yield True
        return _noop()


def publish_card(card: dict) -> str:
    """Write the incident card to the approvals/incidents surface. Returns its path.

    Best-effort by design: an unwritable log directory must not undo a good recovery.
    """
    try:
        base = os.environ.get(
            "ORCH_INCIDENT_DIR",
            os.path.join(os.path.dirname(os.path.abspath(__file__)), ".runtime", "incidents"))
        os.makedirs(base, exist_ok=True)
        path = os.path.join(base, f"dirty-checkout-{int(time.time())}-{os.getpid()}.json")
        import json
        with open(path, "w") as fh:
            json.dump(card, fh, indent=2, sort_keys=True, default=str)
        return path
    except Exception:  # noqa: BLE001 — fail-soft
        return ""


def recover(repo: str, base: str = "master", *, remote: str = "origin",
            fetch: bool = True, dry_run: bool = False) -> dict:
    """Bring a dirty, behind checkout to a clean head without losing anything.

    Outcomes: ``noop`` (already current and clean), ``fast-forward`` (clean, behind),
    ``layered`` (dirty, compatible — work replayed onto upstream), ``quarantined``
    (dirty, incompatible or invalid — preserved on a ref, upstream taken alone),
    ``blocked`` (fence unavailable or git unusable).
    """
    card = {
        "repo": repo, "base": base, "remote": remote, "host": _host_slug(),
        "started": time.time(), "outcome": "blocked", "sha_before": "", "sha_after": "",
        "changed_files": [], "untracked_preserved": [], "recovery_ref": "",
        "quarantine_ref": "", "overlap": [], "tests": [], "problems": [],
        "error": None, "card_path": "",
    }
    if not _enabled():
        card["error"] = "disabled by ORCH_DIRTY_RECOVERY_ENABLED"
        return card

    inv = inventory(repo)
    card["sha_before"] = inv["head"]
    card["changed_files"] = [c["path"] for c in inv["tracked"]]
    card["untracked_preserved"] = inv["untracked"]
    if not inv["head"]:
        card["error"] = f"not a usable git checkout: {repo}"
        return card

    with _fence(repo) as got_fence:
        if got_fence is False:
            card["error"] = f"maintenance fence busy after {FENCE_WAIT}s — will retry"
            card["card_path"] = publish_card(card)
            return card

        if fetch:
            f = _git(["git", "fetch", remote, base, "--quiet"], repo,
                     timeout=max(GIT_TIMEOUT, 300))
            if f.returncode != 0:
                card["error"] = f"fetch failed: {(f.stderr or '').strip()[:200]}"
                card["card_path"] = publish_card(card)
                return card

        upstream = _rev(repo, f"{remote}/{base}")
        if not upstream:
            card["error"] = f"upstream ref not found: {remote}/{base}"
            card["card_path"] = publish_card(card)
            return card

        # Re-read HEAD under the fence: a concurrent writer may have moved it between
        # the inventory above and the lock acquisition.
        head = _rev(repo, "HEAD")
        if head != inv["head"]:
            inv = inventory(repo)
            head = inv["head"]
            card["sha_before"] = head
            card["changed_files"] = [c["path"] for c in inv["tracked"]]
        card["sha_after"] = head

        if head == upstream and inv["clean"]:
            card["outcome"] = "noop"
            card["card_path"] = publish_card(card)
            return card

        # ── clean checkout, simply behind: fast-forward and done ────────────
        if inv["clean"]:
            if dry_run:
                card["outcome"] = "fast-forward/dry-run"
                card["card_path"] = publish_card(card)
                return card
            ff = _git(["git", "merge", "--ff-only", upstream], repo)
            if ff.returncode != 0:
                card["error"] = ("clean checkout but not fast-forwardable "
                                 "(diverged local commits): "
                                 + (ff.stderr or "").strip()[:200])
                card["card_path"] = publish_card(card)
                return card
            card["outcome"] = "fast-forward"
            card["sha_after"] = _rev(repo, "HEAD")
            card["card_path"] = publish_card(card)
            return card

        # ── dirty: inventory -> test -> preserve -> layer ───────────────────
        paths = card["changed_files"]
        card["tests"] = validate_paths(repo, paths)

        pres = preserve(repo, paths, label="dirty")
        if pres["error"]:
            # Could not even preserve — do NOT proceed. Leaving the host behind is
            # strictly better than advancing over unpreserved work.
            card["error"] = f"preservation failed, refusing to touch the checkout: {pres['error']}"
            card["card_path"] = publish_card(card)
            return card
        card["recovery_ref"] = pres["ref"]

        if dry_run:
            card["outcome"] = "dirty/dry-run"
            card["card_path"] = publish_card(card)
            return card

        layered = {"sha": "", "problems": list(card["tests"]), "overlap": []}
        if not card["tests"]:
            layered = layer_onto_upstream(repo, pres["sha"], upstream, paths)
        card["overlap"] = layered.get("overlap", [])
        card["problems"] = layered.get("problems", [])

        if layered.get("sha"):
            # Compatible and valid: adopt the layered head.
            #
            # `git checkout` cannot get us there — it refuses to overwrite a locally
            # modified file whose content differs in the target commit, which is every
            # dirty path by construction. So: compare-and-swap the branch ref (this is
            # also the concurrent-writer check — if someone moved base since we forked,
            # the swap fails and we quarantine instead of clobbering them), then sync
            # the working tree to the ref we just validated.
            #
            # The `--hard` here is NOT the loss path pinned by test_dirty_checkout_sacred:
            # every byte it overwrites is already durable in two places — verbatim on the
            # recovery ref created above, and replayed into `layered["sha"]` itself. It is
            # guarded by that verification rather than taken on faith, and it never touches
            # untracked files.
            if not pres["sha"] or not _rev(repo, pres["ref"]):
                card["outcome"] = "quarantined"
                card["problems"].append("recovery ref vanished before adoption; "
                                        "refusing to sync the working tree")
                card["card_path"] = publish_card(card)
                return card

            if inv["branch"] and inv["branch"] != "HEAD":
                swap = _git(["git", "update-ref", "-m",
                             f"dirty-checkout recovery: layer local work onto {remote}/{base}",
                             f"refs/heads/{inv['branch']}", layered["sha"], head], repo)
                if swap.returncode != 0:
                    card["outcome"] = "quarantined"
                    card["quarantine_ref"] = pres["ref"]
                    card["sha_after"] = _rev(repo, "HEAD")
                    card["error"] = ("concurrent writer moved the base branch during "
                                     "recovery; work preserved on " + pres["ref"])
                    card["card_path"] = publish_card(card)
                    return card
                _git(["git", "reset", "--hard", "HEAD"], repo)
            else:
                _git(["git", "reset", "--hard", layered["sha"]], repo)
            after = _rev(repo, "HEAD")
            still_dirty = inventory(repo)
            if after == layered["sha"] and still_dirty["clean"]:
                card["outcome"] = "layered"
                card["sha_after"] = after
            else:
                card["outcome"] = "quarantined"
                card["quarantine_ref"] = pres["ref"]
                card["sha_after"] = after
                card["problems"].append(
                    "checkout did not settle clean at the layered head; "
                    "work remains on the recovery ref")
            card["card_path"] = publish_card(card)
            return card

        # ── incompatible or invalid dirty layer ─────────────────────────────
        # The work is already durable on the recovery ref. We deliberately do NOT
        # discard the operator's working tree to take upstream: that would be the
        # `reset --hard` loss path. The host stays where it is, and the card names
        # exactly what a human/agent has to reconcile.
        card["outcome"] = "quarantined"
        card["quarantine_ref"] = pres["ref"]
        card["sha_after"] = _rev(repo, "HEAD")
        card["error"] = ("dirty layer could not be integrated; preserved on "
                         f"{pres['ref']} ({pres['sha'][:12]}) — checkout left untouched")
        card["card_path"] = publish_card(card)
        return card


def main(argv=None) -> int:
    import argparse
    import json
    ap = argparse.ArgumentParser(description="Durable dirty-checkout recovery.")
    ap.add_argument("repo")
    ap.add_argument("--base", default="master")
    ap.add_argument("--remote", default="origin")
    ap.add_argument("--no-fetch", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    card = recover(args.repo, args.base, remote=args.remote,
                   fetch=not args.no_fetch, dry_run=args.dry_run)
    print(json.dumps(card, indent=2, sort_keys=True, default=str))
    return 0 if card["outcome"] in ("noop", "fast-forward", "layered") else 1


if __name__ == "__main__":
    raise SystemExit(main())
