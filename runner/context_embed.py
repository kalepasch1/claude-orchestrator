#!/usr/bin/env python3
"""
context_embed.py - embedding-based semantic file ranking for context retrieval.
Upgrades context_retrieval.py from keyword/ripgrep to cosine-similarity ranking so
the agent gets pointed to the files most semantically relevant to the task, not just
files whose path/content contain the same keywords.

Uses the same EMBED_PROVIDER as knowledge_embed.py (openai or voyage). Falls back
gracefully to returning an empty list so context_retrieval.py uses keyword mode.

Embeddings are cached per-repo in .orch-context-cache.json keyed by path+mtime so
unchanged files are never re-embedded. A cold repo with 200 files = ~200 API calls
once; subsequent runs are cache hits.
"""
import os, json, math, urllib.request
import knowledge_embed as ke

CACHE_FILE = ".orch-context-cache.json"
MAX_CHARS = 1500          # chars of file content to embed (header/imports)

# context_embed uses CONTEXT_EMBED_PROVIDER when set (default: EMBED_PROVIDER).
# Typically openai (cheaper for bulk repo-file calls); voyager for quality paths.
_CTX_PROVIDER = (os.environ.get("CONTEXT_EMBED_PROVIDER") or
                 os.environ.get("EMBED_PROVIDER", "")).lower()
ENABLED = bool(_CTX_PROVIDER)
_OPENAI_MODEL = os.environ.get("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
_VOYAGE_MODEL = os.environ.get("VOYAGE_EMBEDDING_MODEL", "voyage-3")


def _embed_ctx(text):
    """Embed using CONTEXT_EMBED_PROVIDER (may differ from the main EMBED_PROVIDER)."""
    try:
        if _CTX_PROVIDER == "openai" and os.environ.get("OPENAI_API_KEY"):
            req = urllib.request.Request(
                "https://api.openai.com/v1/embeddings",
                data=json.dumps({"model": _OPENAI_MODEL, "input": text[:8000]}).encode(),
                headers={"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}",
                         "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())["data"][0]["embedding"]
        if _CTX_PROVIDER == "voyage" and os.environ.get("VOYAGE_API_KEY"):
            req = urllib.request.Request(
                "https://api.voyageai.com/v1/embeddings",
                data=json.dumps({"model": _VOYAGE_MODEL, "input": [text[:8000]]}).encode(),
                headers={"Authorization": f"Bearer {os.environ['VOYAGE_API_KEY']}",
                         "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as r:
                v = json.loads(r.read())["data"][0]["embedding"]
                return (v + [0.0] * 1536)[:1536]
    except Exception:
        pass
    # fall back to the main ke.embed() path
    return ke.embed(text)


def _load_cache(repo):
    path = os.path.join(repo, CACHE_FILE)
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return {}


def _save_cache(repo, cache):
    path = os.path.join(repo, CACHE_FILE)
    try:
        with open(path, "w") as f:
            json.dump(cache, f)
    except Exception:
        pass


def _cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb + 1e-9)


def embed_files(repo, files):
    """Return {filepath: vector} for each file, using cache where possible."""
    if not ENABLED:
        return {}
    cache = _load_cache(repo)
    result = {}
    dirty = False
    for f in files:
        abs_path = os.path.join(repo, f)
        try:
            mtime = str(os.path.getmtime(abs_path))
        except OSError:
            continue
        key = f"{f}:{mtime}"
        if key in cache:
            result[f] = cache[key]
            continue
        try:
            with open(abs_path, errors="replace") as fh:
                content = fh.read(MAX_CHARS)
        except OSError:
            continue
        if not content.strip():
            continue
        vec = _embed_ctx(f"{f}\n{content}")
        if vec:
            cache[key] = vec
            result[f] = vec
            dirty = True
    if dirty:
        _save_cache(repo, cache)
    return result


def rank(repo, prompt, files, k=12):
    """
    Return `files` re-ranked by semantic similarity to `prompt`.
    Returns empty list if embeddings are unavailable (caller falls back to keywords).
    """
    if not ENABLED or not files:
        return []
    prompt_vec = _embed_ctx(prompt)
    if not prompt_vec:
        return []
    file_vecs = embed_files(repo, files)
    if not file_vecs:
        return []
    scored = [(f, _cosine(prompt_vec, file_vecs[f])) for f in files if f in file_vecs]
    scored.sort(key=lambda x: -x[1])
    return [f for f, _ in scored[:k]]


if __name__ == "__main__":
    import sys
    repo = sys.argv[1] if len(sys.argv) > 1 else "."
    prompt = sys.argv[2] if len(sys.argv) > 2 else "fix the auth allowlist"
    import context_retrieval as cr
    files = cr._tracked(repo)[:50]
    ranked = rank(repo, prompt, files)
    print("embedding-ranked:", ranked or "(no EMBED_PROVIDER set)")
