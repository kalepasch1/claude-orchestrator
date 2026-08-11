#!/usr/bin/env python3
"""Cross-project patch transplant hints before model spend."""
import logging
import os
import sys
import re
import subprocess

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import merged_diff_library
import db

log = logging.getLogger(__name__)

MARK = "PATCH TRANSPLANT"

#: Lines a transplanted patch must never carry into an unrelated task.
#:
#: `adapt_patch` rewrites a prior diff's file headers so it lands somewhere new.
#: That is fine for ordinary code, and unacceptable for a change to a security
#: gate, a credential or a permission: the change was reviewed against its
#: original file, and header rewriting moves it somewhere it never was. This
#: gate is FAIL-CLOSED — the one place in this module that refuses rather than
#: degrades, because a silently-relocated security change is worse than no
#: transplant at all.
SECURITY_SENSITIVE = re.compile(
    r"""(?x)
    ORCH_[A-Z0-9_]*SECURITY_GATE      # the gate this check was stubbed for
    | \bSECRET(?:_KEY)?\b
    | \bAPI[_-]?KEY\b
    | \bACCESS[_-]?TOKEN\b
    | \bPRIVATE[_-]?KEY\b
    | \bPASSWORD\b
    | BEGIN\s+(?:RSA\s+|OPENSSH\s+|EC\s+)?PRIVATE\s+KEY
    | \bAUTHORIZATION\b
    | \bchmod\s+(?:\+s|777)
    | \bsudo\b
    """,
    re.I,
)


def hint(task):
    if MARK in str(task.get("prompt") or ""):
        return ""
    hits = merged_diff_library.find(task, limit=1)
    if not hits:
        return ""
    h = hits[0]
    similarity = h.get("similarity", 0)
    if similarity < float(os.environ.get("ORCH_PATCH_TRANSPLANT_MIN_SIM", "0.18")):
        return ""
    return (f"{MARK}: before drafting from scratch, adapt the proven patch "
            f"{h.get('project', '?')}/{h.get('slug', '?')} (similarity {similarity}).\n"
            f"Prior intent: {h.get('summary', '')}\n"
            f"Relevant prior diff excerpt:\n{(h.get('diff') or '')[:2500]}")


def pre_claim_hook(task):
    try:
        h = hint(task)
        if not h:
            return task
        prompt = h + "\n\n" + str(task.get("prompt") or "")
        db.update("tasks", {"id": task["id"]}, {"prompt": prompt})
        return {**task, "prompt": prompt}
    except Exception as exc:
        log.debug("patch_transplant: pre_claim_hook skipped: %s", exc)
        return task


def find_transplant_source(target_task, min_similarity=0.25):
    """Find prior patch with similarity >= min_similarity for transplant."""
    try:
        rows = db.select("patch_history", {})
        if not rows:
            return None
        for row in rows:
            if row.get("similarity", 0) >= min_similarity:
                return {
                    "slug": row.get("slug"),
                    "source": row.get("source"),
                    "project": row.get("project"),
                    "task_class": row.get("task_class"),
                    "similarity": row.get("similarity"),
                    "patch_diff": row.get("patch_diff")
                }
    except Exception as exc:
        # CLAUDE.md: a broad catch is the fail-soft convention here, but a
        # SILENT one is the defect. Diagnose before swallowing.
        log.debug("patch_transplant: transplant-source lookup failed: %s", exc)
    return None


def security_findings(diff_text, limit=10):
    """Security-sensitive tokens on lines a patch ADDS. [] when clean.

    Only added lines (`+`) are inspected. A patch that *removes* a hardcoded
    secret is a patch worth transplanting; judging it by the removed line would
    block exactly the change we want.

    Fail-soft on bad input — an unparseable diff yields no findings, and the
    caller still has `apply_patch`'s dry run in front of it.
    """
    if isinstance(diff_text, bytes):
        diff_text = diff_text.decode("utf-8", errors="replace")
    if not isinstance(diff_text, str) or not diff_text:
        return []
    findings = []
    try:
        for line in diff_text.splitlines():
            if not line.startswith("+") or line.startswith("+++"):
                continue
            match = SECURITY_SENSITIVE.search(line)
            if match:
                token = match.group(0)
                if token not in findings:
                    findings.append(token)
                if len(findings) >= max(1, int(limit or 1)):
                    break
    except Exception:
        return findings
    return findings


def adapt_patch(prior_diff, target_task, target_files=None):
    """Adapt prior patch for target task context.

    Returns the adapted diff, or None when the patch is empty or the
    security gate refuses it (see `SECURITY_SENSITIVE`).
    """
    if not prior_diff:
        return None

    was_bytes = isinstance(prior_diff, bytes)
    adapted = prior_diff
    if isinstance(adapted, bytes):
        adapted = adapted.decode("utf-8", errors="replace")

    if target_files:
        # Rewrite headers only when the diff targets none of the requested
        # files; rewriting per-file would clobber earlier matches.
        current_files = re.findall(r"--- a/(\S+)", adapted)
        already_targeted = any(
            cf in target_files or os.path.basename(cf) in target_files
            for cf in current_files
        )
        if not already_targeted:
            target_file = target_files[0]
            adapted = re.sub(r"--- a/\S+", f"--- a/{target_file}", adapted)
            adapted = re.sub(r"\+\+\+ b/\S+", f"+++ b/{target_file}", adapted)

    # IMPLEMENTED 2026-08-11. This was `if <condition>: pass` — a security check
    # that parsed, ran, and did nothing, so every security-sensitive patch was
    # transplanted exactly as if the check were absent. Refuse instead.
    blocked = security_findings(adapted)
    if blocked:
        log.warning(
            "patch_transplant: refusing to transplant — adapted patch touches "
            "security-sensitive lines (%s); the change was reviewed against its "
            "original file, not this target",
            ", ".join(blocked[:3]),
        )
        return None

    if was_bytes:
        adapted = adapted.encode("utf-8")

    return adapted


def apply_patch(patch_diff, repo_path="/", allow_rejects=True):
    """Apply patch to repository."""
    if not patch_diff:
        return {"applied": False, "rejects": 0, "fallback_rebuild": True}

    if isinstance(patch_diff, str):
        patch_diff = patch_diff.encode("utf-8")

    try:
        result = subprocess.run(
            ["patch", "--dry-run", "-p1"],
            input=patch_diff,
            cwd=repo_path,
            capture_output=True,
            timeout=30
        )

        if result.returncode == 0:
            result = subprocess.run(
                ["patch", "-p1"],
                input=patch_diff,
                cwd=repo_path,
                capture_output=True,
                timeout=30
            )

            if result.returncode == 0:
                return {"applied": True, "rejects": 0}
            else:
                return {"applied": False, "rejects": 1, "fallback_rebuild": True}
        else:
            stderr = result.stderr.decode("utf-8", errors="replace")
            reject_count = stderr.count("FAILED") + stderr.count("reject")
            if not allow_rejects and reject_count > 0:
                return {"applied": False, "rejects": reject_count, "fallback_rebuild": True}
            return {"applied": False, "rejects": reject_count}
    except subprocess.TimeoutExpired:
        return {"applied": False, "rejects": 0, "fallback_rebuild": True}
    except Exception as exc:
        log.debug("patch_transplant: apply_patch failed: %s", exc)
        return {"applied": False, "rejects": 0, "fallback_rebuild": True}
