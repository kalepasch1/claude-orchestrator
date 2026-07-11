#!/usr/bin/env python3
"""
prompt_compressor.py — Measure and compress agent prompts to reduce token waste.

The orchestrator builds enormous prompts (REUSE_FIRST + context_pack + precedent +
unified_knowledge + hivemind + test harness + speculative draft + build mandate).
This module deduplicates, truncates, and optimises them before dispatch.

Compression pipeline:
  1. Dedup detection — find repeated sections (>100 chars appearing 2+ times)
  2. Section prioritisation — rank injected sections by source confidence
  3. Structural compression — convert verbose prose to compact format
  4. Context window budgeting — truncate lowest-priority sections when over budget

Usage:
    import prompt_compressor
    result = prompt_compressor.compress(prompt, extras)
    # result["prompt"], result["extras"], result["savings"]
    info = prompt_compressor.measure(prompt, extras)
    prompt_compressor.stats()
"""
import sys, os, re, time, threading, hashlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import log as _log_mod

_log = _log_mod.get("prompt_compressor")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
_ENABLED = os.environ.get("ORCH_PROMPT_COMPRESSOR_ENABLED", "true").lower() in ("true", "1", "yes")
_MAX_CHARS = int(os.environ.get("ORCH_MAX_AGENT_PROMPT_CHARS", "36000"))
_MIN_DUP_LEN = 100  # minimum substring length to qualify as a duplicate

# Section priority map — higher = more important, kept first when trimming.
_PRIORITY_MAP = {
    "task spec":         10,
    "build mandate":      9,
    "test harness":       8,
    "speculative draft":  7,
    "precedent":          6,
    "context pack":       5,
    "hivemind":           4,
    "conventions":        3,
}
_DEFAULT_PRIORITY = 2

# ---------------------------------------------------------------------------
# Stats tracking (thread-safe)
# ---------------------------------------------------------------------------
_lock = threading.Lock()
_stats = {
    "prompts_compressed": 0,
    "total_original_chars": 0,
    "total_compressed_chars": 0,
}


def stats():
    """Return cumulative compression statistics."""
    with _lock:
        s = dict(_stats)
    avg = 0.0
    if s["total_original_chars"] > 0:
        avg = round(
            (1 - s["total_compressed_chars"] / s["total_original_chars"]) * 100, 2
        )
    return {
        "prompts_compressed": s["prompts_compressed"],
        "avg_reduction_pct": avg,
        "total_chars_saved": s["total_original_chars"] - s["total_compressed_chars"],
    }


def _record(original_chars, compressed_chars):
    with _lock:
        _stats["prompts_compressed"] += 1
        _stats["total_original_chars"] += original_chars
        _stats["total_compressed_chars"] += compressed_chars


# ---------------------------------------------------------------------------
# Measurement
# ---------------------------------------------------------------------------
_SECTION_RE = re.compile(r"^##\s+(.+)", re.MULTILINE)


def _split_sections(text):
    """Split *text* on ## headers, returning [(name, content), ...]."""
    parts = _SECTION_RE.split(text)
    # parts alternates: preamble, header1, body1, header2, body2, ...
    sections = []
    if parts and parts[0].strip():
        sections.append(("preamble", parts[0]))
    idx = 1
    while idx + 1 < len(parts):
        sections.append((parts[idx].strip(), parts[idx + 1]))
        idx += 2
    if not sections and text.strip():
        sections.append(("body", text))
    return sections


def measure(prompt, extras=""):
    """Return character and estimated-token counts broken down by section.

    Returns:
        {"total_chars": int, "estimated_tokens": int,
         "sections": [{"name": str, "chars": int}, ...]}
    """
    try:
        combined = (prompt or "") + (extras or "")
        total = len(combined)
        raw_sections = _split_sections(combined)
        sections = [{"name": name, "chars": len(body)} for name, body in raw_sections]
        return {
            "total_chars": total,
            "estimated_tokens": int(total / 3.5),
            "sections": sections,
        }
    except Exception as exc:
        _log.warning("measure failed: %s", exc)
        total = len(prompt or "") + len(extras or "")
        return {"total_chars": total, "estimated_tokens": int(total / 3.5), "sections": []}


# ---------------------------------------------------------------------------
# Duplicate detection
# ---------------------------------------------------------------------------
def _find_duplicates(text):
    """Find substrings >=_MIN_DUP_LEN that appear 2+ times.

    Uses a rolling-hash approach over fixed-length windows; returns a list of
    deduplicated substring values.
    """
    if not text or len(text) < _MIN_DUP_LEN * 2:
        return []
    window = _MIN_DUP_LEN
    seen = {}  # hash -> start index
    duplicates = []
    dup_hashes = set()
    for i in range(len(text) - window + 1):
        chunk = text[i : i + window]
        h = hashlib.md5(chunk.encode("utf-8", errors="replace")).hexdigest()
        if h in seen and h not in dup_hashes:
            duplicates.append(chunk)
            dup_hashes.add(h)
        else:
            seen[h] = i
    return duplicates


