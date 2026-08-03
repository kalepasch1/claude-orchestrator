#!/usr/bin/env python3
"""
vercel_config_guard.py - deploy-config coherence checker. Catches the class of outage a local
`npm run build` CANNOT catch, because the bug is in the *contract between vercel.json and the
committed git tree*, not in the code:

  * installCommand runs `npm ci` but no lockfile is COMMITTED (only present on the dev machine)
    -> Vercel install step dies. (broke `vigil`)
  * buildCommand runs a script path that `.vercelignore` strips from the upload context
    -> "Cannot find module scripts/release-gate.mjs" on Vercel, green locally. (broke `vigil`)
  * outputDirectory is declared but the whole build chain emits nothing (`node --check foo.js`)
    -> "No Output Directory named 'public' found". (broke `apparently-law`)
  * vercel.json references a package.json script that does not exist -> "Missing script".

Two entry points:
  gate(project, branch) -> (ok, log)   fail-closed; the merge/release path calls this.
  run()                               advisory sweep across every project; files remediation
                                      tasks for real violations (never just prints).
Structured JSONL goes to .runtime/logs/vercel-config-guard.log.
"""
import json
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import guard_tasks

NAME = "vercel-config-guard"
ENABLED = os.environ.get("ORCH_VERCEL_CONFIG_GUARD_ENABLED", "true").lower() in ("1", "true", "yes", "on")
BREAK_GLASS = os.environ.get("ORCH_VERCEL_CONFIG_GUARD_BREAK_GLASS", "false").lower() in ("1", "true", "yes", "on")
FILE_TASKS = os.environ.get("ORCH_VERCEL_CONFIG_GUARD_FILE_TASKS", "true").lower() in ("1", "true", "yes", "on")
MAX_TASKS_PER_RUN = int(os.environ.get("ORCH_VERCEL_CONFIG_MAX_TASKS_PER_RUN", "10"))

# severity "block" -> gate() refuses the merge. "warn" -> reported + remediated, never blocks.
BLOCKING = {"lockfile_not_committed", "build_input_vercelignored",
            "build_input_not_committed", "missing_package_script",
            "output_dir_never_built",
            # 2026-08-02: silent deploy skips. illuminati's ignoreCommand tested
            # $VERCEL_GIT_COMMIT_REF != "main" on a repo whose default branch is `master`,
            # so on every production push the test was TRUE -> exit 0 -> Vercel SKIPPED the
            # build. Exit 0 is "success" to every dashboard, so a full day of production
            # deploys silently never happened and NOTHING alerted. A config that disables
            # the default branch is now a hard block.
            "ignore_command_skips_default_branch",
            "deployment_disabled_for_default_branch"}

_LOCK_REQUIREMENTS = (
    (re.compile(r"\bnpm\s+ci\b"), ("package-lock.json", "npm-shrinkwrap.json")),
    (re.compile(r"\bpnpm\s+(?:install|i)\b[^&|;]*--frozen-lockfile"), ("pnpm-lock.yaml",)),
    (re.compile(r"\byarn\s+install\b[^&|;]*(?:--frozen-lockfile|--immutable)"), ("yarn.lock",)),
)

# A leaf command that provably writes no build output. If EVERY leaf is one of these and an
# outputDirectory is declared, the deploy cannot possibly succeed.
_NON_EMITTING = (
    re.compile(r"\bnode\s+--check\b"),
    re.compile(r"\bnode\s+--test\b"),
    re.compile(r"\b(?:tsc|vue-tsc)\b[^&|;]*--noEmit\b"),
    re.compile(r"\bnuxi\s+typecheck\b"),
    re.compile(r"^\s*(?:npx\s+)?(?:eslint|prettier|biome|stylelint|oxlint)\b"),
    re.compile(r"^\s*(?:npx\s+)?(?:jest|vitest|mocha|ava|tap)\b"),
    re.compile(r"^\s*(?:npx\s+)?playwright\s+test\b"),
    re.compile(r"^\s*echo\b"),
    re.compile(r"^\s*(?:true|:)\s*$"),
)

_SCRIPT_CALL = re.compile(
    r"^\s*(npm|pnpm|yarn|bun)\s+(run\s+)?([A-Za-z0-9:._-]+)(?:\s|$)")
