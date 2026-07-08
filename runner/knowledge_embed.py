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
"""
import os, json, urllib.request
import db
import knowledge as kw_fallback

PROVIDER = os.environ.get("EMBED_PROVIDER", "").lower()
VOYAGE_MODEL = os.environ.get("VOYAGE_EMBEDDING_MODEL", "voyage-3")
OPENAI_MODEL = os.environ.get("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
DIM = 1536

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


def embed(text):
    """Return a 1536-d vector, or None to signal keyword fallback.

    Adaptive circuit breaker: on any API error (429, timeout, DNS), immediately returns None
    and opens the circuit for 5 minutes. During that window, ALL embed calls skip the API
    entirely (zero-delay keyword fallback). After 5 minutes, allows ONE probe call to check
    if the provider recovered. On success, closes the circuit.
    """
    import time as _time
    now = _time.time()
    # Circuit is open — skip API entirely, instant keyword fallback
    if now < _circuit["open_until"]:
        return None
    try:
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
        if vec:
            _circuit["consecutive_failures"] = 0  # success -> close circuit
            return vec
    except Exception as e:
        _circuit["consecutive_failures"] += 1
        cooldown = min(CIRCUIT_COOLDOWN_S * _circuit["consecutive_failures"], 1800)
        _circuit["open_until"] = now + cooldown
        print(f"[embed] circuit OPEN for {cooldown}s after error: {str(e)[:80]} "
              f"(failures={_circuit['consecutive_failures']})")
    return None


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
