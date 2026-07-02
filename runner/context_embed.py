#!/usr/bin/env python3
"""
context_embed.py - embedding-based semantic file ranking for context retrieval.

Optimizations over the naive implementation:
  1. Batch API  - all uncached files embedded in 1-3 round-trips (not 1/file).
                  OpenAI allows 2048 inputs/batch; Voyage allows 128.
  2. Smart text - extracts import lines + function/class signatures + 300-char
                  head instead of raw first-N chars. Code structure beats raw prose.
  3. Hybrid     - final score = 0.7*cosine + 0.3*keyword_tf. Catches exact
                  identifiers the embedding model may miss.
  4. MMR        - Maximal Marginal Relevance selection: maximise relevance AND
                  diversity so the agent sees 12 varied files, not a cluster of
                  nearly identical test/util files.

Provider split (from .env):
  CONTEXT_EMBED_PROVIDER=openai  → bulk repo-file calls (cheap, fast, good dim)
  EMBED_PROVIDER=voyage           → quality path used by knowledge_embed.py
Falls back to empty list (keyword mode in context_retrieval.py) if neither set.
"""
import os, json, math, re, time, urllib.request, urllib.error
import knowledge_embed as ke

CACHE_FILE = ".orch-context-cache.json"
MAX_CHARS   = 8000    # hard cap sent to API per file (tokens ~= chars/4)
BATCH_SIZE  = 96      # stay well under Voyage's 128 limit
MMR_LAMBDA  = float(os.environ.get("CONTEXT_MMR_LAMBDA", "0.7"))   # relevance weight
HYBRID_ALPHA= float(os.environ.get("CONTEXT_HYBRID_ALPHA", "0.7")) # cosine weight

_CTX_PROVIDER   = (os.environ.get("CONTEXT_EMBED_PROVIDER") or
                   os.environ.get("EMBED_PROVIDER", "")).lower()
ENABLED         = bool(_CTX_PROVIDER)
_OPENAI_MODEL   = os.environ.get("OPENAI_EMBEDDING_MODEL",  "text-embedding-3-small")
_VOYAGE_MODEL   = os.environ.get("VOYAGE_EMBEDDING_MODEL",  "voyage-3")
_SIG_RE = re.compile(
    r"^(import |from |export |def |class |function |async function |"
    r"const |let |var |type |interface |enum |fn |pub fn |func )",
)


# ── content extraction ────────────────────────────────────────────────────────

def _extract(filepath, content):
    """Return a compact, semantically rich representation of a source file."""
    lines = content.split("\n")
    sigs  = [l.rstrip() for l in lines if _SIG_RE.match(l)][:40]
    head  = content[:300]
    body  = "\n".join(sigs) if sigs else head
    return f"{filepath}\n{body}\n{head}"[:MAX_CHARS]


# ── batch embedding ───────────────────────────────────────────────────────────

_EMBED_FAILS = 0
_EMBED_COOLDOWN_UNTIL = 0.0
_EMBED_FAIL_LIMIT = int(os.environ.get("EMBED_FAIL_LIMIT", "2"))
_EMBED_COOLDOWN_S = float(os.environ.get("EMBED_COOLDOWN_S", "900"))


