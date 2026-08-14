#!/usr/bin/env python3
"""remote_url_guard.py — keep credentials out of git remote URLs and out of logs (§F).

Audit addendum §F, security item: the `origin` remote URL carried an embedded GitHub PAT,
visible to anything that ran `git remote -v` — including every diagnostic this fleet writes
to a log file, a task note, or a DB row. A token in a remote URL is a token in every log.

Two jobs, both read-only-by-default:

  * `redact(text)` — strip `user:secret@` from any URL-shaped substring. Every fleet code path
    that echoes a remote URL should pass it through this first. Cheap, total, no I/O.
  * `audit(repo)` / `scrub(repo)` — detect remotes carrying credentials and, only when
    explicitly asked, rewrite them to the clean form. Credentials then come from the
    osxkeychain helper / `gh auth`, which is already configured on both machines.

This module NEVER prints the secret it finds, never writes it anywhere, and never removes a
remote. Fail-soft throughout: an unreadable repo returns an empty finding, not an exception.
"""
import os
import re
import subprocess
import sys

# scheme://userinfo@host/path — userinfo is what must never survive.
_URL_WITH_CREDS = re.compile(r"(?P<scheme>[a-zA-Z][a-zA-Z0-9+.\-]*://)(?P<userinfo>[^/@\s]+)@")
# Token shapes worth naming explicitly in a finding (never printed in full).
_TOKEN_HINTS = ("ghp_", "github_pat_", "gho_", "ghs_", "ghu_", "glpat-", "xoxb-")


def redact(text):
    """Return `text` with any URL userinfo replaced by ``***``. Never raises."""
    try:
        if not text:
            return ""
        return _URL_WITH_CREDS.sub(lambda m: m.group("scheme") + "***@", str(text))
    except Exception:
        return ""


def has_credentials(url):
    """True when `url` embeds userinfo (a PAT, a user:password pair, ...). Never raises."""
    try:
        return bool(url) and bool(_URL_WITH_CREDS.search(str(url)))
    except Exception:
        return False


def clean_url(url):
    """Strip embedded credentials from a URL, leaving it usable with a credential helper."""
    try:
        if not url:
            return ""
        return _URL_WITH_CREDS.sub(lambda m: m.group("scheme"), str(url))
    except Exception:
        return ""


def token_hint(url):
    """Name the credential SHAPE found (never its value), or "" when none is recognised."""
    try:
        match = _URL_WITH_CREDS.search(str(url or ""))
        if not match:
            return ""
        userinfo = match.group("userinfo")
        for prefix in _TOKEN_HINTS:
            if prefix in userinfo:
                return prefix + "…"
        return "userinfo"
    except Exception:
        return ""


def _git(repo, *args, timeout=30):
    try:
        r = subprocess.run(("git",) + args, cwd=repo, capture_output=True, text=True,
                           timeout=timeout, errors="replace")
        return (r.returncode, r.stdout or "", r.stderr or "")
    except Exception:
        return (1, "", "")


def list_remotes(repo):
    """{name: url} for the repo's push/fetch remotes. Fail-soft -> {}."""
    out = {}
    try:
        rc, text, _ = _git(repo, "remote", "-v")
        if rc != 0:
            return {}
        for line in text.splitlines():
            parts = line.split()
            if len(parts) >= 2:
                out[parts[0]] = parts[1]
    except Exception:
        return {}
    return out


def audit(repo):
    """Report which remotes embed credentials. The report is SAFE TO LOG.

    Returns {"repo", "findings": [{remote, redacted, token_hint, clean}], "clean": bool}.
    """
    report = {"repo": repo or "", "findings": [], "clean": True}
    try:
        for name, url in sorted(list_remotes(repo).items()):
            if has_credentials(url):
                report["findings"].append({
                    "remote": name,
                    "redacted": redact(url),
                    "token_hint": token_hint(url),
                    "clean": clean_url(url),
                })
        report["clean"] = not report["findings"]
    except Exception:
        report["clean"] = True
    return report


def scrub(repo, apply=False):
    """Rewrite credential-bearing remotes to their clean form.

    Default is a DRY RUN — pass apply=True to actually run `git remote set-url`. Returns the
    audit report with a "rewrote" list added. Never raises, never deletes a remote.
    """
    report = audit(repo)
    report["rewrote"] = []
    report["applied"] = bool(apply)
    try:
        for finding in report["findings"]:
            if not finding["clean"]:
                continue
            if apply:
                rc, _, _ = _git(repo, "remote", "set-url", finding["remote"], finding["clean"])
                if rc == 0:
                    report["rewrote"].append(finding["remote"])
            else:
                report["rewrote"].append(finding["remote"])
    except Exception:
        pass
    return report


def render(report):
    """Operator summary. Contains no secret material. Never raises."""
    try:
        if report.get("clean"):
            return f"remote-url guard: {report.get('repo', '')} — no embedded credentials"
        lines = [f"remote-url guard: {report.get('repo', '')} — CREDENTIALS IN REMOTE URL"]
        for finding in report.get("findings", []):
            lines.append(f"  {finding['remote']}: {finding['redacted']}  ({finding['token_hint']})")
        lines.append("  fix: git remote set-url <remote> <clean-url>  (credentials then come from")
        lines.append("       the osxkeychain helper / gh auth, which both machines already have)")
        if report.get("rewrote") and not report.get("applied"):
            lines.append("  dry run — re-run with --apply to rewrite: " + ", ".join(report["rewrote"]))
        return "\n".join(lines)
    except Exception:
        return "remote-url guard: report unavailable"


def main(argv=None):
    argv = list(argv if argv is not None else sys.argv[1:])
    apply = "--apply" in argv
    paths = [a for a in argv if not a.startswith("-")]
    repos = paths or [os.path.dirname(os.path.dirname(os.path.abspath(__file__)))]
    dirty = 0
    for repo in repos:
        report = scrub(repo, apply=apply) if apply else audit(repo)
        print(render(report))
        dirty += 0 if report.get("clean") else 1
    return 1 if dirty else 0


if __name__ == "__main__":
    sys.exit(main())
