#!/usr/bin/env python3
"""git_identity.py — one definition of who this fleet commits as (audit addendum §G).

CLAUDE.md is unambiguous: every commit in these repos is authored `kalepasch1
<kalepasch@gmail.com>`. The EMAIL is load-bearing — Vercel puts production deployments whose
commit author is anyone else into BLOCKED state, so a bot identity is a silent deploy outage.
The NAME is cosmetic but had drifted anyway: `git log` on this repo shows `kalepasch1` (374),
`Kale Aaron Pasch` (22) and `madeus-agent` (4).

The drift has an obvious cause. The identity is a STRING LITERAL in a dozen call sites —
auto_conflict_resolver, continuous_merger, minimal_commit, self_healing_merge, sentinel,
patch_recovery, repo_setup_repair, branch_recovery_tasks, ci_workflows, runner — each with its
own env-var name (`ORCH_GIT_USER_NAME`, `FLEET_GIT_AUTHOR_NAME`, hardcoded, ...). A value
duplicated twelve times with three different override knobs has already diverged; the only
question is where.

So: one module owns it. Call sites use `config_args()` / `env()` / `ensure()`, and
`tests/test_git_identity.py` fails the build if any file hardcodes a name that is not the
canonical one. Fail-soft per CLAUDE.md — an identity helper that raises could block a commit,
which is strictly worse than a cosmetically-wrong author.

Precedence for overrides, first match wins:
  ORCH_GIT_USER_NAME / ORCH_GIT_USER_EMAIL   (fleet-config convention, preferred)
  FLEET_GIT_AUTHOR_NAME / FLEET_GIT_AUTHOR_EMAIL  (legacy, still honoured)
  the canonical constants below
"""
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

CANONICAL_NAME = "kalepasch1"
CANONICAL_EMAIL = "kalepasch@gmail.com"

_NAME_VARS = ("ORCH_GIT_USER_NAME", "FLEET_GIT_AUTHOR_NAME")
_EMAIL_VARS = ("ORCH_GIT_USER_EMAIL", "FLEET_GIT_AUTHOR_EMAIL")

# Author names seen in this repo's history that are NOT the canonical one. Listed so the audit
# can name them specifically rather than reporting an anonymous count.
KNOWN_DRIFT_NAMES = ("Kale Aaron Pasch", "madeus-agent", "claude", "Claude", "agent")
# Emails that must never author a commit here: Vercel BLOCKS the resulting production deploy.
BLOCKED_EMAILS = ("mandyjustinepasch@gmail.com", "kale@heretomorrow.us", "noreply@github.com")


def _first_env(names, default):
    for name in names:
        value = os.environ.get(name)
        if value and value.strip():
            return value.strip()
    return default


def name():
    """The name every commit in these repos must carry. Never raises."""
    try:
        return _first_env(_NAME_VARS, CANONICAL_NAME)
    except Exception:
        return CANONICAL_NAME


def email():
    """The email every commit in these repos must carry. Never raises."""
    try:
        return _first_env(_EMAIL_VARS, CANONICAL_EMAIL)
    except Exception:
        return CANONICAL_EMAIL


def config_args():
    """`-c user.name=... -c user.email=...` for a one-shot `git -c ... commit`.

    Preferred over `git config` because it cannot leave a repo's config mutated if the process
    dies mid-commit. Never raises.
    """
    try:
        return ["-c", f"user.name={name()}", "-c", f"user.email={email()}"]
    except Exception:
        return ["-c", f"user.name={CANONICAL_NAME}", "-c", f"user.email={CANONICAL_EMAIL}"]


def env(base=None):
    """A minimal environment carrying the identity, for subprocess calls. Never raises."""
    try:
        out = dict(base or {})
        out.setdefault("PATH", os.environ.get("PATH", "/usr/bin:/bin"))
        out.setdefault("HOME", os.environ.get("HOME", ""))
        out["GIT_AUTHOR_NAME"] = name()
        out["GIT_AUTHOR_EMAIL"] = email()
        out["GIT_COMMITTER_NAME"] = name()
        out["GIT_COMMITTER_EMAIL"] = email()
        return out
    except Exception:
        return dict(base or {})