def _batch_embed(texts):
    """
    Embed a list of strings in one or a few API calls.
    Returns a list of vectors (same length as `texts`), or [] on error.
    Circuit breaker: after repeated provider rate-limits (429), pause embedding for a
    cooldown and let callers fall back to keyword ranking — no wasteful retry loops.
    """
    global _EMBED_FAILS, _EMBED_COOLDOWN_UNTIL
    if not texts:
        return []
    # COST GUARD: paid embeddings (Voyage/OpenAI) are OFF by default — use free keyword ranking.
    # Opt in only if you deliberately want the semantic layer: ORCH_PAID_EMBED=true
    if os.environ.get("ORCH_PAID_EMBED", "false").lower() != "true":
        return []
    if time.time() < _EMBED_COOLDOWN_UNTIL:
        return []   # embeddings paused (rate-limited) -> keyword fallback

    def _post(url, body, headers, retries=4):
        """POST with exponential backoff on 429/5xx."""
        delay = 2.0
        for attempt in range(retries):
            try:
                req = urllib.request.Request(url, data=body, headers=headers)
                with urllib.request.urlopen(req, timeout=60) as r:
                    return json.loads(r.read())
            except urllib.error.HTTPError as e:
                if e.code in (429, 500, 502, 503, 529) and attempt < retries - 1:
                    retry_after = float(e.headers.get("Retry-After", delay))
                    print(f"[context_embed] {e.code} — retrying in {retry_after:.1f}s")
                    time.sleep(retry_after)
                    delay = min(delay * 2, 60)
                else:
                    raise
        return None

    try:
        if _CTX_PROVIDER == "openai" and os.environ.get("OPENAI_API_KEY"):
            results = []
            for i in range(0, len(texts), BATCH_SIZE):
                chunk = texts[i:i + BATCH_SIZE]
                data = _post(
                    "https://api.openai.com/v1/embeddings",
                    json.dumps({"model": _OPENAI_MODEL, "input": chunk}).encode(),
                    {"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}",
                     "Content-Type": "application/json"})
                items = data["data"]
                results.extend(x["embedding"] for x in sorted(items, key=lambda x: x["index"]))
            _EMBED_FAILS = 0
            return results

        if _CTX_PROVIDER == "voyage" and os.environ.get("VOYAGE_API_KEY"):
            results = []
            for i in range(0, len(texts), BATCH_SIZE):
                chunk = texts[i:i + BATCH_SIZE]
                data = _post(
                    "https://api.voyageai.com/v1/embeddings",
                    json.dumps({"model": _VOYAGE_MODEL, "input": chunk}).encode(),
                    {"Authorization": f"Bearer {os.environ['VOYAGE_API_KEY']}",
                     "Content-Type": "application/json"})
                for x in sorted(data["data"], key=lambda x: x["index"]):
                    v = x["embedding"]
                    results.append((v + [0.0] * 1536)[:1536])
            _EMBED_FAILS = 0
            return results
    except Exception as exc:
        _EMBED_FAILS += 1
        if _EMBED_FAILS >= _EMBED_FAIL_LIMIT:
            _EMBED_COOLDOWN_UNTIL = time.time() + _EMBED_COOLDOWN_S
            _EMBED_FAILS = 0
            print(f"[context_embed] provider rate-limited — pausing embeddings "
                  f"{_EMBED_COOLDOWN_S/60:.0f}m, using keyword fallback")
        print(f"[context_embed] batch embed error: {exc}")
    # single-vector fallback via knowledge_embed (covers any provider it supports)
    out = []
    for t in texts:
        v = ke.embed(t)
        out.append(v if v else [])
    return out


def _embed_one(text):
    vecs = _batch_embed([text])
    return vecs[0] if vecs and vecs[0] else None


# ── cache helpers ─────────────────────────────────────────────────────────────

def _load_cache(repo):
    try:
        with open(os.path.join(repo, CACHE_FILE)) as f:
            return json.load(f)
    except Exception:
        return {}


def _save_cache(repo, cache):
    try:
        with open(os.path.join(repo, CACHE_FILE), "w") as f:
            json.dump(cache, f)
    except Exception:
        pass


# ── cosine / keyword helpers ──────────────────────────────────────────────────

def _cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na  = math.sqrt(sum(x * x for x in a))
    nb  = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb + 1e-9)


def _keyword_score(prompt, repo, files):
    """
    Simple TF-overlap score: fraction of prompt tokens found in the file's
    first 3000 chars. Returns {filepath: 0..1} with no external calls.
    """
    terms = set(re.findall(r"[a-z][a-z0-9_]{2,}", prompt.lower()))
    scores = {}
    for f in files:
        try:
            with open(os.path.join(repo, f), errors="replace") as fh:
                text = fh.read(3000).lower()
        except OSError:
            scores[f] = 0.0
            continue
        hit = sum(1 for t in terms if t in text)
        scores[f] = hit / (len(terms) + 1e-9)
    # also fold in path-token overlap
    for f in files:
        path_toks = set(re.split(r"[/_.\-]", f.lower()))
        path_hit  = len(terms & path_toks) / (len(terms) + 1e-9)
        scores[f] = scores.get(f, 0.0) + 0.3 * path_hit
    # normalise to 0..1
    mx = max(scores.values()) if scores else 1.0
    return {f: v / (mx + 1e-9) for f, v in scores.items()}


