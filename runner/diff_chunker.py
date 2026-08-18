#!/usr/bin/env python3
"""
diff_chunker.py - Split large unified diffs into bounded chunks and process them
with a retry loop that emits partial results.

Why this exists: merged-diff-memory runs fed a whole merge diff to a model in a
single turn. Anything past a few hundred lines blew the turn budget
(``error_max_turns`` after 2 turns) and the *entire* diff was lost -- no partial
capture, no memory write. Chunking bounds each unit of work below the turn
budget and ``process_diff_chunked`` keeps whatever succeeded even when a later
chunk fails.

Fail-soft by convention (see CLAUDE.md): bad input returns an empty result
rather than raising, and a broad catch always logs a diagnostic before it
swallows.
"""
import logging
import os

logger = logging.getLogger(__name__)

# Chunk ceiling. Kept an ORCH_-prefixed env var so it is fleet-pushable via
# fleet_control.py without a code change.
MAX_CHUNK_LINES = int(os.environ.get("ORCH_DIFF_CHUNK_MAX_LINES", "500"))

# How many times a single chunk is retried before it is recorded as failed.
MAX_CHUNK_RETRIES = int(os.environ.get("ORCH_DIFF_CHUNK_MAX_RETRIES", "3"))

_FILE_HEADER = "diff --git "


def split_diff_by_file(diff_text):
    """Split a unified diff into one string per file.

    Returns [] on empty/None input. Text before the first ``diff --git`` header
    (commit message preamble, for example) is kept as its own leading section so
    nothing is silently dropped.
    """
    if not diff_text:
        return []
    try:
        lines = diff_text.splitlines(keepends=True)
    except Exception as exc:  # non-str input
        logger.warning("diff_chunker: unsplittable diff input (%s); returning []", exc)
        return []

    sections = []
    current = []
    for line in lines:
        if line.startswith(_FILE_HEADER) and current:
            sections.append("".join(current))
            current = [line]
        else:
            current.append(line)
    if current:
        sections.append("".join(current))
    return sections


def chunk_diff(diff_text, max_lines=None):
    """Split ``diff_text`` into chunks of strictly fewer than ``max_lines`` lines.

    Splits on file boundaries first so a chunk stays semantically readable, then
    hard-splits any single file whose hunk body still exceeds the ceiling. Every
    returned chunk satisfies ``len(chunk.splitlines()) <= max_lines``.
    """
    limit = MAX_CHUNK_LINES if max_lines is None else int(max_lines)
    if limit < 1:
        limit = 1

    chunks = []
    for section in split_diff_by_file(diff_text):
        lines = section.splitlines(keepends=True)
        if not lines:
            continue
        if len(lines) <= limit:
            chunks.append(section)
            continue
        for start in range(0, len(lines), limit):
            chunks.append("".join(lines[start:start + limit]))
    return chunks


def process_diff_chunked(diff_text, processor, max_lines=None, max_retries=None):
    """Run ``processor`` over each chunk of ``diff_text``, retrying per chunk.

    ``processor`` is called as ``processor(chunk, index, total)`` and may return
    anything; whatever it returns is collected as a partial merge result.

    Returns a dict::

        {"results": [...], "chunks": int, "succeeded": int,
         "failed": [{"index": int, "error": str}], "complete": bool}

    A chunk that keeps raising after ``max_retries`` attempts is recorded in
    ``failed`` and processing continues -- the point of chunking is that a bad
    tail does not destroy a good head. ``complete`` is True only when every
    chunk succeeded.
    """
    retries = MAX_CHUNK_RETRIES if max_retries is None else int(max_retries)
    if retries < 1:
        retries = 1

    chunks = chunk_diff(diff_text, max_lines=max_lines)
    out = {"results": [], "chunks": len(chunks), "succeeded": 0,
           "failed": [], "complete": True}
    if not chunks:
        return out
    if not callable(processor):
        logger.warning("diff_chunker: processor is not callable; returning empty result")
        out["complete"] = False
        return out

    total = len(chunks)
    for index, chunk in enumerate(chunks):
        last_error = None
        for attempt in range(retries):
            try:
                out["results"].append(processor(chunk, index, total))
                out["succeeded"] += 1
                last_error = None
                break
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "diff_chunker: chunk %d/%d attempt %d/%d failed: %s",
                    index + 1, total, attempt + 1, retries, exc,
                )
        if last_error is not None:
            out["failed"].append({"index": index, "error": str(last_error)})
            out["complete"] = False
    return out
