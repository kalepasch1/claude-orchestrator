#!/usr/bin/env python3
"""worktree_identity.py — record which task slug a worktree serves, so nobody guesses.

THE FAILURE THIS EXISTS FOR
---------------------------
On 2026-08-23 tools/reconcile_worktree_evidence.py classified three dirty worktrees as
RECOVERABLE_VALUE while all three were owned by tasks in state RUNNING under another
executor. Answering "is a live task holding this?" needs the owning slug, and the only
thing available was the directory name.

For two of them the directory name IS the slug. For the third it is not: the worktree is
`madeus-group-3` and the slug is
`dropbox-beethoven-madeus-web-multi-tenant-claude-preneur-platform-bi-group-3` — no
prefix, no suffix, no token-boundary relation. A substring match is NOT the answer here:
a false positive silently discards real recoverable work, which is the exact loss the
reconciliation exists to prevent.

So the mapping is RECORDED at creation instead of inferred later, in a
`.orch-worktree.json` inside the worktree.

DESIGN NOTES THAT MATTER
------------------------
* **Dotfile, on purpose.** A recorded identity that itself showed up as uncommitted
  evidence would make every worktree permanently dirty — the reconciler would then be
  reading its own bookkeeping as recoverable work, the same self-feeding loop that
  scripts/lib/orchestration-artifacts.mjs exists to break. It is also matched by
  reconcile_worktree_evidence.GENERATED_HINTS-style filtering and is gitignored.
* **Atomic write.** `os.replace` over a temp file in the same directory, so a crash mid
  write leaves the old identity or none — never a truncated JSON that reads as "unknown
  slug" and re-opens the guessing problem.
* **Fail-soft everywhere.** Reading returns {} and writing returns False rather than
  raising. Worktree creation must never fail because bookkeeping could not be written,
  and a reconciliation must still produce a ledger when an identity is unreadable.
* **Absence is not a negative answer.** `slug_for()` returns "" for a worktree created
  before this landed. Callers must treat "" as "unknown", never as "no owner" — that
  distinction is what keeps a missing file from looking like proof that nothing is
  holding the directory.
"""
import json
import os
import tempfile
import time

#: Filename written inside each worktree. Dotfile so it never registers as evidence.
IDENTITY_FILE = ".orch-worktree.json"

#: Schema tag, so a future format change is detectable rather than silently misread.
SCHEMA = "orch-worktree-identity-v1"


def identity_path(worktree_path):
    """Absolute path of the identity file for a worktree. "" when unusable."""
    if not worktree_path or not isinstance(worktree_path, str):
        return ""
    return os.path.join(worktree_path, IDENTITY_FILE)


def record(worktree_path, slug, task_id="", branch="", lease_token_present=False):
    """Write the identity file. Returns True on success, False on any failure.

    Never raises: worktree creation must not fail because bookkeeping could not be
    written. The lease TOKEN is deliberately not stored — only whether one existed —
    because this file lives in an agent-writable directory and a token is a credential.
    """
    path = identity_path(worktree_path)
    if not path or not slug:
        return False

    payload = {
        "schema": SCHEMA,
        "slug": str(slug),
        "task_id": str(task_id or ""),
        "branch": str(branch or ("agent/%s" % slug)),
        "leased": bool(lease_token_present),
        "recorded_at": int(time.time()),
    }

    tmp = ""
    try:
        os.makedirs(worktree_path, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=worktree_path, prefix=".orch-worktree-", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, sort_keys=True)
            fh.write("\n")
        os.replace(tmp, path)  # atomic within one filesystem
        return True
    except Exception:
        try:
            if tmp and os.path.exists(tmp):
                os.unlink(tmp)
        except Exception:
            pass
        return False


def read(worktree_path):
    """Return the recorded identity dict, or {} when absent/unreadable/malformed."""
    path = identity_path(worktree_path)
    if not path:
        return {}
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def slug_for(worktree_path):
    """The slug this worktree serves, or "" when unknown.

    "" means UNKNOWN, not "unowned". A caller that treats the two the same reintroduces
    the bug this module exists to remove.
    """
    slug = read(worktree_path).get("slug")
    return slug.strip() if isinstance(slug, str) else ""


def branch_for(worktree_path):
    """The agent branch this worktree serves, or "" when unknown."""
    branch = read(worktree_path).get("branch")
    return branch.strip() if isinstance(branch, str) else ""


def task_id_for(worktree_path):
    """The task id that created this worktree, or "" when unknown."""
    task_id = read(worktree_path).get("task_id")
    return task_id.strip() if isinstance(task_id, str) else ""


def resolve_slug(worktree_path):
    """Best available slug + how it was obtained: ("<slug>", "recorded"|"dirname"|"").

    The SOURCE is returned, not just the answer, because the two are not
    interchangeable. "recorded" is proof. "dirname" is a convention that already has a
    documented counterexample (madeus-group-3), so a caller must not use it to justify a
    destructive decision — it is fine for display, and not fine for "nobody owns this,
    delete it".
    """
    recorded = slug_for(worktree_path)
    if recorded:
        return recorded, "recorded"
    if worktree_path and isinstance(worktree_path, str):
        name = os.path.basename(os.path.normpath(worktree_path))
        if name:
            return name, "dirname"
    return "", ""


def main(argv=None):
    """CLI: `worktree_identity.py record <path> <slug> [task_id] [branch]` / `read <path>`."""
    import sys
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print(__doc__.strip().splitlines()[0])
        return 2

    cmd, rest = argv[0], argv[1:]
    if cmd == "record":
        if len(rest) < 2:
            print("usage: worktree_identity.py record <path> <slug> [task_id] [branch]")
            return 2
        path, slug = rest[0], rest[1]
        task_id = rest[2] if len(rest) > 2 else ""
        branch = rest[3] if len(rest) > 3 else ""
        # Exit 0 even on failure: this must never break worktree creation.
        print("recorded" if record(path, slug, task_id, branch, bool(task_id)) else "not recorded")
        return 0
    if cmd == "read":
        if not rest:
            print("usage: worktree_identity.py read <path>")
            return 2
        print(json.dumps(read(rest[0]), indent=2, sort_keys=True))
        return 0
    print("unknown command: %s" % cmd)
    return 2


if __name__ == "__main__":
    import sys
    sys.exit(main())