# `npm rebuild @prisma/engines` is a package-manager builtin, NOT `npm run rebuild`. Treating
# builtins as script names produced a false "missing script" on pareto-2080; keep this list.
_PM_BUILTINS = {
    "run", "run-script", "exec", "dlx", "install", "i", "ci", "add", "remove", "rm", "up",
    "update", "upgrade", "uninstall", "link", "unlink", "rebuild", "prune", "dedupe", "audit",
    "outdated", "publish", "pack", "version", "view", "info", "config", "cache", "init",
    "create", "login", "logout", "whoami", "ls", "list", "why", "x", "set", "get", "store",
    "fetch", "import", "workspace", "workspaces", "--",
}
# For npm/bun a bare subcommand only runs a package script for these lifecycle aliases.
_BARE_SCRIPT_OK = {"test", "start", "stop", "restart"}
_PATH_TOKEN = re.compile(
    r"(?<![\w./-])(?:\./)?((?:[\w.@-]+/)+[\w.@-]+\.(?:mjs|cjs|js|jsx|ts|tsx|sh|py|toml))(?![\w])")
_SPLIT = re.compile(r"&&|\|\||;|\|")


def _home():
    return os.environ.get("CLAUDE_ORCH_HOME",
                          os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".runtime"))


def _log_event(event):
    """Append one structured JSONL record to .runtime/logs/<name>.log (fail-soft)."""
    row = dict(event)
    row.setdefault("at", time.time())
    row.setdefault("bot", NAME)
    try:
        path = os.path.join(_home(), "logs")
        os.makedirs(path, exist_ok=True)
        with open(os.path.join(path, NAME + ".log"), "a") as f:
            f.write(json.dumps(row, separators=(",", ":"), default=str) + "\n")
    except OSError:
        pass  # logging must never break the check
    return row


def _git(repo, *args, **kw):
    """Run git; return (rc, stdout, stderr). Fail-soft."""
    try:
        r = subprocess.run(["git"] + list(args), cwd=repo, capture_output=True,
                           text=True, timeout=kw.get("timeout", 30))
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except (OSError, subprocess.SubprocessError) as e:
        return -1, "", str(e)


def _package_roots(repo):
    """Every directory holding a vercel.json (deploy roots), falling back to the repo root."""
    roots = []
    try:
        import dependency_prewarm
        roots = list(dependency_prewarm.package_roots(repo) or [])
    except (ImportError, AttributeError, TypeError):
        roots = []
    if repo not in roots:
        roots.insert(0, repo)
    return [r for r in roots if os.path.isfile(os.path.join(r, "vercel.json"))]


def _load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f) or {}
    except (OSError, ValueError):
        return {}


class BranchMissing(Exception):
    """The configured branch does not exist in this repo."""


def _resolve_branch(repo, branch, strict=False):
    """Pick a ref that actually exists: caller's branch, else HEAD.

    <strict> refuses the HEAD fallback. illuminati carried prod_branch='main' in the DB while
    the repo's default is master and origin/main does not exist, so this quietly returned HEAD —
    whatever branch happened to be checked out, in that case an agent branch — and the guard
    reported a clean production result for a ref nobody configured. Silent degradation is the
    exact bug class these guards exist to remove, so the periodic sweep now passes strict=True
    and reports a MISCONFIGURED project instead of inventing a ref.
    """
    if branch:
        rc, _, _ = _git(repo, "rev-parse", "--verify", "--quiet", branch + "^{commit}")
        if rc == 0:
            return branch
        if strict:
            raise BranchMissing(branch)
    elif strict:
        raise BranchMissing("<unset>")
    return "HEAD"


def _committed(repo, ref, rel):
    """True when <rel> exists in the COMMITTED tree (not merely on disk)."""
    rc, out, _ = _git(repo, "ls-tree", "-r", "--name-only", ref, "--", rel)
    return rc == 0 and bool(out.strip())


def _vercelignored(root, rel_paths):
    """Tracked files under <root> that .vercelignore strips from the Vercel upload context."""
    ignore = os.path.join(root, ".vercelignore")
    if not os.path.isfile(ignore) or not rel_paths:
        return set()
    rc, out, _ = _git(root, "ls-files", "-ci", "--exclude-from", ignore)
    if rc != 0:
        return set()
    return set(out.splitlines()) & set(rel_paths)


