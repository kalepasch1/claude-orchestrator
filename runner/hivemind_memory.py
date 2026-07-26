"""Cross-session, cross-project knowledge sharing.

When a task discovers a useful pattern, it's stored here. When a new
task starts, relevant patterns are recalled and injected as context.
Bridges the task execution layer to the organizational hivemind.
"""

import hashlib
import time
import logging
import re
from typing import List, Dict, Any, Optional

log = logging.getLogger(__name__)

# Import the project's existing db module
try:
    import db
except ImportError:
    db = None

TABLE = "hivemind_memory"

_SENSITIVE_PATTERNS = re.compile(
    r'(?:api[_-]?key|secret|password|token\s*=|bearer\s|private[_-]?key|'
    r'credential|supabase[_-]?service[_-]?role|SUPABASE_SERVICE_ROLE_KEY|'
    r'-----BEGIN)',
    re.I
)


def _contains_sensitive(text: str) -> bool:
    """Check if text contains sensitive credentials/keys."""
    return bool(_SENSITIVE_PATTERNS.search(text or ""))


def store(entry: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Store a reusable pattern. Returns the entry or None if blocked.

    Args:
        entry: Dict with keys: project_id, slug, pattern_type, summary,
               content (optional), file_context (optional), tags (optional),
               quality_score (optional), dag_id (optional)

    Returns:
        Inserted row dict or None if blocked/failed
    """
    if _contains_sensitive(entry.get("content", "")):
        log.warning("hivemind_memory: blocked sensitive content from %s/%s",
                    entry.get("project_id"), entry.get("slug"))
        return None
    if not db:
        log.warning("hivemind_memory: db not available, skipping store")
        return None

    row = {
        "project_id": entry["project_id"],
        "dag_id": entry.get("dag_id"),
        "slug": entry["slug"],
        "pattern_type": entry.get("pattern_type", "utility"),
        "summary": entry["summary"],
        "content": entry.get("content", ""),
        "file_context": entry.get("file_context"),
        "tags": entry.get("tags", []),
        "quality_score": entry.get("quality_score", 0.7),
        "reuse_count": 0,
        "promoted": False,
    }
    try:
        result = db.insert(TABLE, row)
        return result
    except Exception as e:
        log.error("hivemind_memory store failed: %s", e)
        return None


def recall(task: Dict[str, Any], limit: int = 5) -> List[Dict[str, Any]]:
    """Find relevant patterns for a task. Returns list of dicts.

    Scores patterns by:
    - Tag overlap with task tags (2.0x per tag)
    - Quality score (3.0x multiplier)
    - Reuse count (0.5x per use, capped at 10)
    - Cross-project preference (-1.0 for same project, +1.0 bonus)

    Args:
        task: Task dict with tags, project_id, slug, kind
        limit: Max patterns to return

    Returns:
        List of pattern dicts ranked by relevance
    """
    if not db:
        return []

    tags = task.get("tags", [])
    if not tags:
        tags = [task.get("slug", ""), task.get("kind", "")]
        tags = [t for t in tags if t]

    try:
        # Query patterns with any matching tags
        filters = {}
        if tags:
            # Note: actual implementation would use db.select with tag overlap
            # For now, this is a simplified query that the db module would support
            candidates = db.select(TABLE,
                filters={"tags": {"overlap": tags}},
                order="quality_score.desc",
                limit=limit * 4
            ) or []
        else:
            candidates = db.select(TABLE, order="quality_score.desc", limit=limit * 4) or []
    except Exception as e:
        log.error("hivemind_memory recall failed: %s", e)
        return []

    scored = []
    task_project = task.get("project_id", "")
    task_tags = set(tags)
    for c in candidates:
        score = 0.0
        tag_overlap = len(set(c.get("tags", [])) & task_tags)
        score += tag_overlap * 2.0
        score += c.get("quality_score", 0) * 3.0
        score += min(c.get("reuse_count", 0), 10) * 0.5

        # Prefer cross-project discoveries (more valuable)
        if c.get("project_id") == task_project:
            score -= 1.0
        else:
            score += 1.0

        scored.append((score, c))

    scored.sort(key=lambda x: -x[0])
    results = [c for _, c in scored[:limit]]

    # Increment reuse_count for returned patterns
    for r in results:
        try:
            db.update(TABLE, r["id"], {
                "reuse_count": (r.get("reuse_count", 0) + 1),
                "last_reused_at": "now()",
            })
        except Exception as e:
            log.warning("failed to increment reuse_count: %s", e)

    return results


def format_context(patterns: List[Dict[str, Any]]) -> str:
    """Format recalled patterns for prompt injection.

    Args:
        patterns: List of pattern dicts from recall()

    Returns:
        Formatted markdown string for prompt injection
    """
    if not patterns:
        return ""
    lines = ["\n--- HIVEMIND PATTERNS (proven solutions from across projects) ---"]
    for p in patterns:
        lines.append(f"\n[{p.get('project_id','?')}/{p.get('slug','?')}] "
                     f"{p.get('pattern_type','?')}: {p.get('summary','')}")
        qs = p.get('quality_score', 0)
        rc = p.get('reuse_count', 0)
        lines.append(f"  Quality: {qs:.0%} | Reused: {rc}x")
        content = p.get("content", "")
        if content and len(content) < 3000:
            lines.append(f"  Pattern:\n{content}")
    lines.append("\n--- END HIVEMIND PATTERNS ---\n")
    return "\n".join(lines)


def stats() -> Dict[str, Any]:
    """Get current hivemind statistics.

    Returns:
        Dict with total_patterns, promoted_to_hivemind, pending_promotion counts
    """
    if not db:
        return {}
    try:
        total = db.count(TABLE) or 0
        promoted = db.count(TABLE, {"promoted": True}) or 0
        return {
            "total_patterns": total,
            "promoted_to_hivemind": promoted,
            "pending_promotion": total - promoted,
        }
    except Exception as e:
        log.error("hivemind_memory stats failed: %s", e)
        return {}


def invalidate() -> None:
    """No-op for safety. Use DB operations directly to clear."""
    pass


def promote_pattern(pattern_id: str, promoted_by: str = "operator") -> bool:
    """Promote a pattern to official hivemind status.

    Args:
        pattern_id: UUID of pattern to promote
        promoted_by: Who promoted it

    Returns:
        True if successful
    """
    if not db:
        return False
    try:
        db.update(TABLE, pattern_id, {
            "promoted": True,
            "promoted_at": "now()",
        })
        return True
    except Exception as e:
        log.error("promote_pattern failed: %s", e)
        return False


def search(query: str, limit: int = 10) -> List[Dict[str, Any]]:
    """Search patterns by summary/content text.

    Args:
        query: Search string
        limit: Max results

    Returns:
        List of matching patterns
    """
    if not db:
        return []
    try:
        # Simple substring search in summary
        all_patterns = db.select(TABLE, order="quality_score.desc", limit=1000) or []
        query_lower = query.lower()
        results = [
            p for p in all_patterns
            if query_lower in p.get("summary", "").lower()
               or query_lower in p.get("content", "").lower()
        ][:limit]
        return results
    except Exception as e:
        log.error("hivemind_memory search failed: %s", e)
        return []
