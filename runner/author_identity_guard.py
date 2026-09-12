#!/usr/bin/env python3
"""author_identity_guard.py — enforce the commit identity at push time (audit addendum §G).

§G settles WHAT the identity is: every commit in these repos is authored
`kalepasch1 <kalepasch@gmail.com>`. The definition lives in `git_identity.py`
(§G, sibling shard) and in CLAUDE.md. This module is the other half — the part
that makes the definition true of what actually leaves the machine.

Why a push-time gate and not only a lint. The two failure modes are not equal:

  * WRONG EMAIL is a silent production outage. Vercel puts a production deploy
    whose commit author is anyone else into BLOCKED state. Nothing fails loudly;
    the deploy simply never happens, and the repo looks healthy. By the time it
    is noticed the commit is already on the remote and the fix is a rewrite.
    So a blocked-email commit is REFUSED before it is pushed.

  * WRONG NAME is cosmetic — §G says so explicitly ("harmless, but standardize").
    A guard that blocks a push over a display name would be worse than the drift
    it prevents, so name drift only WARNS.

  * THE OWNER'S GITHUB NOREPLY ALIAS IS THE OWNER. `102100311+kalepasch1@
    users.noreply.github.com` is what GitHub stamps on every commit the owner makes
    through the web UI, including the merge commit from the "Merge pull request"
    button. Until 2026-08-18 this guard compared against the canonical address by
    string equality and therefore refused all of them — which meant the 14 commits
    that had accumulated on claude-orchestrator's `master` could not be pushed back
    onto `orchestrator/dev` at all, and the release train stayed wedged. It was also
    empirically wrong: a 400-deployment Vercel audit on 2026-08-17 found this alias
    deploying to production while 18 of 18 genuinely-foreign authors were BLOCKED.
    The allow-list is now `is_owner_email()`, which accepts the canonical address and
    the owner's alias and nothing else.

Fail-soft per CLAUDE.md: any git or parsing failure allows the push and says why.
A guard that wedges pushes on its own bug is the one outcome worse than drift.

Wire as a pre-push hook alongside `production_push_guard.py`; both read the same
stdin format (`<local ref> <local sha> <remote ref> <remote sha>` per line), so
either can run first. Standalone audit of history:

    python3 runner/author_identity_guard.py --audit 500
"""
from __future__ import annotations

import os
import re
import subprocess
import sys

RUNNER_DIR = os.path.dirname(os.path.abspath(__file__))
if RUNNER_DIR not in sys.path:
    sys.path.insert(0, RUNNER_DIR)

ZERO_SHA = "0" * 40

# Canonical values. Kept in sync with git_identity.py, which is the owning module
# once it lands; this file falls back to the constants so the guard works on a
# checkout that does not have it yet (and can never be disabled by its absence).
_FALLBACK_NAME = "kalepasch1"
_FALLBACK_EMAIL = "kalepasch@gmail.com"
_FALLBACK_LOGIN = "kalepasch1"

# Authoring as any of these puts the Vercel production deploy in BLOCKED state.
_FALLBACK_BLOCKED_EMAILS = (
    "mandyjustinepasch@gmail.com",
    "kale@heretomorrow.us",
    "noreply@github.com",
)

#: "enforce" (default) refuses blocked-email pushes; "warn" reports only;
#: "off" disables the guard entirely. Break-glass without editing the hook.
ORCH_AUTHOR_IDENTITY_GUARD = os.environ.get("ORCH_AUTHOR_IDENTITY_GUARD", "enforce")
#: Cap on commits inspected per ref, so a first push of a long branch stays fast.
ORCH_AUTHOR_IDENTITY_MAX_COMMITS = int(
    os.environ.get("ORCH_AUTHOR_IDENTITY_MAX_COMMITS", "500")
)


def _identity_module():
    """The owning module if it exists on this checkout, else None. Never raises."""
    try:
        import git_identity  # type: ignore

        return git_identity
    except Exception:
        return None


def canonical_name() -> str:
    mod = _identity_module()
    try:
        if mod is not None and hasattr(mod, "name"):
            value = mod.name()
            if value:
                return str(value)
    except Exception:
        pass
    return os.environ.get("ORCH_GIT_USER_NAME") or _FALLBACK_NAME


def canonical_email() -> str:
    mod = _identity_module()
    try:
        if mod is not None and hasattr(mod, "email"):
            value = mod.email()
            if value:
                return str(value)
    except Exception:
        pass
    return os.environ.get("ORCH_GIT_USER_EMAIL") or _FALLBACK_EMAIL