def resolve_chain(scripts, command, _seen=None, _depth=0):
    """Expand `npm run X` chains into leaf shell commands.

    Returns (leaves, missing_scripts). Cycles and runaway depth terminate safely.
    """
    leaves, missing = [], []
    if not command or _depth > 8:
        return leaves, missing
    seen = set(_seen or ())
    for raw in _SPLIT.split(str(command)):
        seg = raw.strip()
        if not seg:
            continue
        m = _SCRIPT_CALL.match(seg)
        name = None
        if m:
            manager, explicit_run, candidate = m.group(1), bool(m.group(2)), m.group(3)
            if candidate in _PM_BUILTINS:
                name = None
            elif explicit_run:
                name = candidate
            elif manager in ("yarn", "pnpm") or candidate in _BARE_SCRIPT_OK:
                name = candidate
        if name is None:
            leaves.append(seg)
            continue
        if name not in scripts:
            missing.append(name)
            leaves.append(seg)
            continue
        if name in seen:
            continue
        seen.add(name)
        sub_leaves, sub_missing = resolve_chain(scripts, scripts[name], seen, _depth + 1)
        leaves.extend(sub_leaves)
        missing.extend(sub_missing)
    return leaves, missing


def emits_output(leaves):
    """True if any leaf command can plausibly write build output."""
    for leaf in leaves:
        if not any(p.search(leaf) for p in _NON_EMITTING):
            return True
    return False


def _violation(code, root_rel, detail, fix):
    return {"code": code, "severity": "block" if code in BLOCKING else "warn",
            "package_root": root_rel, "detail": detail, "fix": fix}


# --------------------------------------------------------------------------------------
# silent deploy skips + configs that match nothing (2026-08-02)
# --------------------------------------------------------------------------------------

def minimatch_regex(pattern):
    """Compile a glob to a regex with MINIMATCH semantics, which Vercel uses.

    The distinction that caused the outage: in minimatch `*` does NOT cross a `/`, so a
    `git.deploymentEnabled` rule of `{"*": false}` matches `main` but NOT `agent/foo`.
    The author believed they had disabled every branch; the rule silently matched nothing
    they cared about. `**` is the only token that crosses separators.
    """
    out, i = ["^"], 0
    while i < len(pattern):
        ch = pattern[i]
        if ch == "*":
            if pattern[i:i + 2] == "**":
                out.append(".*")
                i += 2
                if i < len(pattern) and pattern[i] == "/":
                    i += 1
                continue
            out.append("[^/]*")
        elif ch == "?":
            out.append("[^/]")
        elif ch in ".^$+(){}[]|\\":
            out.append("\\" + ch)
        else:
            out.append(ch)
        i += 1
    out.append("$")
    return re.compile("".join(out))


def glob_matches(pattern, name):
    """True when a minimatch pattern matches a branch name."""
    try:
        return bool(minimatch_regex(pattern).match(name))
    except re.error:
        return False


def _default_branch(repo, fallback=None):
    """The repo's real default branch: origin/HEAD, else the local HEAD, else fallback."""
    rc, out, _ = _git(repo, "symbolic-ref", "--quiet", "refs/remotes/origin/HEAD")
    if rc == 0 and out.strip():
        return out.strip().rsplit("/", 1)[-1]
    rc, out, _ = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    if rc == 0 and out.strip() and out.strip() != "HEAD":
        return out.strip()
    return fallback


def _branch_names(repo):
    """Every local + remote branch name, for 'does this rule match anything real'."""
    names = set()
    rc, out, _ = _git(repo, "for-each-ref", "--format=%(refname:short)",
                      "refs/heads", "refs/remotes")
    if rc == 0:
        for line in out.splitlines():
            n = line.strip()
            if not n or n.endswith("/HEAD"):
                continue
            names.add(n[len("origin/"):] if n.startswith("origin/") else n)
    return names