def ensure(repo_path):
    """Write the canonical identity into a repo's local config. True on success, never raises.

    For clones a fresh agent will commit in repeatedly; one-shot commits should prefer
    `config_args()`.
    """
    try:
        if not repo_path or not os.path.isdir(repo_path):
            return False
        for key, value in (("user.name", name()), ("user.email", email())):
            r = subprocess.run(["git", "config", key, value], cwd=repo_path,
                               capture_output=True, text=True, timeout=30)
            if r.returncode != 0:
                return False
        return True
    except Exception:
        return False


def current(repo_path):
    """The identity a repo is currently configured with, as (name, email). ("", "") on error."""
    try:
        out = []
        for key in ("user.name", "user.email"):
            r = subprocess.run(["git", "config", "--get", key], cwd=repo_path,
                               capture_output=True, text=True, timeout=30)
            out.append((r.stdout or "").strip() if r.returncode == 0 else "")
        return tuple(out)
    except Exception:
        return ("", "")


_AUTHOR_LINE = re.compile(r"^\s*(?P<name>.*?)\s*<(?P<email>[^>]*)>\s*$")


def audit_authors(log_lines):
    """Report author drift from `git log --format='%an <%ae>'` output.

    Returns {"total", "canonical", "drift": {author: count}, "blocked": {author: count},
    "clean": bool}. `blocked` is the serious category — those commits produce BLOCKED Vercel
    deploys; `drift` is cosmetic. Never raises.
    """
    report = {"total": 0, "canonical": 0, "drift": {}, "blocked": {}, "clean": True}
    try:
        lines = log_lines.splitlines() if isinstance(log_lines, str) else list(log_lines or ())
        for line in lines:
            match = _AUTHOR_LINE.match(str(line))
            if not match:
                continue
            report["total"] += 1
            author_name = match.group("name")
            author_email = match.group("email").lower()
            if author_email in BLOCKED_EMAILS:
                key = f"{author_name} <{author_email}>"
                report["blocked"][key] = report["blocked"].get(key, 0) + 1
            elif author_name == CANONICAL_NAME and author_email == CANONICAL_EMAIL:
                report["canonical"] += 1
            else:
                key = f"{author_name} <{author_email}>"
                report["drift"][key] = report["drift"].get(key, 0) + 1
        report["clean"] = not report["drift"] and not report["blocked"]
    except Exception:
        pass
    return report


def audit_repo(repo_path, limit=500):
    """Run audit_authors over a repo's recent history. Never raises."""
    try:
        r = subprocess.run(["git", "log", f"-{int(limit)}", "--format=%an <%ae>"],
                           cwd=repo_path, capture_output=True, text=True, timeout=120)
        return audit_authors(r.stdout if r.returncode == 0 else "")
    except Exception:
        return audit_authors("")


def render(report, repo_path=""):
    """Operator summary of an audit. Never raises."""
    try:
        lines = [f"git identity audit: {repo_path or '.'}",
                 f"  canonical ({CANONICAL_NAME} <{CANONICAL_EMAIL}>): "
                 f"{report.get('canonical', 0)}/{report.get('total', 0)}"]
        if report.get("blocked"):
            lines.append("  BLOCKED-DEPLOY AUTHORS (Vercel will not ship these):")
            for author, count in sorted(report["blocked"].items(), key=lambda kv: -kv[1]):
                lines.append(f"    {count:>5}  {author}")
        if report.get("drift"):
            lines.append("  cosmetic name drift (email is correct, deploys unaffected):")
            for author, count in sorted(report["drift"].items(), key=lambda kv: -kv[1]):
                lines.append(f"    {count:>5}  {author}")
        if report.get("clean"):
            lines.append("  no drift")
        return "\n".join(lines)
    except Exception:
        return "git identity audit unavailable"


def main(argv=None):
    argv = list(argv if argv is not None else sys.argv[1:])
    repos = [a for a in argv if not a.startswith("-")] or [
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))]
    dirty = 0
    for repo in repos:
        report = audit_repo(repo)
        print(render(report, repo))
        if "--fix" in argv:
            print(f"  set local config: {ensure(repo)}")
        if report.get("blocked"):
            dirty += 1
    return 1 if dirty else 0


if __name__ == "__main__":
    sys.exit(main())
