#!/usr/bin/env python3
"""DB-independent deployment sweep (2026-07-09). Supabase is down; deployments must not be.

For each fleet repo: fetch origin, find origin/agent/* branches with commits not in the base
branch, and for each candidate (newest-first, capped): rebase it onto base in an ISOLATED
worktree, run the repo's test/build gate there, fast-forward base, push with one non-ff
reconcile retry. Every action is journaled to .runtime/git_deploy_sweep.jsonl so task rows can
be reconciled when the DB returns. Idempotent: already-merged branches are skipped; the merge
train redoing one of these later is a no-op.

Usage: python3 scripts/git_deploy_sweep.py [repo_name ...]   (default: all)
"""
import json, os, subprocess, sys, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
JOURNAL = os.path.join(ROOT, ".runtime", "git_deploy_sweep.jsonl")
HOME = os.path.expanduser("~")

REPOS = {  # name -> (path, base, gate_cmd or None=detect)
    "beethoven":  (os.path.join(HOME, "Documents/beethoven/claude-orchestrator"), "master",
                   "python3 -m pytest runner/tests/test_merge_train.py runner/tests/test_branch_share.py -q"),
    "smarter":    (os.path.join(HOME, "Documents/smarter"), "main", "npm test"),
    "tomorrow":   (os.path.join(HOME, "Documents/tomorrow/tomorrow"), "main",
                   "npx vitest run --config vitest.pure.config.ts"),
    "apparently": (os.path.join(HOME, "Documents/apparently"), "main", "npm test"),
    "pareto-2080": (os.path.join(HOME, "Documents/pareto/2080"), "main", "npm test"),
    "santas-secret-workshop": (os.path.join(HOME, "Documents/hisanta"), "master", "npm test"),
    "racefeed":   (os.path.join(HOME, "Documents/galop/racefeed"), "main", "npm test"),
}
PER_REPO_CAP = int(os.environ.get("SWEEP_PER_REPO_CAP", "10"))
GATE_TIMEOUT = int(os.environ.get("SWEEP_GATE_TIMEOUT", "1500"))
KNOWN_FLAKY = {"pareto-2080": 2}  # allowed pre-existing failures (local Prisma-binary mismatch)


def log(repo, branch, action, detail=""):
    row = {"at": datetime.datetime.utcnow().isoformat() + "Z", "repo": repo,
           "branch": branch, "action": action, "detail": str(detail)[:300]}
    os.makedirs(os.path.dirname(JOURNAL), exist_ok=True)
    with open(JOURNAL, "a") as f:
        f.write(json.dumps(row) + "\n")
    print(f"[{repo}] {branch}: {action} {str(detail)[:120]}", flush=True)


def git(cwd, *args, timeout=120):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=timeout)


def gate(cwd, cmd, allowed_failures=0):
    try:
        r = subprocess.run(["bash", "-lc", cmd], cwd=cwd, capture_output=True, text=True, timeout=GATE_TIMEOUT)
    except subprocess.TimeoutExpired:
        return False, "gate timeout"
    if r.returncode == 0:
        return True, "green"
    tail = ((r.stdout or "") + (r.stderr or ""))[-400:]
    if allowed_failures:
        import re
        m = re.search(r"(\d+) fail", tail)
        if m and int(m.group(1)) <= allowed_failures and "passing" in tail:
            return True, f"green-with-{m.group(1)}-known-flaky"
    return False, tail


def candidates(repo_path, base):
    git(repo_path, "fetch", "origin", "--prune",
        f"+refs/heads/agent/*:refs/remotes/origin/agent/*", timeout=180)
    git(repo_path, "fetch", "origin", base, timeout=120)
    out = git(repo_path, "for-each-ref", "--sort=-committerdate",
              "--format=%(refname:short)", "refs/remotes/origin/agent/").stdout
    res = []
    for ref in out.splitlines():
        ref = ref.strip()
        if not ref:
            continue
        ahead = git(repo_path, "rev-list", "--count", f"origin/{base}..{ref}").stdout.strip()
        if ahead and ahead != "0":
            res.append(ref)
    return res


def integrate(name, repo, base, gate_cmd, ref):
    short = ref.replace("refs/remotes/", "").replace("origin/", "")
    wt = os.path.join(os.path.dirname(repo), os.path.basename(repo) + "-wt", "sweep")
    git(repo, "worktree", "remove", "--force", wt)
    os.makedirs(os.path.dirname(wt), exist_ok=True)
    if git(repo, "worktree", "add", "--detach", "-f", wt, ref).returncode != 0:
        log(name, short, "SKIP", "worktree add failed"); return False
    try:
        if git(wt, "rebase", f"origin/{base}", timeout=300).returncode != 0:
            git(wt, "rebase", "--abort")
            log(name, short, "CONFLICT", "rebase onto base failed"); return False
        ok, tail = gate(wt, gate_cmd, KNOWN_FLAKY.get(name, 0))
        if not ok:
            log(name, short, "GATE-RED", tail); return False
        sha = git(wt, "rev-parse", "HEAD").stdout.strip()
        push = git(repo, "push", "origin", f"{sha}:refs/heads/{base}", timeout=300)
        if push.returncode != 0 and ("non-fast-forward" in (push.stderr or "") or "fetch first" in (push.stderr or "")):
            git(repo, "fetch", "origin", base, timeout=120)
            if git(wt, "rebase", f"origin/{base}", timeout=300).returncode == 0:
                ok2, tail2 = gate(wt, gate_cmd, KNOWN_FLAKY.get(name, 0))
                if ok2:
                    sha = git(wt, "rev-parse", "HEAD").stdout.strip()
                    push = git(repo, "push", "origin", f"{sha}:refs/heads/{base}", timeout=300)
        if push.returncode != 0:
            log(name, short, "PUSH-FAIL", (push.stderr or "")[-150:]); return False
        git(repo, "fetch", "origin", base, timeout=120)  # update local view
        log(name, short, "DEPLOYED", f"{base} -> {sha[:9]} (gate {tail})")
        return True
    finally:
        git(repo, "worktree", "remove", "--force", wt)


def main():
    names = sys.argv[1:] or list(REPOS)
    total = 0
    for name in names:
        repo, base, gate_cmd = REPOS[name]
        if not os.path.isdir(repo):
            log(name, "-", "SKIP-REPO", "path missing"); continue
        refs = candidates(repo, base)[:PER_REPO_CAP]
        log(name, "-", "SCAN", f"{len(refs)} candidate branches")
        for ref in refs:
            if integrate(name, repo, base, gate_cmd, ref):
                total += 1
    log("-", "-", "DONE", f"{total} branches deployed to base")


if __name__ == "__main__":
    main()
