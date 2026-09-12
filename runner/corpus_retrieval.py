#!/usr/bin/env python3
"""corpus_retrieval.py — corpus-first retrieval for the Consilium (docs/consilium-v2.md §7.2).

WHY. Every tournament used to start from the open web: 30–40 WebSearch/WebFetch turns inside a
frontier call to find the statute the firm already holds in its verified corpus (1,200 primary
documents, 15,600 clause units). This module embeds those clause units ONCE with the local
`qwen3-embedding:4b` (Ollama, zero subscription cost) and serves the best passages for a question
so the research clerk reads the firm's own record before it searches the web.

DESIGN. Pure Python, no numpy (not installed on the runner host): vectors are L2-normalised,
truncated to 256 dimensions (Qwen3-Embedding is Matryoshka-trained; truncation keeps ranking
quality within a few points) and stored as raw float32 in one file next to a JSONL of metadata
in the same row order. 15.7K × 256 floats is 16 MB; a full cosine scan is ~1 s in pure Python.
Resumable build; every public function is fail-soft (returns [] / "" on any error).

    python3 corpus_retrieval.py build [--limit N]      # embed the corpus (resumable)
    python3 corpus_retrieval.py query "<question>" [k]
    python3 corpus_retrieval.py status
"""
from __future__ import annotations
import array
import json
import math
import os
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import db as _db  # noqa: F401  (canonical CLAUDE_ORCH_HOME)
except Exception:
    pass
import corpus_db

HOME = os.environ.get("CLAUDE_ORCH_HOME", os.path.expanduser("~/.claude-orchestrator"))
INDEX_DIR = os.path.join(HOME, "consilium", "corpus_index")
VEC_PATH = os.path.join(INDEX_DIR, "vectors.f32")
META_PATH = os.path.join(INDEX_DIR, "meta.jsonl")
EMBED_MODEL = os.environ.get("ORCH_EMBED_MODEL", "qwen3-embedding:4b")
OLLAMA = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
DIMS = int(os.environ.get("ORCH_EMBED_DIMS", "256"))
BATCH = int(os.environ.get("ORCH_EMBED_BATCH", "24"))
MIN_TEXT = 40

_CACHE = {"mtime": None, "vecs": None, "meta": None}


# ── math ─────────────────────────────────────────────────────────────────────────────────────────
def _normalize(v):
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def truncate_normalize(v, dims=DIMS):
    """Matryoshka truncation: keep the first `dims` components, re-normalise."""
    return _normalize(list(v)[:dims])


def cosine(a, b):
    return sum(x * y for x, y in zip(a, b))