# Branch literals inside an ignoreCommand. Covers the shapes Vercel docs recommend:
#   bash -c '[ "$VERCEL_GIT_COMMIT_REF" != "main" ]'
#   if [ "$VERCEL_GIT_COMMIT_REF" == "production" ]; then exit 1; else exit 0; fi
#   npx vercel-deploy-check --branch main
# The optional quote AFTER the variable is load-bearing: the shape Vercel's own docs use is
# [ "$VERCEL_GIT_COMMIT_REF" != "main" ], where a closing double-quote sits between the
# variable and the operator. Omitting it made this detector silently match nothing.
_REF_VAR = r"\$\{?VERCEL_GIT_COMMIT_REF\}?"
_Q = r"[\"']?"
_REF_CMP = re.compile(
    r"(?:%s%s\s*(==|!=|=~|=)\s*%s([\w./*-]+)%s)"
    r"|(?:%s([\w./*-]+)%s\s*(==|!=|=~|=)\s*%s%s)"
    % (_REF_VAR, _Q, _Q, _Q, _Q, _Q, _Q, _REF_VAR))


def check_deploy_skip(repo, root, cfg, default_branch):
    """ignoreCommand / git.deploymentEnabled configs that silently skip the DEFAULT branch.

    Vercel semantics, and the reason this was invisible: ignoreCommand exit 0 means SKIP
    the build, exit 1 means BUILD. A skipped build is reported as a SUCCESS. There is no
    failed deployment, no red check, no alert -- production simply stops updating.
    """
    out = []
    rel_root = os.path.relpath(root, repo)
    if not default_branch:
        return out

    # -- 1. ignoreCommand that evaluates "skip" on the default branch.
    ignore = str(cfg.get("ignoreCommand") or "").strip()
    if ignore:
        refs = set()
        negated = False
        for m in _REF_CMP.finditer(ignore):
            op = m.group(1) or m.group(4)
            val = m.group(2) or m.group(3)
            if val:
                refs.add(val)
            if op == "!=":
                negated = True
        if refs and not any(r == default_branch or glob_matches(r, default_branch)
                            for r in refs):
            out.append(_violation(
                "ignore_command_skips_default_branch", rel_root,
                "vercel.json ignoreCommand `%s` branches on VERCEL_GIT_COMMIT_REF against %s, "
                "but this repository's DEFAULT branch is '%s', which is not among them. On "
                "every push to '%s' the%s comparison makes the command exit 0, and exit 0 means "
                "SKIP THE BUILD. Vercel records a skipped build as a SUCCESS, so production "
                "stops updating with no failed deploy, no red check and no alert -- exactly how "
                "illuminati skipped every production build for a day."
                % (ignore[:200], " or ".join(sorted("'%s'" % r for r in refs)),
                   default_branch, default_branch, " negated" if negated else ""),
                "Change the ignoreCommand to reference '%s' (the real default branch), or "
                "delete it. Verify with: VERCEL_GIT_COMMIT_REF=%s sh -c %r ; echo $?  — it "
                "MUST print 1 (build) for the default branch."
                % (default_branch, default_branch, ignore[:120])))

    # -- 2. git.deploymentEnabled disabling the default branch.
    # A blanket `deploymentEnabled: false`, or a map in which NOTHING is enabled, is a
    # deliberate "this repository does not deploy" -- the orchestrator's own repo says
    # exactly that. Blocking it would quarantine every merge on a correctly-configured
    # project, so it is advisory. The BLOCKING case is the INCONSISTENT one: some branches
    # are explicitly enabled while the default branch is disabled, which is never intended
    # and is the shape that silently stops production.
    git_cfg = cfg.get("git") or {}
    enabled_cfg = git_cfg.get("deploymentEnabled")
    if isinstance(enabled_cfg, bool) and enabled_cfg is False:
        out.append(_violation(
            "deployment_disabled_everywhere", rel_root,
            "vercel.json git.deploymentEnabled is `false` for ALL branches, so no push to "
            "'%s' ever deploys. Advisory: for a repo that deliberately does not deploy this "
            "is correct, and deploy_silence_detector honours it. Confirm it is intended."
            % default_branch,
            "If this project SHOULD deploy, set git.deploymentEnabled to true for '%s'."
            % default_branch))
    elif isinstance(enabled_cfg, dict):
        # PRECEDENCE MATTERS. `{"*": false, "master": true}` is a correct, common config:
        # the exact branch key overrides the catch-all glob, so master DOES deploy. Reading
        # only the `false` rules called that an outage and produced a BLOCKING false
        # positive on this repo's own web/vercel.json -- a guard that would have quarantined
        # every merge on a correctly configured project.
        matching = [(pat, val) for pat, val in enabled_cfg.items()
                    if pat == default_branch or glob_matches(pat, default_branch)]
        if matching and not any(val is True for _, val in matching):
            patterns = ", ".join("'%s'" % p for p, _ in matching)
            if not any(v is True for v in enabled_cfg.values()):
                out.append(_violation(
                    "deployment_disabled_everywhere", rel_root,
                    "vercel.json git.deploymentEnabled disables %s (matching the default "
                    "branch '%s') and enables nothing, so this project never deploys. "
                    "Advisory: consistent with a repo that deliberately does not deploy."
                    % (patterns, default_branch),
                    "If this project SHOULD deploy, add `\"%s\": true`." % default_branch))
            else:
                out.append(_violation(
                    "deployment_disabled_for_default_branch", rel_root,
                    "vercel.json git.deploymentEnabled matches the DEFAULT branch '%s' only "
                    "with rules that are false (%s), while OTHER branches are explicitly "
                    "enabled. Production pushes are silently not deployed and Vercel shows "
                    "no failure, but this project clearly is meant to deploy."
                    % (default_branch, patterns),
                    "Add an explicit `\"%s\": true` entry — an exact branch key overrides a "
                    "catch-all glob." % default_branch))
    return out