def canonical_login() -> str:
    mod = _identity_module()
    try:
        if mod is not None and hasattr(mod, "login"):
            value = mod.login()
            if value:
                return str(value)
    except Exception:
        pass
    return os.environ.get("ORCH_GIT_USER_LOGIN") or _FALLBACK_LOGIN


def is_owner_email(address) -> bool:
    """True if `address` is the owner — canonical address, or their GitHub noreply alias.

    Delegates to `git_identity.is_owner_email` when the owning module has it, and otherwise
    reimplements it here. The duplication is deliberate: this guard runs from a pre-push hook
    on checkouts that may predate the owning module, and a guard that silently reverts to
    string equality on an old checkout would re-wedge the release train exactly where it was
    wedged on 2026-08-18 (see git_identity.is_owner_email for the full account).
    """
    mod = _identity_module()
    try:
        if mod is not None and hasattr(mod, "is_owner_email"):
            return bool(mod.is_owner_email(address))
    except Exception:
        pass
    try:
        addr = (address or "").strip().lower()
        if not addr:
            return False
        if addr == canonical_email().strip().lower():
            return True
        pattern = (r"^(?:\d+\+)?" + re.escape(canonical_login())
                   + r"@users\.noreply\.github\.com$")
        return bool(re.match(pattern, addr, re.IGNORECASE))
    except Exception:
        return False


def blocked_emails() -> tuple:
    mod = _identity_module()
    try:
        listed = getattr(mod, "BLOCKED_EMAILS", None)
        if listed:
            return tuple(str(e).lower() for e in listed)
    except Exception:
        pass
    return _FALLBACK_BLOCKED_EMAILS


def _git(repo, *args):
    """Run git, returning stdout. Returns '' on any failure (fail-soft)."""
    try:
        proc = subprocess.run(
            ["git", *args], cwd=repo, capture_output=True, text=True, check=False
        )
        return proc.stdout.strip() if proc.returncode == 0 else ""
    except Exception:
        return ""


def pushed_ranges(lines):
    """Parse pre-push stdin into (local_sha, remote_sha) pairs worth inspecting.

    Deletions (local sha all zeros) push no commits and are skipped.
    """
    ranges = []
    for line in lines or []:
        fields = str(line).strip().split()
        if len(fields) != 4:
            continue
        _local_ref, local_sha, _remote_ref, remote_sha = fields
        if local_sha == ZERO_SHA:
            continue
        ranges.append((local_sha, remote_sha))
    return ranges


def commit_authors(repo, local_sha, remote_sha, limit=None):
    """[(sha, name, email)] for commits this push would add. Empty on any failure.

    "Would add" means add TO THE REMOTE REPOSITORY, not to one branch of it. A
    commit that already exists on some other remote-tracking ref is not
    introduced by this push, and must not be judged by it.

    Until 2026-08-24 only the new-branch case reasoned that way. The
    ``remote_sha..local_sha`` form used for an existing branch reports every
    commit missing from THAT BRANCH, including commits long since published
    elsewhere in the same repo. On apparently, pushing ten commits to
    ``orchestrator/dev`` was refused over ``6cd4d679`` — an automated corpus
    harvest authored ``corpus@apparently.cc``, which by then sat on
    ``origin/master`` and 302 other remote branches.

    Refusing that push prevented nothing: the commit was already on the remote,
    and Vercel had already seen it. What the refusal did do was recommend
    ``git rebase --exec 'git commit --amend --reset-author'``, which on
    published history does not correct the commit — it forks it, leaving the
    original reachable from 303 refs and a divergent duplicate on the branch
    being pushed. The guard's own rationale says the fix for an
    already-remote commit is a rewrite; the unstated premise is that the
    commit is NOT already remote. Once it is, refusing costs a rewrite of
    public history and buys nothing.

    So both cases now exclude ``--remotes``. Only commits that exist nowhere on
    any remote are subject to this gate — which is what "this push would add"
    meant all along.
    """
    limit = ORCH_AUTHOR_IDENTITY_MAX_COMMITS if limit is None else limit
    if remote_sha and remote_sha != ZERO_SHA:
        revs = [f"{remote_sha}..{local_sha}", "--not", "--remotes"]
    else:
        # A first push of a new branch reports an all-zero remote SHA. Inspecting
        # ``local_sha`` by itself treats the repository's entire ancestry as newly
        # pushed and can reject a correctly-authored one-commit branch because an
        # unrelated commit already on origin used a historical email.
        revs = [local_sha, "--not", "--remotes"]
    out = _git(repo, "log", f"--max-count={limit}", "--format=%H%x1f%an%x1f%ae", *revs)
    authors = []
    for line in out.splitlines():
        parts = line.split("\x1f")
        if len(parts) == 3:
            authors.append((parts[0], parts[1], parts[2]))
    return authors


