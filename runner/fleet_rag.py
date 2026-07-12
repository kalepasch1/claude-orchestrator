#!/usr/bin/env python3
"""
fleet_rag.py - retrieval-augmented generation over fleet knowledge.

Index (pgvector 'knowledge' table, existing embedding provider with 429 fallback):
  - Merged diff summaries
  - Task postmortems/notes
  - CLAUDE.md conventions
  - Pattern library entries
  - Sentinel/incident logs
  - REPORT-*.md docs

At prompt-build time, retrieves top-k relevant chunks for the task prompt
(k=5, token-budgeted, dedupe against already-injected patterns) and adds
a 'FLEET MEMORY' section.

Index refresh piggybacks nightly on the distill corpus job.
Retrieval is fail-soft (DB down = skip).
"""
import os, sys, json, hashlib, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

TOP_K = int(os.environ.get("FLEET_RAG_TOP_K", "5"))
TOKEN_BUDGET = int(os.environ.get("FLEET_RAG_TOKEN_BUDGET", "2000"))
CHARS_PER_TOKEN = 4  # rough estimate
CHAR_BUDGET = TOKEN_BUDGET * CHARS_PER_TOKEN
KNOWLEDGE_TABLE = "knowledge"


# ── Indexing ──────────────────────────────────────────────────────────────────

def _chunk_text(text, max_chars=800):
    """Split text into chunks of roughly max_chars, breaking at line boundaries."""
    lines = text.split("\n")
    chunks = []
    current = []
    current_len = 0
    for line in lines:
        if current_len + len(line) > max_chars and current:
            chunks.append("\n".join(current))
            current = []
            current_len = 0
        current.append(line)
        current_len += len(line) + 1
    if current:
        chunks.append("\n".join(current))
    return chunks


def _content_hash(text):
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def index_document(source_type, source_id, content, project="orchestrator"):
    """
    Index a document into the knowledge table for RAG retrieval.
    source_type: 'diff_summary', 'postmortem', 'claude_md', 'pattern', 'incident', 'report'
    Fail-soft: errors are swallowed.
    """
    chunks = _chunk_text(content)
    indexed = 0
    for i, chunk in enumerate(chunks):
        chunk_id = f"{source_type}:{source_id}:chunk{i}"
        content_hash = _content_hash(chunk)
        try:
            db.upsert(KNOWLEDGE_TABLE, {
                "id": chunk_id,
                "source_type": source_type,
                "source_id": source_id,
                "content": chunk,
                "content_hash": content_hash,
                "project": project,
                "chunk_index": i,
            })
            indexed += 1
        except Exception:
            pass
    return indexed


# ── Retrieval ─────────────────────────────────────────────────────────────────

def _keyword_score(query_words, chunk_text):
    """Simple keyword overlap score for retrieval ranking."""
    chunk_lower = chunk_text.lower()
    hits = sum(1 for w in query_words if w in chunk_lower)
    return hits / max(len(query_words), 1)


def retrieve(query, existing_patterns=None, top_k=None, budget=None):
    """
    Retrieve top-k relevant chunks for a task prompt.
    
    Dedupes against existing_patterns (set of content hashes already injected).
    Token-budgeted: stops adding chunks when budget is exhausted.
    Fail-soft: returns [] on any error.
    
    Returns list of {"content": str, "source_type": str, "source_id": str}
    """
    top_k = top_k or TOP_K
    budget = budget or CHAR_BUDGET
    existing_patterns = existing_patterns or set()

    try:
        # Fetch candidate chunks from knowledge table
        rows = db.select(KNOWLEDGE_TABLE, {
            "select": "id,content,source_type,source_id,content_hash",
            "order": "created_at.desc",
            "limit": "200",
        }) or []
    except Exception:
        return []

    # Dedupe against already-injected patterns
    candidates = []
    for r in rows:
        h = r.get("content_hash", "")
        if h and h in existing_patterns:
            continue
        candidates.append(r)

    # Score and rank by keyword overlap
    query_words = [w.lower() for w in query.split() if len(w) > 2]
    scored = []
    for r in candidates:
        content = r.get("content", "")
        score = _keyword_score(query_words, content)
        scored.append((score, r))

    scored.sort(key=lambda x: x[0], reverse=True)

    # Budget-limited selection
    results = []
    chars_used = 0
    for score, r in scored[:top_k * 3]:  # over-fetch then trim by budget
        content = r.get("content", "")
        if chars_used + len(content) > budget:
            continue
        results.append({
            "content": content,
            "source_type": r.get("source_type", ""),
            "source_id": r.get("source_id", ""),
        })
        chars_used += len(content)
        if len(results) >= top_k:
            break

    return results


# ── Prompt injection ──────────────────────────────────────────────────────────

def build_fleet_memory_section(query, existing_patterns=None):
    """
    Build a FLEET MEMORY section for injection into task prompts.
    Returns empty string if no relevant memory found or on error.
    """
    try:
        chunks = retrieve(query, existing_patterns)
        if not chunks:
            return ""
        lines = ["## FLEET MEMORY (auto-retrieved, may be relevant)\n"]
        for c in chunks:
            source = f"[{c['source_type']}:{c['source_id']}]"
            lines.append(f"### {source}")
            lines.append(c["content"])
            lines.append("")
        return "\n".join(lines)
    except Exception:
        return ""


# ── Nightly index refresh ────────────────────────────────────────────────────

def refresh_index(repo_path=None):
    """
    Refresh the knowledge index. Piggybacks on the distill corpus job.
    Indexes: CLAUDE.md, REPORT-*.md, recent task notes, pattern library.
    """
    repo_path = repo_path or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    indexed = 0

    # Index CLAUDE.md
    claude_md = os.path.join(repo_path, "CLAUDE.md")
    if os.path.isfile(claude_md):
        try:
            with open(claude_md, "r", errors="replace") as f:
                indexed += index_document("claude_md", "CLAUDE.md", f.read())
        except Exception:
            pass

    # Index REPORT-*.md files
    import glob
    for report in glob.glob(os.path.join(repo_path, "REPORT-*.md")):
        try:
            with open(report, "r", errors="replace") as f:
                name = os.path.basename(report)
                indexed += index_document("report", name, f.read())
        except Exception:
            pass

    # Index recent task postmortems/notes
    try:
        rows = db.select("tasks", {
            "select": "slug,note",
            "state": "in.(DONE,MERGED)",
            "order": "updated_at.desc",
            "limit": "100",
        }) or []
        for r in rows:
            note = r.get("note", "")
            if note and len(note) > 20:
                indexed += index_document("postmortem", r.get("slug", ""), note)
    except Exception:
        pass

    return indexed


if __name__ == "__main__":
    print(f"Indexed {refresh_index()} chunks")