def check_config_noop(repo, root, cfg):
    """Config rules the author believes are active but which match NOTHING real.

    The incident: `git.deploymentEnabled: {"*": false}` was written to stop agent branches
    from deploying. Under minimatch `*` does not cross `/`, so it never matched `agent/foo`
    -- and because a rule that matches nothing produces no output of any kind, the author
    had no way to learn it was inert. Advisory rather than blocking: a rule for a branch
    that simply does not exist YET is legitimate and common.
    """
    out = []
    rel_root = os.path.relpath(root, repo)
    git_cfg = cfg.get("git") or {}
    enabled_cfg = git_cfg.get("deploymentEnabled")
    if not isinstance(enabled_cfg, dict) or not enabled_cfg:
        return out
    branches = _branch_names(repo)
    if not branches:
        return out
    for pattern in enabled_cfg:
        matched = sorted(b for b in branches if glob_matches(pattern, b))
        if matched:
            continue
        # Is it inert only because of the `*`-doesn't-cross-`/` rule? Say so explicitly.
        loose = sorted(b for b in branches
                       if re.match("^" + re.escape(pattern).replace(r"\*", ".*") + "$", b))
        hint = ""
        if loose:
            hint = (" It WOULD match %d branch(es) (%s) if `*` crossed `/`, but under "
                    "minimatch `*` stops at a path separator — use `**` to cross it. This is "
                    "the exact bug that let agent/* branches keep deploying."
                    % (len(loose), ", ".join(loose[:5])))
        out.append(_violation(
            "config_rule_matches_nothing", rel_root,
            "vercel.json git.deploymentEnabled has a rule for '%s' which matches NONE of the "
            "%d branches that exist in this repo. The rule is inert: it produces no effect "
            "and no output, so it looks configured while doing nothing.%s"
            % (pattern, len(branches), hint),
            "Either correct the pattern (e.g. '%s' -> '%s**') or delete the rule so the "
            "config states what is actually enforced."
            % (pattern, pattern.rstrip("*"))))
    return out