def classify(authors):
    """Split authors into blocked-email and name-drift findings.

    Returns ``(blocked, drifted)``. An unknown non-owner email is treated as
    blocked too: the allow-list is the owner's identity, not the deny-list. The
    deny-list only exists to name the specific addresses already seen.

    The allow-list is `is_owner_email`, not string equality against the canonical
    address, because GitHub's own merge button authors as the owner's noreply alias
    and that alias demonstrably deploys (see `git_identity.is_owner_email`). Under
    string equality this guard refused every merge commit the owner had ever made
    through the GitHub UI, which is what wedged the release train on 2026-08-18.
    """
    want_name = canonical_name()
    blocked, drifted = [], []
    for sha, name, email in authors:
        if not is_owner_email(email):
            blocked.append((sha, name, email))
        elif name != want_name:
            drifted.append((sha, name, email))
    return blocked, drifted


def _report(blocked, drifted, stream):
    for sha, name, email in blocked:
        print(
            f"author_identity_guard: BLOCKED-EMAIL {sha[:12]} <{email}> "
            f"(expected <{canonical_email()}>) — Vercel would mark this deploy BLOCKED",
            file=stream,
        )
    for sha, name, _email in drifted:
        print(
            f"author_identity_guard: name drift {sha[:12]} '{name}' "
            f"(canonical '{canonical_name()}') — cosmetic, not blocking",
            file=stream,
        )


def check(repo, lines, stream=None):
    """Return 0 to allow the push, 1 to refuse it. Never raises."""
    stream = stream or sys.stderr
    mode = (ORCH_AUTHOR_IDENTITY_GUARD or "enforce").strip().lower()
    if mode == "off":
        return 0

    all_blocked, all_drifted = [], []
    try:
        for local_sha, remote_sha in pushed_ranges(lines):
            authors = commit_authors(repo, local_sha, remote_sha)
            blocked, drifted = classify(authors)
            all_blocked.extend(blocked)
            all_drifted.extend(drifted)
    except Exception as exc:  # fail-soft: never wedge a push on our own bug
        print(
            f"author_identity_guard: could not inspect authors ({exc}); allowing push",
            file=stream,
        )
        return 0

    _report(all_blocked, all_drifted, stream)

    if all_blocked and mode == "enforce":
        print(
            "author_identity_guard: REFUSED. Fix with\n"
            f"    git config user.name \"{canonical_name()}\"\n"
            f"    git config user.email \"{canonical_email()}\"\n"
            "    git rebase -i --exec 'git commit --amend --no-edit --reset-author' <base>\n"
            "The rewrite is safe here: only commits that exist on NO remote ref reach\n"
            "this report, so nothing you amend has been published.\n"
            "Break-glass: ORCH_AUTHOR_IDENTITY_GUARD=warn",
            file=stream,
        )
        return 1
    return 0


def audit(repo, limit=500, stream=None):
    """Report identity drift across recent history. Read-only; always returns 0."""
    stream = stream or sys.stdout
    out = _git(repo, "log", f"--max-count={limit}", "--format=%H%x1f%an%x1f%ae")
    authors = [
        tuple(p.split("\x1f")) for p in out.splitlines() if len(p.split("\x1f")) == 3
    ]
    blocked, drifted = classify(authors)
    print(
        f"author_identity_guard: {len(authors)} commits inspected — "
        f"{len(blocked)} wrong-email, {len(drifted)} name-drift",
        file=stream,
    )
    counts = {}
    for _sha, name, email in blocked + drifted:
        counts[f"{name} <{email}>"] = counts.get(f"{name} <{email}>", 0) + 1
    for who, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {n:>4}  {who}", file=stream)
    return 0


def main(argv=None, stdin=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    repo = _git(os.getcwd(), "rev-parse", "--show-toplevel") or os.getcwd()
    if argv and argv[0] == "--audit":
        limit = int(argv[1]) if len(argv) > 1 and argv[1].isdigit() else 500
        return audit(repo, limit)
    return check(repo, stdin if stdin is not None else sys.stdin)


if __name__ == "__main__":
    raise SystemExit(main())
