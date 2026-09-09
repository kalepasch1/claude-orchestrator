#!/usr/bin/env python3
"""
diff_fleet_sync.py - Bridge between merged-diff memory and fleet coordination.

Connects two previously independent systems:
1. The stored diff data structure (merged_diff_memory.json) that tracks merge metadata
2. The fleet coordination layer (fleet_config table) that shares state across machines

On each run:
- Reads the local merged-diff memory (the JSON metadata file)
- Extracts a compact digest of recent patterns (branches, file areas, conventions)
- Publishes the digest to fleet_config so other machines can consume it
- Reads digests published by other hosts and merges novel patterns into local memory

Fail-soft throughout: errors are logged, never raised. A broken fleet sync must not
wedge the runner or block local pattern capture.
"""
import json
import logging
import os
import socket
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logger = logging.getLogger(__name__)

HOST = socket.gethostname()

# Config key prefix. fleet_control.py only applies ORCH_-prefixed keys.
FLEET_KEY_PREFIX = "ORCH_DIFF_DIGEST"
MAX_DIGEST_BRANCHES = 20
MAX_DIGEST_AREAS = 15


def _import_db():
    """Lazy import so a broken db module cannot wedge the import chain."""
    try:
        import db
        return db
    except Exception:
        return None


def _import_merged_diff_memory():
    try:
        import merged_diff_memory
        return merged_diff_memory
    except Exception:
        return None


def _build_digest(merges: list[dict]) -> dict:
    """Compact digest of recent merge metadata for fleet sharing.

    Shape kept small — this goes into a single fleet_config row as JSON.
    Includes: host, timestamp, branch names, top file areas, merge count.
    """
    branches = []
    area_counts: dict[str, int] = {}

    for m in merges:
        branch = m.get("branch") or m.get("branch_name") or ""
        if branch:
            branches.append(branch)
        files = m.get("files_affected") or m.get("files_changed") or []
        for f in files:
            if isinstance(f, str) and "/" in f:
                area = f.split("/", 1)[0]
                area_counts[area] = area_counts.get(area, 0) + 1

    top_areas = sorted(area_counts, key=area_counts.get, reverse=True)[:MAX_DIGEST_AREAS]
    return {
        "host": HOST,
        "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "merge_count": len(merges),
        "branches": branches[:MAX_DIGEST_BRANCHES],
        "top_areas": top_areas,
    }


def publish_digest() -> bool:
    """Read local merged-diff memory, publish digest to fleet_config.

    Returns True if the digest was persisted, False on any error.
    Uses db.upsert("fleet_config", ...) — the same API fleet_control.py uses.
    """
    try:
        mdm = _import_merged_diff_memory()
        if mdm is None:
            logger.warning("diff_fleet_sync: cannot import merged_diff_memory")
            return False

        merges = mdm.get_recent_merges(limit=MAX_DIGEST_BRANCHES)
        if not merges:
            return False

        digest = _build_digest(merges)
        db_mod = _import_db()
        if db_mod is None:
            logger.warning("diff_fleet_sync: cannot import db")
            return False

        key = f"{FLEET_KEY_PREFIX}_{HOST}"
        db_mod.upsert("fleet_config", {"key": key, "value": json.dumps(digest)})
        return True
    except Exception as e:
        logger.warning("diff_fleet_sync: publish failed: %s", e)
        return False


def consume_fleet_digests() -> list[dict]:
    """Read digests published by OTHER hosts from fleet_config.

    Does not modify local memory — caller decides what to do with the results.
    Returns a list of digest dicts from other hosts, [] on any error.
    """
    try:
        db_mod = _import_db()
        if db_mod is None:
            return []

        rows = db_mod.select("fleet_config", {
            "select": "key,value",
            "key": f"like.{FLEET_KEY_PREFIX}%",
        })
        if not rows:
            return []

        results = []
        for row in rows:
            try:
                val = row.get("value", "")
                if isinstance(val, str):
                    digest = json.loads(val)
                elif isinstance(val, dict):
                    digest = val
                else:
                    continue
                if digest.get("host") != HOST:
                    results.append(digest)
            except (json.JSONDecodeError, TypeError):
                continue
        return results
    except Exception as e:
        logger.warning("diff_fleet_sync: consume failed: %s", e)
        return []


def sync(repo: str = ".") -> dict:
    """Full sync cycle: publish local digest, consume remote digests.

    Called by periodic.py after capture_to_memory(). Returns a summary dict.
    Fail-soft: always returns a dict, never raises.
    """
    result = {
        "published": False,
        "remote_digests": 0,
        "novel_branches": [],
        "error": None,
    }
    try:
        result["published"] = publish_digest()

        remote = consume_fleet_digests()
        result["remote_digests"] = len(remote)

        # Identify branches seen on other hosts but not in local memory
        mdm = _import_merged_diff_memory()
        local_branches = set()
        if mdm:
            for m in mdm.get_recent_merges(limit=50):
                b = m.get("branch") or m.get("branch_name") or ""
                if b:
                    local_branches.add(b)

        novel = []
        for digest in remote:
            for b in digest.get("branches", []):
                if b and b not in local_branches:
                    novel.append(b)
        result["novel_branches"] = novel[:20]

    except Exception as e:
        result["error"] = str(e)
        logger.warning("diff_fleet_sync: sync error: %s", e)

    return result


def stats() -> dict:
    """Introspection for operators. Fail-soft."""
    try:
        return {
            "host": HOST,
            "fleet_key_prefix": FLEET_KEY_PREFIX,
            "remote_digests": len(consume_fleet_digests()),
        }
    except Exception:
        return {"host": HOST, "error": "stats unavailable"}
