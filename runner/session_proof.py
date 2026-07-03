#!/usr/bin/env python3
"""
session_proof.py - machine-checkable proof that an agent session did REAL work.

Some sessions burn a whole model call and produce nothing: the CLI opened without instructions
and the model replied "what would you like to work on?", or it chatted without touching the repo.
Those used to be scored as completed runs. This module gives the runner a cheap, deterministic
verdict per session:

    verify_session(task, output_text, repo, branch) -> {ok, reasons, diff_files, diff_lines}

Checks:
  (a) the branch's diff vs the base branch is non-empty beyond noise paths
      (.claude/, *.log, settings.local.json) — via `git diff --numstat`
  (b) the output does not match known stall phrases ("what would you like to work on", ...)
  (c) prompt-echo: the output actually engages with the task prompt (>=3 significant words
      from the first 400 chars of the prompt appear in the output; skipped for tiny prompts)
  (d) if the output mentions tests passing, that's recorded as a bonus reason (not required)

And when a session provably received no instructions, reinjection_prompt(task) builds the retry
prompt that inlines the FULL original task prompt so the next session cannot start blank.

Pure functions: only subprocess for git, no db access, no model calls.
"""
import re
import subprocess

STALL_RX = re.compile(
    r"what would you like to work on|i'm ready to help|i don't have a specific task",
    re.IGNORECASE)

TESTS_PASS_RX = re.compile(
    r"(all\s+)?tests?\s+(are\s+|is\s+)?(now\s+)?pass(ed|ing)?\b|\b\d+\s+passed\b",
    re.IGNORECASE)

# paths that don't count as real work product
NOISE_PREFIXES = (".claude/",)
NOISE_SUFFIXES = (".log", "settings.local.json")

MIN_PROMPT_LEN = 40      # skip the echo check for prompts shorter than this
ECHO_WINDOW = 400        # only sample the head of the prompt
ECHO_MIN_HITS = 3        # significant prompt words that must appear in the output
SIG_WORD_MIN_LEN = 6     # "significant" = longer than 5 chars


def _is_noise(path):
    p = path.strip()
    return p.startswith(NOISE_PREFIXES) or p.endswith(NOISE_SUFFIXES)


def _diff_numstat(repo, branch, base):
    """Rows of (added, deleted, path) for base...branch; [] if git fails."""
    try:
        out = subprocess.run(
            ["git", "diff", "--numstat", f"{base}...{branch}"],
            cwd=repo, capture_output=True, text=True, timeout=30)
        if out.returncode != 0:
            return []
        rows = []
        for line in (out.stdout or "").splitlines():
            parts = line.split("\t")
            if len(parts) != 3:
                continue
            a, d, path = parts
            added = int(a) if a.isdigit() else 0    # '-' for binary files
            deleted = int(d) if d.isdigit() else 0
            rows.append((added, deleted, path))
        return rows
    except Exception:
        return []


def _significant_words(text):
    """Lowercased words longer than 5 chars, deduped, order-preserving."""
    seen, words = set(), []
    for w in re.findall(r"[A-Za-z0-9_]+", (text or "").lower()):
        if len(w) >= SIG_WORD_MIN_LEN and w not in seen:
            seen.add(w)
            words.append(w)
    return words


def verify_session(task, output_text, repo, branch):
    """Deterministic verdict on whether a session did real work.

    Returns {"ok": bool, "reasons": [str], "diff_files": int, "diff_lines": int}.
    ok=True only if the diff is non-trivial, the output isn't a stall reply, and the
    output engages with the task prompt."""
    task = task or {}
    output_text = output_text or ""
    reasons = []
    ok = True

    # (a) real diff beyond noise paths
    base = task.get("base_branch") or "main"
    rows = _diff_numstat(repo, branch, base)
    real = [(a, d, p) for a, d, p in rows if not _is_noise(p)]
    diff_files = len(real)
    diff_lines = sum(a + d for a, d, _ in real)
    if diff_files == 0:
        ok = False
        reasons.append(f"no non-noise diff vs {base} (session produced no work product)")

    # (b) stall-phrase detection
    if STALL_RX.search(output_text):
        ok = False
        reasons.append("output matches a stall phrase — session received no instructions")

    # (c) prompt-echo: does the output engage with the actual task?
    prompt = (task.get("prompt") or "").strip()
    if len(prompt) >= MIN_PROMPT_LEN:
        words = _significant_words(prompt[:ECHO_WINDOW])
        needed = min(ECHO_MIN_HITS, len(words)) or 0
        if needed:
            out_lower = output_text.lower()
            hits = sum(1 for w in words if w in out_lower)
            if hits < needed:
                ok = False
                reasons.append(
                    f"prompt-echo failed: only {hits}/{needed} significant prompt words in output")

    # (d) bonus: output claims tests pass (informational, never required)
    if TESTS_PASS_RX.search(output_text):
        reasons.append("bonus: output reports tests passing")

    return {"ok": ok, "reasons": reasons, "diff_files": diff_files, "diff_lines": diff_lines}


def reinjection_prompt(task):
    """Retry prompt for a session that provably got no instructions: inline the FULL original
    prompt under an unmissable header so the next session cannot start blank."""
    task = task or {}
    prompt = task.get("prompt") or ""
    slug = task.get("slug") or "unknown-task"
    return (
        "YOUR TASK (previous session received no instructions — do this now):\n"
        "\n"
        f"{prompt}\n"
        "\n"
        f"Work on branch agent/{slug}. Make the changes, run the tests, and commit your work. "
        "Do NOT ask what to work on — the task above is your full assignment."
    )


if __name__ == "__main__":
    import json, sys
    # quick manual check: session_proof.py <repo> <branch> [base]
    repo = sys.argv[1] if len(sys.argv) > 1 else "."
    branch = sys.argv[2] if len(sys.argv) > 2 else "HEAD"
    base = sys.argv[3] if len(sys.argv) > 3 else "main"
    print(json.dumps(verify_session({"base_branch": base, "prompt": ""}, "", repo, branch), indent=2))
