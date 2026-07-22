"""Task splitter: splits large recovery tasks into smaller sub-tasks.

Provides heuristics-based decomposition of task descriptions into
independently-buildable sub-tasks based on size and complexity signals.
"""

import re
from typing import List, Dict, Any


def estimate_complexity(description: str) -> str:
    """Estimate task complexity from description text.

    Returns 'low', 'medium', or 'high'.
    """
    if not description or not isinstance(description, str):
        return "low"
    words = description.split()
    word_count = len(words)
    # Complexity signals
    keywords_high = ["refactor", "migrate", "rewrite", "redesign", "overhaul", "integrate"]
    keywords_med = ["add", "implement", "create", "update", "extend", "modify"]
    score = 0
    lower = description.lower()
    for kw in keywords_high:
        if kw in lower:
            score += 3
    for kw in keywords_med:
        if kw in lower:
            score += 1
    if word_count > 100:
        score += 2
    elif word_count > 50:
        score += 1
    # Count distinct file references
    file_refs = len(re.findall(r'\b\w+\.\w{1,4}\b', description))
    if file_refs > 5:
        score += 2
    elif file_refs > 2:
        score += 1
    if score >= 5:
        return "high"
    elif score >= 2:
        return "medium"
    return "low"


def split_task(description: str, max_subtasks: int = 6) -> List[Dict[str, Any]]:
    """Split a task description into independently-buildable sub-tasks.

    Args:
        description: Full task description text.
        max_subtasks: Maximum number of sub-tasks to produce.

    Returns:
        List of dicts with keys: title, description, complexity, order.
    """
    if not description or not isinstance(description, str):
        return []
    description = description.strip()
    if not description:
        return []

    complexity = estimate_complexity(description)
    # Split by sentence boundaries or bullet points
    segments = re.split(r'(?<=[.!?])\s+|[\n\r]+[-*]\s*|[\n\r]{2,}', description)
    segments = [s.strip() for s in segments if s.strip() and len(s.strip()) > 5]
    if not segments:
        segments = [description]
    # Group small segments together, split large ones
    subtasks = []
    if complexity == "low" or len(segments) <= 1:
        subtasks.append({
            "title": _extract_title(description),
            "description": description,
            "complexity": complexity,
            "order": 1,
        })
    else:
        # Chunk segments into subtasks respecting max_subtasks
        chunk_size = max(1, len(segments) // max_subtasks)
        for i in range(0, len(segments), chunk_size):
            chunk = segments[i:i + chunk_size]
            if len(subtasks) >= max_subtasks:
                subtasks[-1]["description"] += " " + " ".join(chunk)
                continue
            text = " ".join(chunk)
            subtasks.append({
                "title": _extract_title(text),
                "description": text,
                "complexity": estimate_complexity(text),
                "order": len(subtasks) + 1,
            })
    return subtasks


def _extract_title(text: str, max_len: int = 60) -> str:
    """Extract a short title from the first meaningful phrase."""
    if not text:
        return "Untitled"
    # Take first sentence or first N chars
    first = re.split(r'[.!?\n]', text)[0].strip()
    if len(first) > max_len:
        first = first[:max_len].rsplit(' ', 1)[0] + "..."
    return first if first else "Untitled"


if __name__ == "__main__":
    sample = ("Refactor the authentication module to use JWT tokens. "
              "Add rate limiting middleware. "
              "Create integration tests for all auth endpoints. "
              "Update the API documentation.")
    for st in split_task(sample):
        print(f"  [{st['order']}] {st['title']} ({st['complexity']})")
