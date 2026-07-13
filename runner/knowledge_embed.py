#!/usr/bin/env python3
"""
knowledge_embed.py - semantic cross-project reuse via Supabase pgvector.

extract(project,title,tags,body)  - embed + store a reusable solution in Supabase.
inject(prompt)                    - embed the prompt, pull the nearest prior solutions
                                    via match_knowledge(), prepend them so agents reuse
                                    instead of writing from scratch.

Embeddings are pluggable. Set EMBED_PROVIDER + key:
    voyage  -> VOYAGE_API_KEY      (voyage-3, 1024d -> padded/truncated to 1536)
    openai  -> OPENAI_API_KEY      (text-embedding-3-small, 1536d)
If no provider/key is set, falls back to the dependency-free keyword search in
knowledge.py, so it always works.

RATE-LIMIT HANDLING (2026-07-08): as of this writing the embed provider was 429-throttled so
hard that .runtime/knowledge/ stayed permanently empty and every call fell back to keyword
search for the whole cooldown window. The circuit breaker below already stops hammering a
throttled provider; this adds two more degradation steps before giving up on semantic search
for a given text: (1) while the circuit is open (or a call still fails), try a LOCAL Ollama
embedding model if one is reachable — no cooldown needed, it's not the throttled resource;
(2) if that's also unavailable, persist the text to a small retry queue that a later periodic
tick drains — so a 429 degrades to "embedded a bit later," not "keyword-only forever."
"""
import os, json, time, urllib.request, urllib.error
import db
import knowledge as kw_fallback