def check_root(repo, root, ref):
    """Validate one vercel.json deploy root against the committed tree."""
    out = []
    rel_root = os.path.relpath(root, repo)
    cfg = _load_json(os.path.join(root, "vercel.json"))
    scripts = (_load_json(os.path.join(root, "package.json")).get("scripts") or {})
    prefix = "" if rel_root == "." else rel_root.rstrip("/") + "/"

    install = str(cfg.get("installCommand") or "")
    build = str(cfg.get("buildCommand") or "")
    dev = str(cfg.get("devCommand") or "")

    # 0. Silent deploy skips + inert config rules. These run FIRST because they are the only
    # failures in this module that produce no error signal anywhere: a skipped build is a
    # green build, and a config rule matching nothing emits nothing at all.
    out.extend(check_deploy_skip(repo, root, cfg, _default_branch(repo)))
    out.extend(check_config_noop(repo, root, cfg))

    # 1. `npm ci` (and friends) demand a lockfile that is actually COMMITTED.
    for pattern, lockfiles in _LOCK_REQUIREMENTS:
        if not pattern.search(install):
            continue
        if any(_committed(repo, ref, prefix + lf) for lf in lockfiles):
            continue
        on_disk = [lf for lf in lockfiles if os.path.isfile(os.path.join(root, lf))]
        out.append(_violation(
            "lockfile_not_committed", rel_root,
            "installCommand `%s` needs a committed %s in %s; none is in the tree at %s%s"
            % (install.strip(), " or ".join(lockfiles), rel_root or ".", ref,
               " (it exists on disk but was never committed: " + ", ".join(on_disk) + ")" if on_disk else ""),
            "git add %s%s && commit it, or change installCommand to `npm install`."
            % (prefix, lockfiles[0])))

    # 2/4. Resolve every command vercel.json runs down to leaf shell commands.
    leaves, build_leaves, missing = [], [], []
    for label, command in (("buildCommand", build), ("installCommand", install), ("devCommand", dev)):
        if not command:
            continue
        sub_leaves, sub_missing = resolve_chain(scripts, command)
        if label == "buildCommand":
            build_leaves.extend(sub_leaves)
        if label != "devCommand":
            leaves.extend(sub_leaves)
        for name in sub_missing:
            if name not in missing:
                missing.append(name)
                out.append(_violation(
                    "missing_package_script", rel_root,
                    "vercel.json %s runs `npm run %s`, which does not exist in %spackage.json scripts"
                    % (label, name, prefix),
                    "Add a `%s` script to %spackage.json or fix the %s." % (name, prefix, label)))

    # 2. Script paths the build depends on must survive .vercelignore AND be committed.
    referenced = []
    for leaf in leaves:
        for match in _PATH_TOKEN.finditer(leaf):
            candidate = match.group(1)
            if candidate not in referenced and os.path.isfile(os.path.join(root, candidate)):
                referenced.append(candidate)
    for candidate in referenced:
        if not _committed(repo, ref, prefix + candidate):
            out.append(_violation(
                "build_input_not_committed", rel_root,
                "buildCommand runs `%s`, which exists on this machine but is NOT in the committed tree at %s"
                % (candidate, ref),
                "git add %s%s — Vercel only ever sees committed files." % (prefix, candidate)))
    for candidate in sorted(_vercelignored(root, referenced)):
        out.append(_violation(
            "build_input_vercelignored", rel_root,
            "buildCommand runs `%s`, but %s.vercelignore strips it from the Vercel upload context"
            % (candidate, prefix),
            "Re-include it in %s.vercelignore after the excluding rule — a bare `!%s` is NOT enough "
            "when its parent directory is excluded; you also need `!%s/` for each parent."
            % (prefix, candidate, candidate.split("/")[0])))

    # 3. A declared outputDirectory needs something that actually produces it.
    outdir = str(cfg.get("outputDirectory") or "").strip().strip("/")
    framework = cfg.get("framework")
    if outdir and not framework and build_leaves and not emits_output(build_leaves):
        if not _committed(repo, ref, prefix + outdir):
            out.append(_violation(
                "output_dir_never_built", rel_root,
                "outputDirectory '%s' is declared with framework=null, but the whole build chain "
                "emits nothing (%s) and '%s' is not committed — the deploy will fail with "
                "\"No Output Directory named '%s' found\""
                % (outdir, " ; ".join(leaves)[:200], outdir, outdir),
                "Make the build write %s (e.g. `node scripts/build.mjs`), commit %s, or set a framework preset."
                % (outdir, outdir)))
    return out