# ── embedding ────────────────────────────────────────────────────────────────────────────────────
def embed(texts, model=EMBED_MODEL, timeout=600):
    """Embed a list of strings with Ollama; returns a list of truncated unit vectors (or [] on error)."""
    if not texts:
        return []
    body = json.dumps({"model": model, "input": list(texts)}).encode()
    req = urllib.request.Request(f"{OLLAMA}/api/embed", data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
        embs = data.get("embeddings") or []
        return [truncate_normalize(e) for e in embs] if len(embs) == len(texts) else []
    except Exception:
        return []


# ── index files ──────────────────────────────────────────────────────────────────────────────────
def _indexed_ids():
    ids = set()
    try:
        with open(META_PATH) as f:
            for line in f:
                try:
                    ids.add(json.loads(line)["clause_id"])
                except Exception:
                    pass
    except OSError:
        pass
    return ids


def _append(rows, vecs):
    os.makedirs(INDEX_DIR, exist_ok=True)
    with open(META_PATH, "a") as mf, open(VEC_PATH, "ab") as vf:
        for row, vec in zip(rows, vecs):
            mf.write(json.dumps(row, ensure_ascii=False) + "\n")
            array.array("f", vec).tofile(vf)


def _load():
    try:
        mt = (os.path.getmtime(META_PATH), os.path.getmtime(VEC_PATH))
    except OSError:
        return None, None
    if _CACHE["mtime"] == mt and _CACHE["vecs"] is not None:
        return _CACHE["vecs"], _CACHE["meta"]
    meta = []
    with open(META_PATH) as f:
        for line in f:
            try:
                meta.append(json.loads(line))
            except Exception:
                meta.append({})
    raw = array.array("f")
    with open(VEC_PATH, "rb") as vf:
        raw.frombytes(vf.read())
    n = min(len(meta), len(raw) // DIMS)
    vecs = [raw[i * DIMS:(i + 1) * DIMS] for i in range(n)]
    _CACHE.update(mtime=mt, vecs=vecs, meta=meta[:n])
    return vecs, meta[:n]


# ── build ────────────────────────────────────────────────────────────────────────────────────────
def _docs():
    out, off = {}, 0
    while True:
        page = corpus_db.select("corpus_documents", {
            "select": "doc_id,title,doc_type,jurisdiction_id,source_url,low_quality,superseded",
            "order": "doc_id.asc", "limit": "1000", "offset": str(off)})
        for d in page:
            out[d.get("doc_id")] = d
        if len(page) < 1000:
            break
        off += 1000
    return out


def build_index(resume=True, limit=None, page_size=500, log=print):
    """Embed every corpus clause not yet indexed. Returns a summary dict."""
    t0 = time.time()
    done = _indexed_ids() if resume else set()
    if not resume:
        for p in (META_PATH, VEC_PATH):
            try:
                os.remove(p)
            except OSError:
                pass
    docs = _docs()
    log(f"corpus_retrieval: {len(docs)} documents, {len(done)} clauses already indexed")
    added = skipped = off = 0
    while True:
        page = corpus_db.select("corpus_clauses", {
            "select": "clause_id,doc_id,heading,text,source_url,clause_type,governing_law",
            "order": "clause_id.asc", "limit": str(page_size), "offset": str(off)})
        if not page:
            break
        off += len(page)
        rows, texts = [], []
        for c in page:
            cid = c.get("clause_id")
            text = (c.get("text") or "").strip()
            doc = docs.get(c.get("doc_id")) or {}
            if not cid or cid in done or len(text) < MIN_TEXT or doc.get("low_quality") or doc.get("superseded"):
                skipped += 1
                continue
            title = doc.get("title") or c.get("doc_id") or ""
            heading = c.get("heading") or ""
            rows.append({"clause_id": cid, "doc_id": c.get("doc_id"), "heading": heading[:200],
                         "doc_title": title[:300], "jurisdiction": doc.get("jurisdiction_id") or c.get("governing_law") or "",
                         "source_url": c.get("source_url") or doc.get("source_url") or "",
                         "doc_type": doc.get("doc_type") or c.get("clause_type") or "", "text": text[:1200]})
            texts.append(f"{title}\n{heading}\n{text[:1500]}")
        for i in range(0, len(rows), BATCH):
            vecs = embed(texts[i:i + BATCH])
            if not vecs:
                log(f"corpus_retrieval: embedding failed at offset {off}; stopping (resume later)")
                return {"added": added, "skipped": skipped, "secs": round(time.time() - t0), "error": "embed failed"}
            _append(rows[i:i + BATCH], vecs)
            added += len(vecs)
            done.update(r["clause_id"] for r in rows[i:i + BATCH])
        el = time.time() - t0
        log(f"corpus_retrieval: offset {off} | indexed {added} (+{len(done)} total) | skipped {skipped} | {added / el if el else 0:.1f} rows/s")
        if limit and added >= limit:
            break
        if len(page) < page_size:
            break
    return {"added": added, "skipped": skipped, "total": len(done), "secs": round(time.time() - t0)}


# ── query ────────────────────────────────────────────────────────────────────────────────────────
def top_passages(question, k=8, jurisdiction=None, min_score=0.0, query_vec=None):
    """Best-matching corpus passages for a question. Never raises; [] when no index or no Ollama."""
    try:
        vecs, meta = _load()
        if not vecs:
            return []
        q = query_vec or (embed([question]) or [None])[0]
        if not q:
            return []
        scored = []
        for i, v in enumerate(vecs):
            m = meta[i]
            if jurisdiction and jurisdiction.lower() not in (m.get("jurisdiction") or "").lower():
                continue
            s = cosine(q, v)
            if s >= min_score:
                scored.append((s, i))
        scored.sort(key=lambda x: -x[0])
        out, seen = [], set()
        for s, i in scored:
            m = meta[i]
            key = (m.get("doc_id"), (m.get("text") or "")[:80])
            if key in seen:
                continue
            seen.add(key)
            out.append({"score": round(s, 4), **m})
            if len(out) >= k:
                break
        return out
    except Exception:
        return []


def dossier_block(question, k=8, max_chars=6000, **kw):
    """Compact numbered passages for prompt injection; "" when nothing is available."""
    try:
        parts, n = [], 0
        for i, p in enumerate(top_passages(question, k=k, **kw), 1):
            head = f"[{i}] {p.get('doc_title')} — {p.get('heading')} ({p.get('jurisdiction')}) {p.get('source_url')}"
            body = (p.get("text") or "").replace("\n", " ")[:600]
            block = f"{head}\n{body}"
            if n + len(block) + 1 > max_chars:
                break
            parts.append(block)
            n += len(block) + 1
        return "\n".join(parts)
    except Exception:
        return ""


def status():
    vecs, meta = _load()
    try:
        sizes = {os.path.basename(p): os.path.getsize(p) for p in (VEC_PATH, META_PATH)}
    except OSError:
        sizes = {}
    return {"rows": len(vecs or []), "dims": DIMS, "model": EMBED_MODEL, "index_dir": INDEX_DIR, "bytes": sizes}


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "build":
        lim = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else None
        print(json.dumps(build_index(limit=lim)))
    elif cmd == "query":
        k = int(sys.argv[3]) if len(sys.argv) > 3 else 8
        for p in top_passages(sys.argv[2], k=k):
            print(f"{p['score']:.3f}  {p['doc_title'][:70]} | {p['heading'][:50]} | {p['source_url'][:80]}")
    else:
        print(json.dumps(status(), indent=2))