PROVIDER = os.environ.get("EMBED_PROVIDER", "").lower()
VOYAGE_MODEL = os.environ.get("VOYAGE_EMBEDDING_MODEL", "voyage-3")
OPENAI_MODEL = os.environ.get("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
DIM = 1536
OLLAMA_EMBED_MODEL = os.environ.get("ORCH_OLLAMA_EMBED_MODEL", "nomic-embed-text")

HOME = os.environ.get("CLAUDE_ORCH_HOME", os.path.expanduser("~/.claude-orchestrator"))
RETRY_QUEUE = os.path.join(HOME, "knowledge", "embed_retry_queue.jsonl")
QUEUE_MIN_BACKOFF_S = int(os.environ.get("ORCH_EMBED_QUEUE_MIN_BACKOFF_S", "60"))     # 1 min
QUEUE_MAX_BACKOFF_S = int(os.environ.get("ORCH_EMBED_QUEUE_MAX_BACKOFF_S", "3600"))   # capped at 1h

# Adaptive circuit breaker: on 429/error, skip API calls for CIRCUIT_COOLDOWN_S seconds
# then probe once to see if the provider recovered. Zero-delay fallback to keyword search.
_circuit = {"open_until": 0.0, "consecutive_failures": 0}
CIRCUIT_COOLDOWN_S = 300  # 5 minutes between probes when circuit is open
CIRCUIT_RESET_AFTER = 3   # consecutive successes to fully close the circuit


def _http_json(url, payload, headers):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 headers={**headers, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def _provider_call(text):
    vec = None
    if PROVIDER == "openai" and os.environ.get("OPENAI_API_KEY"):
        d = _http_json("https://api.openai.com/v1/embeddings",
                       {"model": OPENAI_MODEL, "input": text[:8000]},
                       {"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"})
        vec = d["data"][0]["embedding"]
    elif PROVIDER == "voyage" and os.environ.get("VOYAGE_API_KEY"):
        d = _http_json("https://api.voyageai.com/v1/embeddings",
                       {"model": VOYAGE_MODEL, "input": [text[:8000]]},
                       {"Authorization": f"Bearer {os.environ['VOYAGE_API_KEY']}"})
        v = d["data"][0]["embedding"]
        vec = (v + [0.0] * DIM)[:DIM]
    return vec


def _ollama_embed(text):
    """Local fallback so a cloud-provider 429/circuit-open doesn't force keyword-only search
    for the whole cooldown window. Returns None (never raises) on any failure — this is itself
    a best-effort fallback, not a hard dependency."""
    try:
        base = (os.environ.get("OLLAMA_API_BASE") or os.environ.get("OLLAMA_HOST")
                or "http://127.0.0.1:11434")
        if not base.startswith("http"):
            base = "http://" + base
        d = _http_json(base.rstrip("/") + "/api/embeddings",
                       {"model": OLLAMA_EMBED_MODEL, "prompt": text[:8000]}, {})
        v = d.get("embedding")
        if v:
            return (list(v) + [0.0] * DIM)[:DIM]
    except Exception:
        pass
    return None


def _enqueue_retry(text, reason):
    try:
        os.makedirs(os.path.dirname(RETRY_QUEUE), exist_ok=True)
        with open(RETRY_QUEUE, "a", encoding="utf-8") as f:
            f.write(json.dumps({"text": text[:8000], "reason": reason,
                                "queued_at": time.time(), "attempts": 0,
                                "next_attempt_at": time.time() + QUEUE_MIN_BACKOFF_S}) + "\n")
    except Exception:
        pass  # queue persistence is best-effort; worst case this item just stays keyword-only


def embed(text):
    """Return a 1536-d vector, or None to signal keyword fallback for THIS call (the text may
    still surface later via the local fallback or the persistent retry queue).

    Adaptive circuit breaker: on any API error (429, timeout, DNS), immediately returns None
    and opens the circuit for 5 minutes. During that window, ALL embed calls skip the cloud API
    entirely (zero-delay) but still try the local Ollama fallback before giving up. After 5
    minutes, allows ONE probe call to check if the provider recovered. On success, closes the
    circuit.
    """
    if not isinstance(text, str):
        try:
            text = json.dumps(text, default=str)
        except Exception:
            text = str(text)
    now = time.time()
    circuit_open = now < _circuit["open_until"]
    vec, err = None, None
    if not circuit_open:
        try:
            vec = _provider_call(text)
            if vec:
                _circuit["consecutive_failures"] = 0  # success -> close circuit
                return vec
        except Exception as e:
            err = e
            _circuit["consecutive_failures"] += 1
            cooldown = min(CIRCUIT_COOLDOWN_S * _circuit["consecutive_failures"], 1800)
            _circuit["open_until"] = now + cooldown
            print(f"[embed] circuit OPEN for {cooldown}s after error: {str(e)[:80]} "
                  f"(failures={_circuit['consecutive_failures']})")
    local = _ollama_embed(text)
    if local:
        return local
    _enqueue_retry(text, str(err) if err else ("circuit open" if circuit_open else "provider unavailable"))
    return None


def retry_queue_flush(max_items=10):
    """Periodic job entry point: drain due items from the persistent retry queue. Each retry
    that still fails gets its backoff doubled (capped) and is re-enqueued; a success is simply
    dropped from the queue (the original extract()/inject() caller already got its answer at
    call time — this just warms semantic search for the NEXT lookup of similar text, turning
    permanent keyword-fallback into eventually-consistent semantic search)."""
    try:
        with open(RETRY_QUEUE) as f:
            items = [json.loads(l) for l in f if l.strip()]
    except FileNotFoundError:
        return {"flushed": 0, "requeued": 0, "remaining": 0}
    except Exception:
        return {"flushed": 0, "requeued": 0, "remaining": 0, "error": "corrupt queue"}

    now = time.time()
    due, not_due = [], []
    for it in items:
        (due if it.get("next_attempt_at", 0) <= now else not_due).append(it)

    flushed, still_pending = 0, []
    for it in due[:max_items]:
        try:
            vec = _provider_call(it["text"])
        except Exception:
            vec = None
        if vec:
            flushed += 1
            continue
        it["attempts"] = it.get("attempts", 0) + 1
        backoff = min(QUEUE_MIN_BACKOFF_S * (2 ** it["attempts"]), QUEUE_MAX_BACKOFF_S)
        it["next_attempt_at"] = now + backoff
        still_pending.append(it)
    still_pending.extend(due[max_items:])   # over-budget items stay due, retried next tick
    remaining = still_pending + not_due
    try:
        os.makedirs(os.path.dirname(RETRY_QUEUE), exist_ok=True)
        with open(RETRY_QUEUE, "w", encoding="utf-8") as f:
            for it in remaining:
                f.write(json.dumps(it) + "\n")
    except Exception:
        pass
    return {"flushed": flushed, "requeued": len(still_pending), "remaining": len(remaining)}


def stats():
    try:
        with open(RETRY_QUEUE) as f:
            n = sum(1 for l in f if l.strip())
    except Exception:
        n = 0
    return {"provider": PROVIDER or "none", "retry_queue_depth": n,
            "circuit_open": time.time() < _circuit["open_until"],
            "consecutive_failures": _circuit["consecutive_failures"]}


def invalidate():
    """Reset the circuit breaker and drop the retry queue (e.g. after rotating a provider key
    so stale failures/429s don't linger)."""
    _circuit["open_until"] = 0.0
    _circuit["consecutive_failures"] = 0
    try:
        os.remove(RETRY_QUEUE)
    except FileNotFoundError:
        pass
    except Exception:
        pass


def extract(project, title, tags, body):
    vec = embed(f"{title}\n{tags}\n{body}")
    row = {"project": project, "title": title,
           "tags": [t.strip() for t in tags.split(",") if t.strip()],
           "body": body, "keywords": kw_fallback.toks(title + " " + tags + " " + body)[:40]}
    if vec:
        row["embedding"] = vec
    db.insert("knowledge", row)


def inject(prompt, k=3):
    vec = embed(prompt)
    hits = []
    if vec:
        try:
            hits = db.rpc("match_knowledge", {"query_embedding": vec, "match_count": k}) or []
        except Exception:
            hits = []
    if not hits:                                     # keyword fallback over Supabase rows
        try:
            rows = db.select("knowledge", {"select": "project,title,body,keywords"}) or []
            hits = kw_fallback.rank(prompt, rows, k) if hasattr(kw_fallback, "rank") else []
        except Exception:
            hits = []
    if not hits:
        return prompt
    blocks = [f"### {h['title']} (from {h.get('project')})\n{h['body'].strip()}" for h in hits]
    return ("# Relevant prior solutions from other projects - REUSE/adapt instead of "
            "writing from scratch:\n\n" + "\n\n".join(blocks) + "\n\n# ---- your task ----\n" + prompt)


if __name__ == "__main__":
    import sys
    print(inject(sys.argv[1] if len(sys.argv) > 1 else "example task"))
