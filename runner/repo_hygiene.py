#!/usr/bin/env python3
"""
repo_hygiene.py - shared filesystem hygiene checks for local repo checkouts, used by both
merge_train.py (before every test run) and queue_janitor.py (periodic sweep across all
registered projects).

STRAY COMPILED .js SHADOWING .ts: an ESM ("type":"module") project's runtime module
resolver can pick up a same-basename .js file over its .ts source, independent of git
tracking -- a leftover local tsc/build run that emitted output in-place instead of a
separate dist/ directory silently breaks every test/build that imports the shadowed
module. Observed twice on 2026-07-10: beethoven's web/ (10 files, tracked in git --
required an explicit git rm and a human decision) and tomorrow's server/ tree (4106
files, ALL untracked -- pure local build residue on one machine, invisible to git status
and therefore invisible to code review). This module only ever auto-removes UNTRACKED
files. A tracked .js/.ts collision is a real content decision -- it might be an
intentionally-committed compiled fallback -- so it is left alone and must be handled by a
human (as beethoven's was).

Fail-soft and fail-closed throughout: any error verifying safety (can't read package.json,
can't run git) results in doing nothing for that repo, never in deleting something we
couldn't verify.
"""
import json
import os
import re
import subprocess

_SKIP_DIRS = {"node_modules", ".git", "dist", ".output", ".nuxt"}

# ── LLM-response artifacts committed as files ────────────────────────────────
#
# WHY (2026-08-13): commit 6f82f95d ("regen-from-cache(template)") landed three files in
# the repo root of the beethoven checkout:
#
#     "Step 5: Write a Minimal Test"    <- a prose heading, containing python
#     "test_template_95fc17a.py"        <- content was the literal string of its own name
#     "unittest.main()"                 <- an EMPTY file named after a line of code
#
# Nothing was corrupted; a coder's *prose reply* was parsed as if it were a file
# manifest. The section heading, the ```python fence's filename comment, and the last
# line of the snippet each became a path. They reached orchestrator/dev before being
# cleaned up by hand, and the branch that carried them sat QUEUED behind a stale
# "merge would DELETE or STUB code" note long after the content was gone.
#
# A file named `unittest.main()` is never a real source file, and a root-level `.py`
# whose only content is its own filename is never real code. Both are cheap to detect
# and expensive to miss: `test_template_95fc17a.py` is collected by pytest, where its
# single bare word parses as a name reference and fails the whole collection run.
#
# Detection only. These are TRACKED files by the time anyone notices, and this module's
# standing rule is that removing tracked content is a human decision.

# Tuned against the three real repos on this fleet (13,629 tracked files) to zero false
# positives. The rules that had to be narrowed, and why:
#
#   * `\(` anywhere was the first attempt and flagged "Kale Pasch Resume (6.23.2026) -
#     Revised.docx" — parentheses are ordinary in human filenames. What is NOT ordinary
#     is a name ENDING in a call expression, so the paren rule now anchors to the end
#     and requires the identifier to touch the bracket: unittest.main() matches, the
#     résumé does not.
#   * Prose appended AFTER a file extension is the other real shape, found in the
#     apparently repo as "…/candidate-list.vue (assuming this is a Vue component)" —
#     the model's aside became part of the path. A genuine filename ends at its
#     extension, so ".vue " followed by more text is decisive while a trailing
#     ".docx" is not.
_RESPONSE_ARTIFACT_PATTERNS = (
    re.compile(r"\w\([^)]*\)$"),            # ends in a call: unittest.main(), foo(bar)
    re.compile(r"\.[A-Za-z0-9]{1,5}\s+\S"),  # prose after an extension: "x.vue (assuming …)"
    re.compile(r"[\n\r]|\\n"),              # a whole source file captured AS a filename
    re.compile(r"^(step|phase|part)\s*\d+\s*:", re.I),   # "Step 5: Write a Minimal Test"
    re.compile(r"^(here|note|example|output|usage|summary)\b.*:", re.I),
    re.compile(r"^```"),                    # a stray code fence
    re.compile(r"[<>|*?]"),                 # invalid on common filesystems
)


def _looks_like_response_artifact(rel_path, repo):
    """True when a path looks like prose or code echoed out of an LLM reply.

    Judged on the BASENAME: a legitimately-named file inside an oddly-named directory is
    somebody else's problem, and flagging it would produce duplicate noise per file.
    """
    name = os.path.basename(rel_path.rstrip("\t "))
    if not name:
        return False
    if any(p.search(name) for p in _RESPONSE_ARTIFACT_PATTERNS):
        return True
    if name != rel_path.strip() and rel_path != rel_path.strip():
        return True                      # trailing tab/space in the path itself
    # A .py file whose entire content is its own name — the code-fence filename comment
    # captured as though it were the body.
    if name.endswith(".py"):
        try:
            with open(os.path.join(repo, rel_path)) as f:
                body = f.read().strip()
        except Exception:
            return False
        if body == name or body == os.path.splitext(name)[0]:
            return True
    return False


def find_response_artifacts(repo):
    """Return tracked paths that look like an LLM reply committed as files.

    Detection only — never removes. Fails closed (returns []) if git cannot be queried,
    consistent with the rest of this module.
    """
    tracked = _tracked_files(repo)
    if tracked is None:
        return []
    found = []
    for rel in tracked:
        top = rel.split("/", 1)[0]
        if top in _SKIP_DIRS:
            continue
        if _looks_like_response_artifact(rel, repo):
            found.append(rel)
    return sorted(found)


def _is_esm_project(repo):
    try:
        with open(os.path.join(repo, "package.json")) as f:
            return json.load(f).get("type") == "module"
    except Exception:
        return False


def _tracked_files(repo):
    """Set of git-tracked paths (relative to repo root). None (fail closed -- caller must
    treat this as 'do nothing') if git itself can't be queried."""
    try:
        out = subprocess.run(["git", "ls-files"], cwd=repo, capture_output=True,
                             text=True, timeout=30)
        if out.returncode != 0:
            return None
        return set(out.stdout.splitlines())
    except Exception:
        return None


def find_stray_js_duplicates(repo):
    """Return relative paths of .js files that (1) have a same-basename .ts sibling in the
    same directory and (2) are NOT tracked by git. Only acts on ESM ("type":"module")
    projects -- that's the specific runtime resolution hazard this guards against."""
    if not _is_esm_project(repo):
        return []
    tracked = _tracked_files(repo)
    if tracked is None:
        return []
    strays = []
    for root, dirs, files in os.walk(repo):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        fileset = set(files)
        for fn in files:
            if not fn.endswith(".js"):
                continue
            if (fn[:-3] + ".ts") not in fileset:
                continue
            rel = os.path.relpath(os.path.join(root, fn), repo)
            if rel in tracked:
                continue
            strays.append(rel)
    return strays


def clean_stray_js_duplicates(repo):
    """Remove untracked stray .js files shadowing a .ts sibling. Returns the list of
    relative paths actually removed. Fail-soft: one removal failing doesn't stop the rest."""
    removed = []
    for rel in find_stray_js_duplicates(repo):
        try:
            os.remove(os.path.join(repo, rel))
            removed.append(rel)
        except OSError:
            continue
    return removed