def check_repo(repo, branch=None, project=None, strict=False):
    """Validate every vercel.json in a repo. Returns a result dict; never raises."""
    result = {"project": project, "repo": repo, "branch": branch,
              "ref": None, "roots": 0, "violations": [], "ok": True, "skipped": None}
    if not ENABLED:
        result["skipped"] = "disabled"
        return result
    if not repo or not os.path.isdir(repo):
        result["skipped"] = "repo not on this machine"
        return result
    try:
        ref = _resolve_branch(repo, branch, strict=strict)
    except BranchMissing as exc:
        result["ok"] = False
        result["branch_missing"] = str(exc)
        result["skipped"] = ("configured branch %r does not exist in this repo — refusing to fall "
                             "back to HEAD" % str(exc))
        return result
    result["ref"] = ref
    roots = _package_roots(repo)
    result["roots"] = len(roots)
    if not roots:
        result["skipped"] = "no vercel.json"
        return result
    for root in roots:
        try:
            for v in check_root(repo, root, ref):
                v["project"] = project
                v["repo"] = repo
                result["violations"].append(v)
        except (OSError, ValueError, TypeError) as e:
            result["violations"].append(_violation(
                "guard_error", os.path.relpath(root, repo),
                "vercel_config_guard could not evaluate this root: %s" % e,
                "Inspect vercel.json / package.json for malformed JSON."))
    result["ok"] = not any(v["severity"] == "block" for v in result["violations"])
    return result


def gate(project_name, branch=None):
    """Merge-path gate. FAIL-CLOSED: any blocking config violation stops the merge.

    Returns (ok, log) to match build_gate.check()'s contract.
    """
    if not ENABLED:
        return True, "vercel_config_guard disabled"
    rows = db.select("projects", {"select": "*", "name": "eq.%s" % project_name}) or [{}]
    p = rows[0]
    repo = p.get("repo_path") or ""
    if not repo or not os.path.isdir(repo):
        return True, "repo not on this machine (skipped)"
    ref = branch or p.get("prod_branch") or p.get("default_base")
    result = check_repo(repo, ref, project_name)
    _log_event({"event": "gate", "project": project_name, "branch": ref,
                "ok": result["ok"], "violations": len(result["violations"])})
    if result.get("skipped"):
        return True, "vercel_config_guard: %s" % result["skipped"]
    blocking = [v for v in result["violations"] if v["severity"] == "block"]
    if not blocking:
        return True, "vercel_config_guard: %d root(s) coherent at %s" % (result["roots"], result["ref"])
    log = "\n".join("[%s] %s\n    fix: %s" % (v["code"], v["detail"], v["fix"]) for v in blocking)
    if BREAK_GLASS:
        return True, "BREAK-GLASS override (ORCH_VERCEL_CONFIG_GUARD_BREAK_GLASS):\n" + log
    return False, "vercel.json/git-tree incoherent — this WILL fail on Vercel:\n" + log


def _file_task(project_row, violation, filer):
    """File a remediation task so an advisory finding still gets fixed."""
    if not FILE_TASKS:
        return "disabled"
    key = "%s-%s" % (violation["code"].replace("_", "-"),
                     re.sub(r"[^a-z0-9]+", "-", (violation.get("package_root") or ".").lower()).strip("-") or "root")
    slug = guard_tasks.stable_slug("vercelcfg", project_row.get("name", "app"), key)
    severity = guard_tasks.HIGH if violation.get("severity") == "block" else guard_tasks.ADVISORY
    return filer.file(
        project_row.get("id"), slug,
        ("Fix a Vercel deploy-config incoherence that a local build cannot catch.\n\n"
         "Violation: %s\nWhere: %s\nDetail: %s\nSuggested fix: %s\n\n"
         "Verify with: python3 runner/vercel_config_guard.py %s"
         % (violation["code"], violation.get("package_root"), violation["detail"],
            violation["fix"], project_row.get("name", ""))),
        severity=severity, project_name=project_row.get("name", ""),
        title="%s: %s" % (project_row.get("name", ""), violation["code"]),
        escalate_why=violation["detail"][:800])