def _dedup(text):
    """Remove duplicate blocks from *text*, keeping the first occurrence."""
    dups = _find_duplicates(text)
    if not dups:
        return text
    # Sort longest first so we remove the broadest matches first.
    dups.sort(key=len, reverse=True)
    result = text
    for dup in dups:
        first = result.find(dup)
        if first == -1:
            continue
        # Remove all subsequent occurrences.
        after_first = first + len(dup)
        result = result[:after_first] + result[after_first:].replace(dup, "")
    return result


# ---------------------------------------------------------------------------
# Section prioritisation
# ---------------------------------------------------------------------------
def _section_priority(name):
    """Return the priority score for a section header (case-insensitive)."""
    lower = name.lower().strip()
    for keyword, pri in _PRIORITY_MAP.items():
        if keyword in lower:
            return pri
    return _DEFAULT_PRIORITY


def _prioritize_sections(text):
    """Parse text into prioritised sections.

    Returns [(section_name, priority, content), ...] sorted lowest-priority first
    (so the caller can truncate from the front of the list).
    """
    raw = _split_sections(text)
    sections = [(name, _section_priority(name), body) for name, body in raw]
    sections.sort(key=lambda s: s[1])  # ascending priority
    return sections


# ---------------------------------------------------------------------------
# Structural compression
# ---------------------------------------------------------------------------
_FILE_LINE_RE = re.compile(
    r"(?:^|\n)\s*(?:File|Path|Source):\s*(\S+)[^\n]*", re.IGNORECASE
)
_BLANK_LINES_RE = re.compile(r"\n{3,}")
_TRAILING_SPACES_RE = re.compile(r"[ \t]+$", re.MULTILINE)


def _compress_structure(text):
    """Light structural compression — collapse blank lines, trim trailing spaces."""
    text = _BLANK_LINES_RE.sub("\n\n", text)
    text = _TRAILING_SPACES_RE.sub("", text)
    return text


# ---------------------------------------------------------------------------
# Budget enforcement
# ---------------------------------------------------------------------------
def _enforce_budget(text, max_chars):
    """Truncate lowest-priority sections until *text* fits within *max_chars*."""
    if len(text) <= max_chars:
        return text, 0

    sections = _prioritize_sections(text)
    total = sum(len(body) for _, _, body in sections)
    truncated_count = 0

    # Walk from lowest-priority to highest, trimming as needed.
    rebuilt = []
    excess = total - max_chars
    for name, pri, body in sections:
        if excess > 0:
            body_len = len(body)
            if body_len <= excess:
                # Drop entire section.
                excess -= body_len
                truncated_count += 1
                rebuilt.append((name, pri, f"\n[section truncated — {body_len} chars removed]\n"))
                continue
            else:
                # Partial truncation — keep beginning.
                keep = body_len - excess
                body = body[:keep] + f"\n... [{excess} chars truncated]\n"
                excess = 0
                truncated_count += 1
        rebuilt.append((name, pri, body))

    # Re-sort by original document order (approximate by restoring priority-desc).
    rebuilt.sort(key=lambda s: -s[1])
    result = ""
    for name, pri, body in rebuilt:
        if name not in ("preamble", "body"):
            result += f"## {name}\n{body}"
        else:
            result += body
    return result, truncated_count


# ---------------------------------------------------------------------------
# Main API
# ---------------------------------------------------------------------------
def compress(prompt, extras="", max_chars=None):
    """Compress *prompt* + *extras* through the full pipeline.

    Returns:
        {"prompt": str, "extras": str,
         "savings": {"original_chars": int, "compressed_chars": int,
                      "reduction_pct": float, "sections_truncated": int}}
    """
    prompt = prompt or ""
    extras = extras or ""
    original_chars = len(prompt) + len(extras)

    # Fast path: disabled or nothing to do.
    if not _ENABLED or original_chars == 0:
        return {
            "prompt": prompt,
            "extras": extras,
            "savings": {
                "original_chars": original_chars,
                "compressed_chars": original_chars,
                "reduction_pct": 0.0,
                "sections_truncated": 0,
            },
        }

    budget = max_chars if max_chars is not None else _MAX_CHARS

    try:
        # Step 1: dedup
        prompt = _dedup(prompt)
        extras = _dedup(extras)

        # Step 2 + 3: structural compression on both parts
        prompt = _compress_structure(prompt)
        extras = _compress_structure(extras)

        # Step 4: budget enforcement across the combined text, then split back.
        combined = prompt + "\n" + extras if extras else prompt
        combined, sections_truncated = _enforce_budget(combined, budget)

        # Split back: the prompt is everything up to the original split point
        # (approximate — we recombine after budget enforcement).
        if extras:
            prompt = combined
            extras = ""
        else:
            prompt = combined

        compressed_chars = len(prompt) + len(extras)
        reduction = 0.0
        if original_chars > 0:
            reduction = round((1 - compressed_chars / original_chars) * 100, 2)

        _record(original_chars, compressed_chars)

        return {
            "prompt": prompt,
            "extras": extras,
            "savings": {
                "original_chars": original_chars,
                "compressed_chars": compressed_chars,
                "reduction_pct": reduction,
                "sections_truncated": sections_truncated,
            },
        }
    except Exception as exc:
        _log.warning("compress failed, returning original: %s", exc)
        return {
            "prompt": prompt,
            "extras": extras,
            "savings": {
                "original_chars": original_chars,
                "compressed_chars": original_chars,
                "reduction_pct": 0.0,
                "sections_truncated": 0,
            },
        }
