#!/usr/bin/env python3
"""Aggregate the real reasons agent runs finish without a diff."""
import os, re, sys, collections, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

HOURS = float(os.environ.get("DIAG_HOURS", "6"))
since = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=HOURS)).isoformat()
rows = db.select("tasks", {
    "select": "slug,state,note,log_tail,remediation_count,force_coder,model,updated_at",
    "note": "like.agentic-repair:*",
    "updated_at": "gte." + since,
    "order": "updated_at.desc",
    "limit": "1000",
}) or []
print("tasks with any agentic-repair note in last %sh: %d\n" % (HOURS, len(rows)))

SIGS = [
    ("cli-not-installed",      r"No such file or directory: '(claude|codex|ollama|gemini)'"),
    ("python-nameerror",       r"NameError: name '([\w]+)' is not defined"),
    ("python-importerror",     r"(ModuleNotFoundError|ImportError): "),
    ("usage-limit",            r"(usage limit|rate.?limit|429|quota)"),
    ("auth",                   r"(401|403|unauthorized|invalid api key|authentication)"),
    ("timeout",               r"(TimeoutExpired|timed out)"),
    ("oom-killed",             r"(Killed|signal 9|exit code 137|MemoryError)"),
    ("worktree-git",           r"(fatal: |git .*failed|worktree)"),
    ("no-changes-made",        r"(no changes|nothing to commit|made no file changes|empty diff)"),
    ("already-integrated",     r"existing committed branch"),
    ("empty",                  r"^$"),
]

def sig(tail):
    t = str(tail or "").strip()
    if not t:
        return "empty-log-tail"
    for name, pat in SIGS:
        if re.search(pat, t, re.I | re.M):
            return name
    return "other: " + re.sub(r"\s+", " ", t.strip().splitlines()[-1])[:70]

cat = collections.Counter()
sigs = collections.Counter()
pairs = collections.Counter()
examples = {}
for r in rows:
    c = str(r.get("note") or "").split(":", 1)[-1].split()[0]
    s = sig(r.get("log_tail"))
    cat[c] += 1
    sigs[s] += 1
    pairs[(c, s)] += 1
    examples.setdefault(s, r)

print("repair category:")
for k, n in cat.most_common(10):
    print("  %5d  %s" % (n, k))

print("\nfailure signature (why no diff):")
for k, n in sigs.most_common(20):
    print("  %5d  %s" % (n, k))

print("\ntop category x signature:")
for (c, s), n in pairs.most_common(15):
    print("  %5d  %-16s %s" % (n, c, s))

print("\nrepresentative slug per top signature:")
for k, _ in sigs.most_common(8):
    r = examples[k]
    print("  %-24s %-52s coder=%s rc=%s" % (k[:24], (r.get("slug") or "")[:52],
                                            r.get("force_coder") or r.get("model"),
                                            r.get("remediation_count")))