def _file_branch_task(project_row, ref, filer):
    """A configured branch that does not exist is a CONFIGURATION defect, not a skip."""
    if not FILE_TASKS:
        return "disabled"
    slug = guard_tasks.stable_slug("branchcfg", project_row.get("name", "app"), ref)
    return filer.file(
        project_row.get("id"), slug,
        ("projects.prod_branch for '%s' is %r, but that ref does not exist in %s.\n\n"
         "vercel_config_guard used to fall back to HEAD here, so it validated whatever branch "
         "happened to be checked out and reported it as production. It now refuses.\n\n"
         "Fix the projects row (or create/push the branch), then re-run:\n"
         "    cd runner && python3 vercel_config_guard.py %s"
         % (project_row.get("name", ""), ref, project_row.get("repo_path", ""),
            project_row.get("name", ""))),
        severity=guard_tasks.CRITICAL, project_name=project_row.get("name", ""),
        title="%s: configured branch %r does not exist" % (project_row.get("name", ""), ref),
        escalate_why="Guards silently validated the wrong ref for this project.")


def run(project=None):
    """Advisory sweep over every project. Logs, reports and files remediation tasks."""
    if not ENABLED:
        print("vercel_config_guard: disabled")
        return {"enabled": False}
    params = {"select": "*"}
    if project:
        params["name"] = "eq.%s" % project
    projects = db.select("projects", params) or []
    filer = guard_tasks.Filer(NAME, max_per_run=MAX_TASKS_PER_RUN)
    summary = {"projects": 0, "violations": 0, "blocking": 0, "misconfigured": 0, "by_code": {}}
    for p in projects:
        repo = p.get("repo_path") or ""
        if not repo or not os.path.isdir(repo):
            continue
        summary["projects"] += 1
        ref = p.get("prod_branch") or p.get("default_base")
        # strict: a configured branch that does not exist is a MISCONFIGURATION to report, never
        # a silent switch to HEAD. See _resolve_branch (the illuminati prod_branch='main' case).
        result = check_repo(repo, ref, p.get("name"), strict=True)
        if result.get("branch_missing"):
            summary["misconfigured"] += 1
            print("  %-14s MISCONFIGURED: %s (projects.prod_branch=%r) — NOT falling back to HEAD"
                  % (p.get("name"), result["skipped"], ref), flush=True)
            _log_event({"event": "branch_missing", "project": p.get("name"), "repo": repo,
                        "configured_ref": ref})
            _file_branch_task(p, ref, filer)
            continue
        for v in result["violations"]:
            summary["violations"] += 1
            summary["by_code"][v["code"]] = summary["by_code"].get(v["code"], 0) + 1
            if v["severity"] == "block":
                summary["blocking"] += 1
            _log_event({"event": "violation", "project": p.get("name"), "ref": result["ref"], **v})
            print("  %-14s %-22s %s" % (p.get("name"), v["code"], v["detail"][:150]), flush=True)
            _file_task(p, v, filer)
        if not result["violations"] and not result.get("skipped"):
            print("  %-14s OK (%d vercel.json root(s) @ %s)" % (p.get("name"), result["roots"], result["ref"]),
                  flush=True)
    summary.update(filer.counters())
    _log_event({"event": "sweep", **summary})
    print("vercel_config_guard: %(projects)d project(s), %(violations)d violation(s) "
          "(%(blocking)d blocking), %(misconfigured)d MISCONFIGURED branch(es)" % summary)
    print("vercel_config_guard: " + filer.summary_line())
    return summary


def stats():
    """Module statistics for the dashboard."""
    try:
        projects = db.select("projects", {"select": "name,repo_path,prod_branch,default_base"}) or []
        bad = 0
        for p in projects:
            repo = p.get("repo_path") or ""
            if repo and os.path.isdir(repo):
                r = check_repo(repo, p.get("prod_branch") or p.get("default_base"), p.get("name"))
                bad += len([v for v in r["violations"] if v["severity"] == "block"])
        return {"enabled": ENABLED, "projects": len(projects), "blocking_violations": bad}
    except (OSError, TypeError, ValueError):
        return {"enabled": ENABLED, "projects": 0, "blocking_violations": 0}


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if args and os.path.isdir(args[0]):
        res = check_repo(args[0], args[1] if len(args) > 1 else None, os.path.basename(args[0]))
        print(json.dumps(res, indent=2, default=str))
    elif args:
        ok, log = gate(args[0], args[1] if len(args) > 1 else None)
        print("VERCEL-CONFIG", "GREEN" if ok else "RED")
        print(log)
    else:
        run()
