#!/usr/bin/env python3
"""
context_retrieval.py - the biggest realistic token lever. Instead of letting the agent
load the whole repo, pick only the files a task likely needs (by path + content keyword
overlap, ripgrep-powered) and tell it to focus there. Typically cuts input tokens 5-10x.

select_files(repo, prompt) -> [paths]   focus_note(repo, prompt) -> str to prepend
Dependency-free (uses git + rg/grep). Embeddings can be swapped in later for ranking.
"""
import os, sys, subprocess, re
from collections import Counter
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import knowledge as kw

CODE_EXT = (".ts", ".tsx", ".js", ".vue", ".py", ".go", ".rs", ".java", ".sql", ".md")
MAX_FILES = int(os.environ.get("CONTEXT_MAX_FILES", "12"))


def _tracked(repo):
    try:
        out = subprocess.check_output(["git", "ls-files"], cwd=repo, text=True)
        return [f for f in out.splitlines() if f.endswith(CODE_EXT)]
    except Exception:
        return []


def _grep_hits(repo, terms):
    hits = Counter()
    for term in terms[:8]:
        if len(term) < 4:
            continue
        try:
            out = subprocess.run(["rg", "-l", "-i", "--max-count", "1", term],
                                 cwd=repo, capture_output=True, text=True, timeout=20)
            for f in out.stdout.splitlines():
                if f.endswith(CODE_EXT):
                    hits[f] += 2
        except Exception:
            pass
    return hits


def select_files(repo, prompt):
    terms = [t for t in kw.toks(prompt) if len(t) > 3]
    files = _tracked(repo)
    score = _grep_hits(repo, terms)                     # content matches (strong)
    tset = set(terms)
    for f in files:                                     # path matches (weak)
        toks = set(re.split(r"[/_.-]", f.lower()))
        score[f] += len(tset & toks)
    ranked = [f for f, s in score.most_common(MAX_FILES) if s > 0]
    return ranked


def focus_note(repo, prompt):
    files = select_files(repo, prompt)
    if not files:
        return ""
    return ("# Focus: this task most likely involves these files - read THESE first and "
            "avoid loading the whole repo (saves tokens):\n" +
            "\n".join(f"- {f}" for f in files) + "\n\n")


if __name__ == "__main__":
    r = sys.argv[1] if len(sys.argv) > 1 else "."
    print(focus_note(r, sys.argv[2] if len(sys.argv) > 2 else "fix the settlement allowlist"))
