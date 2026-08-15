#!/usr/bin/env python3
"""verified_firing.py — ALREADY FIXED AND VERIFIED FIRING. DO NOT REDO. (audit addendum §B)

The two-session reconciliation found the same guards being "discovered as missing" and
re-implemented by successive sessions, because a fix that lands and works leaves no trace an
audit can see. A guard that never fires looks exactly like a guard that does not exist.

This is the companion to `do_not_touch.py`. That module records things deliberately NOT wired;
this one records things that ARE wired, verified firing, and must not be rebuilt:

  * an audit that re-flags one of these is producing a false finding, and should say so;
  * a task asking to implement one of these should be marked SUPERSEDED, not re-coded;
  * `check(entry)` re-verifies the fix is still in place, so an entry cannot rot into a lie —
    the failure mode this module would otherwise introduce.

Fail-soft per CLAUDE.md: an unknown key returns False, verification failure returns a
"cannot verify" result rather than raising.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
REPO = os.path.dirname(HERE)

# key -> (what was fixed, where it lives, a substring that must still be present there)
VERIFIED = {
    "sentinel-hotfix-rescue": (
        "checkout_guard COMMITS dirty protected paths to hotfix/sentinel-rescue-<ts> instead of "
        "stashing them. Stashes are write-only here — nothing ever pops one — so the old "
        "behaviour silently swallowed operator hotfixes twice in one night.",
        "runner/sentinel.py",
        "hotfix/sentinel-rescue-",
    ),
    "sentinel-no-untracked-stash": (
        "checkout_guard never runs `git stash push -u`. The -u flag destroyed 282 batches of "
        "queued intake drops between 2026-07-08 and 07-16; untracked files also never block a "
        "branch switch, so it bought nothing.",
        "runner/sentinel.py",
        "NEVER stashes untracked files",
    ),
    "wip-stash-rescue": (
        "Any anonymous `WIP on <base>` stash is auto-preserved by pointing a "
        "hotfix/stash-rescue-<ts> branch at the stash commit — defence in depth, since no grep "
        "can prove a negative about future code.",
        "runner/sentinel.py",
        "def wip_stash_rescue",
    ),
    "stash-drift-alarm": (
        "Unreconciled stashes are ALERTED on past a threshold and never auto-popped or dropped. "
        "Auto-popping stale diffs onto a moved-on codebase is its own hazard.",
        "runner/sentinel.py",
        "def stash_drift_guard",
    ),
    "self-healing-merge-worktree": (
        "self_healing_merge classifies in a DETACHED WORKTREE. It used to stash the main "
        "checkout and never pop — the improvement-wipe pattern, third occurrence.",
        "runner/self_healing_merge.py",
        "DETACHED WORKTREE",
    ),
    "branch-gc-durability": (
        "branch_gc keeps any local branch not present on origin. Deleting it would destroy the "
        "only copy of its commits; 23.6% of fleet output was re-doing exactly that work.",
        "runner/branch_gc.py",
        "not present on origin",
    ),
    "core-retry-rpcs": (
        "db.CORE_RETRY_RPCS retries the lease/claim/complete RPCs with bounded backoff. This is "
        "the hardening for the outage class that mass-quarantined 91 tasks on 2026-07-29.",
        "runner/db.py",
        "CORE_RETRY_RPCS",
    ),
    "git-identity-canonical": (
        "One module owns the commit identity (§G). The value was a string literal in a dozen "
        "call sites with three different override knobs, and had already drifted.",
        "runner/git_identity.py",
        "CANONICAL_NAME",
    ),
}


def is_verified(key):
    """True when `key` names a fix that is already in place. Never raises."""
    try:
        return str(key) in VERIFIED
    except Exception:
        return False


def describe(key):
    """What was fixed, or "" when the key is unknown. Never raises."""
    try:
        return VERIFIED.get(str(key), ("", "", ""))[0]
    except Exception:
        return ""


def check(key, repo=None):
    """Re-verify one entry against the working tree.

    Returns {"key", "present": bool, "path", "marker", "reason"}. `present` is False both when
    the fix is genuinely gone and when the file cannot be read — an entry that cannot be
    verified must not report itself as verified. Never raises.
    """
    result = {"key": str(key), "present": False, "path": "", "marker": "", "reason": ""}
    try:
        if str(key) not in VERIFIED:
            result["reason"] = "unknown key"
            return result
        _, rel_path, marker = VERIFIED[str(key)]
        result["path"], result["marker"] = rel_path, marker
        full = os.path.join(repo or REPO, rel_path)
        try:
            with open(full, errors="replace") as f:
                text = f.read()
        except FileNotFoundError:
            result["reason"] = f"{rel_path} not found"
            return result
        except OSError as exc:
            result["reason"] = f"cannot read {rel_path}: {exc}"
            return result
        if marker in text:
            result["present"] = True
        else:
            result["reason"] = f"marker {marker!r} missing from {rel_path} — the fix regressed"
        return result
    except Exception:
        result["reason"] = "verification failed"
        return result


def check_all(repo=None):
    """Re-verify every entry. Returns a list of check() results. Never raises."""
    try:
        return [check(key, repo=repo) for key in sorted(VERIFIED)]
    except Exception:
        return []


def regressions(repo=None):
    """Entries whose fix is no longer detectable — the ones worth alerting on."""
    try:
        return [r for r in check_all(repo=repo) if not r["present"]]
    except Exception:
        return []


def filter_findings(findings, key_of=None):
    """Drop audit findings that name an already-verified fix.

    `findings` may be strings or dicts; `key_of` extracts the verified-key from one. Default:
    the finding itself when it is a string, else its "key" field. Never raises.
    """
    try:
        def default_key(finding):
            return finding if isinstance(finding, str) else (finding or {}).get("key", "")

        extract = key_of or default_key
        return [f for f in (findings or []) if not is_verified(extract(f))]
    except Exception:
        return list(findings or [])


def render(results=None, repo=None):
    """Operator summary. Never raises."""
    try:
        results = check_all(repo=repo) if results is None else results
        lines = ["ALREADY FIXED — VERIFIED FIRING (audit addendum §B)", "=" * 50]
        for result in results:
            status = "ok " if result["present"] else "GONE"
            lines.append(f"  [{status}] {result['key']:<32} {result['path']}")
            if not result["present"]:
                lines.append(f"          {result['reason']}")
        gone = [r for r in results if not r["present"]]
        lines.append("")
        lines.append(f"  {len(results) - len(gone)}/{len(results)} still in place")
        if gone:
            lines.append("  A missing entry is a REGRESSION, not a task to re-plan: the fix "
                         "existed and was verified.")
        return "\n".join(lines)
    except Exception:
        return "verified-firing manifest unavailable"


def main(argv=None):
    argv = list(argv if argv is not None else sys.argv[1:])
    results = check_all()
    print(render(results))
    return 1 if any(not r["present"] for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
