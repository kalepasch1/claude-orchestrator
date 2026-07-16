#!/usr/bin/env python3
"""
ingest_fulltext.py - fetch full_text_url, strip HTML, chunk by section,
embed each chunk into a store, save raw blob, flip status to ingested.

Network access is injected (urllib by default, mocked in tests). Stdlib only.

Env vars:
    ORCH_FULLTEXT_ENABLED       "true" to enable (default "true")
    ORCH_FULLTEXT_CHUNK_SIZE    max chars per chunk (default 2000)
    ORCH_CORPUS_DIR             blob storage dir (default runner/corpus/blobs)
"""
import os, sys, re, hashlib, json, threading, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

try:
    import urllib.request
except ImportError:
    urllib = None

ENABLED = os.environ.get("ORCH_FULLTEXT_ENABLED", "true").lower() in ("1", "true", "yes")
CHUNK_SIZE = int(os.environ.get("ORCH_FULLTEXT_CHUNK_SIZE", "2000"))
CORPUS_DIR = os.environ.get("ORCH_CORPUS_DIR",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "corpus", "blobs"))

_stats_lock = threading.Lock()
_stats = {"fetched": 0, "chunks_created": 0, "blobs_saved": 0,
          "embedded": 0, "ingested": 0, "errors": 0}


def _inc(key, n=1):
    with _stats_lock:
        _stats[key] = _stats.get(key, 0) + n


_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")
_SECTION_RE = re.compile(r"\n{2,}")


def _strip_html(html):
    """Remove HTML tags and normalize whitespace."""
    text = _HTML_TAG_RE.sub(" ", html)
    text = _WHITESPACE_RE.sub(" ", text).strip()
    return text


def _chunk_by_section(text, chunk_size=None):
    """Split text into chunks by section breaks (double newlines) or size."""
    chunk_size = chunk_size or CHUNK_SIZE
    sections = _SECTION_RE.split(text)
    chunks = []
    current = ""
    for section in sections:
        if len(current) + len(section) + 2 > chunk_size and current:
            chunks.append(current.strip())
            current = section
        else:
            current = current + "\n\n" + section if current else section
    if current.strip():
        chunks.append(current.strip())
    # handle oversized single sections
    final = []
    for ch in chunks:
        while len(ch) > chunk_size:
            final.append(ch[:chunk_size])
            ch = ch[chunk_size:]
        if ch:
            final.append(ch)
    return final


def _save_blob(text, corpus_dir=None):
    """Save raw text blob to corpus/blobs/<hash>.txt. Returns hash."""
    corpus = corpus_dir or CORPUS_DIR
    os.makedirs(corpus, exist_ok=True)
    h = hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:16]
    path = os.path.join(corpus, f"{h}.txt")
    try:
        with open(path, "w") as f:
            f.write(text)
        _inc("blobs_saved")
    except Exception:
        _inc("errors")
    return h


def _default_fetch(url):
    """Default network fetcher using urllib (stdlib)."""
    req = urllib.request.Request(url, headers={"User-Agent": "beethoven-ingest/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="replace")


def ingest_fulltext(record, store, embedder, fetcher=None, corpus_dir=None):
    """Fetch full_text_url, strip HTML, chunk, embed, save blob, flip status.

    Args:
        record: dict with at least 'full_text_url' and 'id'
        store: object with .add(chunk_id, vector, metadata) method
        embedder: callable(text) -> vector (list of floats)
        fetcher: callable(url) -> html string (default: urllib)
        corpus_dir: override blob storage directory
    Returns:
        dict with ingestion results
    """
    if not ENABLED:
        return {"status": "disabled"}
    url = record.get("full_text_url")
    if not url:
        return {"status": "skipped", "reason": "no_full_text_url"}
    fetch = fetcher or _default_fetch
    try:
        html = fetch(url)
        _inc("fetched")
    except Exception as e:
        _inc("errors")
        return {"status": "error", "reason": f"fetch_failed: {e}"}
    text = _strip_html(html)
    blob_hash = _save_blob(text, corpus_dir=corpus_dir)
    chunks = _chunk_by_section(text)
    _inc("chunks_created", len(chunks))
    rec_id = record.get("id", blob_hash)
    for i, chunk in enumerate(chunks):
        try:
            vec = embedder(chunk)
            chunk_id = f"{rec_id}_chunk_{i}"
            store.add(chunk_id, vec, {"record_id": rec_id, "chunk_index": i,
                                      "length": len(chunk)})
            _inc("embedded")
        except Exception:
            _inc("errors")
    record["full_text_status"] = "ingested"
    record["blob_hash"] = blob_hash
    _inc("ingested")
    return {"status": "ingested", "blob_hash": blob_hash,
            "chunks": len(chunks), "record_id": rec_id}


def stats():
    with _stats_lock:
        return dict(_stats)


def reset_stats():
    with _stats_lock:
        for k in _stats:
            _stats[k] = 0


if __name__ == "__main__":
    print(json.dumps(stats(), indent=2))
