"""Bounded, content-free classification of *reported* Consilium job outcomes.

A zero exit is execution success, not evidence of persistence, customer absorption,
legal quality, or business value. Never promote these receipts to those claims.
"""
import json
import re

MAX_SUMMARY_CHARS = 65536
MAX_CANDIDATES = 128
# Output counters, work counters, activity counters. Only these numeric fields escape.
SCHEMAS = {
    "legal_docket": (("cards_minted", "seeded"), (), ("convened",)),
    "publication_commission": ((), ("reviewed",), ("reviewed",)),
    "paper_drafter": (("drafted",), (), ("candidates",)),
    "expert_corps": (("claims", "spawned"), ("evolved", "retired"), ("researched",)),
    "corpus_forecaster": (("added",), (), ()),
    "theory_lab": ((), ("positions.resolved", "claims.checked"), ("positions.groups",)),
    "ambiguity_miner": (("docketed", "mined_findings"), ("reviewed",), ("docs",)),
    "reg_opportunity_scan": (("opportunities", "docketed"), (), ()),
    "card_freshness": ((), ("stale_marked",), ("scanned_cards", "would_stale")),
    "benchmark_ingest": (("ingested",), (), ("considered",)),
    "corpus_index": (("added",), (), ("skipped",)),
}


def _get(obj, path):
    for key in path.split("."):
        obj = obj.get(key) if isinstance(obj, dict) else None
    return obj


def _count(value):
    return type(value) is int and 0 <= value <= 1_000_000_000


def classify_outcome(job, stdout, rc):
    """Parse only known top-level summaries; never retain child text or nested results."""
    base = {"execution_success": rc == 0, "absorption": "unverified",
            "value": "unverified", "evidence": "job_summary", "counters": {}}
    if rc != 0:
        return {**base, "status": "failed", "reason": "execution_failed"}
    if job not in SCHEMAS or not isinstance(stdout, str):
        return {**base, "status": "unverified", "reason": "summary_unavailable"}
    bounded = stdout[-MAX_SUMMARY_CHARS:]
    # If clipped, discard the first incomplete line rather than treating it as a receipt.
    if len(stdout) > MAX_SUMMARY_CHARS:
        bounded = bounded.partition("\n")[2]
    starts = list(re.finditer(r"(?m)^(?:" + re.escape(job) + r": )?\{", bounded))[-MAX_CANDIDATES:]
    decoder = json.JSONDecoder()
    summary = None
    paths = sum(SCHEMAS[job], ())
    for match in starts:
        try:
            candidate, _ = decoder.raw_decode(bounded, bounded.index("{", match.start()))
        except (ValueError, RecursionError):
            continue
        if isinstance(candidate, dict) and (any(_get(candidate, k) is not None for k in paths)
                                           or isinstance(candidate.get("skipped"), str)):
            summary = candidate
    if summary is None:
        return {**base, "status": "unverified", "reason": "summary_unavailable"}
    counters = {k: _get(summary, k) for k in paths if _count(_get(summary, k))}
    base["counters"] = counters
    if any(_get(summary, k) is not None and not _count(_get(summary, k)) for k in paths):
        return {**base, "status": "unverified", "reason": "invalid_summary_counts"}
    skipped = [summary.get("skipped")]
    if job == "theory_lab":
        skipped += [_get(summary, "positions.skipped"), _get(summary, "claims.skipped")]
    unavailable = any(isinstance(v, str) and v and v != "already ran today" for v in skipped)
    unavailable |= any(_count(summary.get(k)) and summary[k] > 0
                       for k in ("left_pending", "skipped_budget", "unavailable", "deferred", "deferred_docs"))
    unavailable |= summary.get("status") == "deferred"
    produced = sum(counters.get(k, 0) for k in SCHEMAS[job][0])
    work = sum(counters.get(k, 0) for k in SCHEMAS[job][1])
    if (summary.get("error") or summary.get("errors") or summary.get("status") == "failed"
            or (_count(summary.get("persist_failed")) and summary["persist_failed"] > 0)):
        return {**base, "status": "failed", "deferred": True,
                "partial": bool(produced or work), "reason": "job_reported_failure"}
    if unavailable:
        return {**base, "status": "deferred", "deferred": True,
                "partial": bool(produced or work), "reason": "job_reported_unavailable"}
    if any(v == "already ran today" for v in skipped) or summary.get("dry_run") is True:
        return {**base, "status": "no_work", "reason": "already_done_or_dry_run"}
    if produced or work:
        return {**base, "status": "produced" if produced else "work_done",
                "reason": "reported_output_not_verified_absorption"}
    if not counters:
        return {**base, "status": "unverified", "reason": "summary_unavailable"}
    # Successful scans may legitimately find no changes. Generation attempts with
    # no reported output remain unverified, not a productive completion.
    no_work = not any(counters.values()) or job in ("card_freshness", "corpus_index") or summary.get("status") == "noop"
    return {**base, "status": "no_work" if no_work else "unverified",
            "reason": "no_reported_output"}
