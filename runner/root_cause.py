#!/usr/bin/env python3
"""
root_cause.py — Autonomous root cause analysis for task failures.

Analyzes failure patterns across tasks to identify systemic issues:
- Repeated failures on the same file/module
- Build failures correlated with specific dependencies
- Test failures linked to environment issues
- Capacity-related failures (timeouts, rate limits)
"""
import os, sys, re, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import provider_banner

# Common failure pattern classifiers
PATTERNS = {
    "missing_dep": re.compile(r"Cannot find (module|package)|Module not found|No module named", re.I),
    "type_error": re.compile(r"TS\d{4}|TypeError|type.*not assignable|Property.*does not exist", re.I),
    "build_timeout": re.compile(r"timeout|timed out|ETIMEDOUT|deadline exceeded", re.I),
    # Was a local regex that knew "weekly limit" but none of the dozen other
    # banner phrases runner.py already handled ("5-hour limit", "spend limit",
    # "raise it at claude.ai"), so an exhaustion the runner classified
    # correctly came back "unknown" from the analyzer reading the same note.
    # `exhausted` is split out because it is a different remedy: rate limits
    # want backoff, exhaustion wants a different account.
    "rate_limit": provider_banner.RATE_LIMIT_RX,
    "exhausted": provider_banner.EXHAUSTED_RX,
    "auth_failure": re.compile(r"401|403|authentication|unauthorized|PAT.*lacks|token.*expired", re.I),
    "merge_conflict": re.compile(r"conflict|CONFLICT|cannot merge|rebase.*fail", re.I),
    "disk_space": re.compile(r"no space|ENOSPC|disk full", re.I),
    "missing_branch": re.compile(r"missing.branch|branch.*not found|refname.*not found", re.I),
}


def classify_failure(note_or_prompt):
    """Classify a failure string into root cause categories.

    Returns list of (category, confidence) tuples, sorted by confidence.
    """
    text = str(note_or_prompt or "")[:5000]
    matches = []
    for category, pattern in PATTERNS.items():
        hits = pattern.findall(text)
        if hits:
            confidence = min(0.9, 0.5 + 0.1 * len(hits))
            matches.append((category, confidence))
    matches.sort(key=lambda x: -x[1])
    return matches or [("unknown", 0.3)]


def analyze_batch(tasks):
    """Analyze a batch of failed/quarantined tasks for systemic patterns.

    Returns dict with:
        top_causes: list of (cause, count)
        affected_projects: dict of project -> cause counts
        recommendations: list of actionable recommendations
    """
    cause_counts = collections.Counter()
    project_causes = collections.defaultdict(lambda: collections.Counter())

    for t in tasks:
        text = f"{t.get('note', '')} {t.get('prompt', '')}"
        causes = classify_failure(text)
        project = t.get("project_name", t.get("project_id", "unknown"))
        for cause, conf in causes:
            if conf >= 0.5:
                cause_counts[cause] += 1
                project_causes[project][cause] += 1

    recommendations = []
    if cause_counts.get("rate_limit", 0) >= 3:
        recommendations.append("Multiple rate-limit failures — consider reducing concurrency or adding account rotation")
    # Distinct remedy from rate_limit: lowering concurrency does not refill an
    # exhausted account, and these used to be reported as one bucket (when they
    # were recognised at all), so the advice was wrong half the time.
    if cause_counts.get("exhausted", 0) >= 3:
        recommendations.append("Provider budget exhausted, not throttled — rotate to another account "
                               "or wait for the stated reset; reducing concurrency will not help")
    if cause_counts.get("missing_dep", 0) >= 3:
        recommendations.append("Repeated missing dependency errors — run `npm install` or check package.json")
    if cause_counts.get("auth_failure", 0) >= 2:
        recommendations.append("Auth failures detected — verify PAT and API keys in fleet_config")
    if cause_counts.get("merge_conflict", 0) >= 5:
        recommendations.append("High conflict rate — consider rebasing agent branches more frequently")
    if cause_counts.get("missing_branch", 0) >= 5:
        recommendations.append("Many missing branches — run branch_recovery.batch_recover()")
    if cause_counts.get("type_error", 0) >= 3:
        recommendations.append("Repeated TypeScript errors — check for breaking type changes on base branch")

    return {
        "top_causes": cause_counts.most_common(10),
        "affected_projects": {p: dict(c) for p, c in project_causes.items()},
        "recommendations": recommendations,
        "total_analyzed": len(tasks),
    }