# ── MMR selection ─────────────────────────────────────────────────────────────

def _mmr_select(file_vecs, hybrid_scores, k):
    """
    Maximal Marginal Relevance: greedily pick files that maximise
    MMR_LAMBDA * relevance - (1-MMR_LAMBDA) * max_redundancy_to_selected.
    Returns ordered list of up to k filepaths.
    """
    remaining  = list(hybrid_scores.keys())
    selected   = []
    sel_vecs   = []

    while remaining and len(selected) < k:
        if not sel_vecs:
            # first pick: pure relevance
            best = max(remaining, key=lambda f: hybrid_scores[f])
        else:
            def _mmr(f):
                rel = hybrid_scores[f]
                red = max(_cosine(file_vecs[f], sv) for sv in sel_vecs) if sel_vecs else 0.0
                return MMR_LAMBDA * rel - (1 - MMR_LAMBDA) * red
            best = max(remaining, key=_mmr)
        selected.append(best)
        if best in file_vecs:
            sel_vecs.append(file_vecs[best])
        remaining.remove(best)
    return selected


# ── public API ────────────────────────────────────────────────────────────────

def embed_files(repo, files):
    """Return {filepath: vector} using batched API + per-repo mtime cache."""
    if not ENABLED:
        return {}
    cache  = _load_cache(repo)
    result = {}
    to_embed = []    # (filepath, mtime_key, text)

    for f in files:
        abs_path = os.path.join(repo, f)
        try:
            mtime = str(os.path.getmtime(abs_path))
        except OSError:
            continue
        key = f"{f}:{mtime}"
        if key in cache and cache[key]:
            result[f] = cache[key]
            continue
        try:
            with open(abs_path, errors="replace") as fh:
                content = fh.read(MAX_CHARS)
        except OSError:
            continue
        if not content.strip():
            continue
        to_embed.append((f, key, _extract(f, content)))

    if to_embed:
        texts = [t for _, _, t in to_embed]
        vecs  = _batch_embed(texts)
        dirty = False
        for (f, key, _), vec in zip(to_embed, vecs):
            if vec:
                cache[key] = vec
                result[f]  = vec
                dirty = True
        if dirty:
            _save_cache(repo, cache)

    return result


def rank(repo, prompt, files, k=12):
    """
    Return up to k files from `files` ranked by hybrid semantic+keyword
    relevance to `prompt`, with MMR diversity applied.
    Returns [] if embeddings are unavailable (caller falls back to keywords).
    """
    if not ENABLED or not files:
        return []

    prompt_vec = _embed_one(prompt)
    if not prompt_vec:
        return []

    file_vecs = embed_files(repo, files)
    if not file_vecs:
        return []

    # cosine similarity scores
    cos_scores = {f: _cosine(prompt_vec, file_vecs[f])
                  for f in files if f in file_vecs}

    # keyword overlap scores (free - no API call)
    kw_scores  = _keyword_score(prompt, repo, list(cos_scores.keys()))

    # hybrid: weighted blend
    hybrid = {
        f: HYBRID_ALPHA * cos_scores[f] + (1 - HYBRID_ALPHA) * kw_scores.get(f, 0.0)
        for f in cos_scores
    }

    # MMR diversity selection
    return _mmr_select(file_vecs, hybrid, k)


if __name__ == "__main__":
    import sys
    repo   = sys.argv[1] if len(sys.argv) > 1 else "."
    prompt = sys.argv[2] if len(sys.argv) > 2 else "fix the auth allowlist"
    import context_retrieval as cr
    files  = cr._tracked(repo)[:200]
    print(f"Ranking {len(files)} files via {_CTX_PROVIDER or '(none)'}…")
    ranked = rank(repo, prompt, files)
    if ranked:
        for i, f in enumerate(ranked, 1):
            print(f"  {i:2d}. {f}")
    else:
        print("(no EMBED_PROVIDER set — keyword fallback active)")
