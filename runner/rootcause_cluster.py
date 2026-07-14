"""
rootcause_cluster.py - Cluster BLOCKED/regression failures into named patterns.
For each recurring pattern, auto-generate a guard rule so that class of failure
is solved once, forever.
"""
import re
import hashlib
from dataclasses import dataclass, field
from collections import defaultdict


@dataclass
class FailureRecord:
    task_id: str
    slug: str
    state: str
    note: str
    error_signature: str = ""
    def __post_init__(self):
        if not self.error_signature:
            self.error_signature = extract_signature(self.note)


@dataclass
class FailureCluster:
    pattern_id: str
    pattern_name: str
    signature: str
    records: list = field(default_factory=list)
    guard_rule: str = ""
    @property
    def count(self):
        return len(self.records)
    @property
    def is_recurring(self):
        return self.count >= 2


KNOWN_PATTERNS = [
    (r"capacity circuit.*call cap", "capacity-exhaustion"),
    (r"Not logged in.*Please run /login", "auth-not-logged-in"),
    (r"HTTP Error 409.*Conflict", "git-conflict-409"),
    (r"no spec|no real specification|no actionable", "missing-spec"),
    (r"PATCH TEMPLATE.*[0-9a-f]{6,}", "patch-template-corrupt"),
    (r"budget guard|spend limit", "budget-guard"),
    (r"shelved after \d+ remediations", "remediation-cap"),
    (r"FileNotFoundError.*No such file", "file-not-found"),
    (r"ModuleNotFoundError", "module-not-found"),
    (r"TypeError|AttributeError", "type-error"),
    (r"test.*fail|tests fail", "test-failure"),
    (r"build.*fail|production build red", "build-failure"),
    (r"Prisma.*schema|migration", "prisma-schema"),
    (r"index\.lock.*File exists", "git-index-lock"),
    (r"orphaned-running|stuck RUNNING", "orphaned-task"),
]


def extract_signature(note):
    if not note:
        return "unknown"
    for pattern, name in KNOWN_PATTERNS:
        if re.search(pattern, note, re.IGNORECASE):
            return name
    return "unknown-" + hashlib.sha256(note[:200].encode()).hexdigest()[:8]


GUARD_RULES = {
    "capacity-exhaustion": "pre_check: verify API capacity before claiming task; back off 60s on 429/capacity errors",
    "auth-not-logged-in": "pre_check: validate auth token before spawning agent; refresh token if expired",
    "git-conflict-409": "pre_check: fetch + rebase before push; retry with fresh branch on 409",
    "missing-spec": "pre_check: reject tasks where prompt contains only error messages and no specification",
    "patch-template-corrupt": "pre_check: quarantine tasks whose prompt starts with PATCH TEMPLATE + hex hashes",
    "budget-guard": "pre_check: check remaining budget before claiming; skip if < min_cost_estimate",
    "remediation-cap": "post_check: after 3 failed remediations, shelve task and notify human",
    "file-not-found": "pre_check: verify all referenced files exist before running agent",
    "module-not-found": "pre_check: verify imports resolve; run pip install if requirements.txt present",
    "type-error": "post_check: run type checker (mypy/pyright) before committing",
    "test-failure": "post_check: run test suite before marking DONE; revert on failure",
    "build-failure": "post_check: run production build before marking DONE; fix or revert",
    "prisma-schema": "pre_check: validate prisma schema (npx prisma validate) before migration",
    "git-index-lock": "pre_check: rm -f .git/index.lock before any git operation",
    "orphaned-task": "janitor: detect tasks RUNNING > 2h with no recent commits; reset to QUEUED",
}


def generate_guard_rule(signature):
    return GUARD_RULES.get(signature, f"manual_review: unknown pattern '{signature}' -- needs human triage")


def cluster_failures(records):
    groups = defaultdict(list)
    for rec in records:
        groups[rec.error_signature].append(rec)
    clusters = []
    for sig, recs in sorted(groups.items(), key=lambda x: -len(x[1])):
        cluster = FailureCluster(
            pattern_id=hashlib.sha256(sig.encode()).hexdigest()[:12],
            pattern_name=sig,
            signature=sig,
            records=recs,
            guard_rule=generate_guard_rule(sig),
        )
        clusters.append(cluster)
    return clusters


def get_recurring_patterns(clusters):
    return [c for c in clusters if c.is_recurring]
