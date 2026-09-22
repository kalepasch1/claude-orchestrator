#!/usr/bin/env python3
"""local_llm.py — the Consilium's LOCAL model tier: EXO and Ollama, zero subscription cost.

OPERATOR DIRECTION (2026-09-21): tournaments run on the local stack — the best model this machine
can hold — and the subscription models are an escalation, not the default. The host is an M5 Max
with 48 GB, so "best local" is a model that fits beside everything else: Qwen3.5-35B-A3B on EXO
(19 GB, 3B active parameters, so it generates fast) and the dense qwen3.5:27b on Ollama behind it.
The 80B/120B checkpoints on disk do not fit and are not tried.

One function, chat(): system + user -> text, optionally constrained to a JSON schema. Ollama
enforces the schema with a grammar (`format`), so the object always parses; EXO is asked through
`response_format` and, failing that, by instruction with one repair pass. Providers are tried in
ORCH_LOCAL_MODELS order; every failure is soft and recorded in the result.

    python3 local_llm.py status        # what is reachable / placed
    python3 local_llm.py probe         # one short call per provider with tok/s
"""
from __future__ import annotations
import json
import os
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

EXO = os.environ.get("EXO_HOST", "http://127.0.0.1:52415").rstrip("/")
OLLAMA = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
if not OLLAMA.startswith("http"):
    OLLAMA = "http://" + OLLAMA
MODELS = [m.strip() for m in os.environ.get(
    "ORCH_LOCAL_MODELS", "exo:mlx-community/Qwen3.5-122B-A10B-4bit,exo:mlx-community/Qwen3-Next-80B-A3B-Instruct-4bit,"
                         "exo:mlx-community/Qwen3.5-35B-A3B-4bit,exo:mlx-community/Qwen3.5-27B-4bit,"
                         "ollama:qwen3.5:27b-mlx,exo:mlx-community/Qwen3.5-9B-4bit").split(",") if m.strip()]
# The cluster has its own placement owner (~/cluster-control/exo-health-watchdog.sh keeps the 80B and
# the 27B up when all three nodes are healthy). This client therefore PREFERS whatever is already
# resident, places a model only when no rung is resident (ORCH_EXO_PLACE=false forbids even that),
# uses the watchdog's own placement parameters, and NEVER deletes an instance.
EXO_PLACE = os.environ.get("ORCH_EXO_PLACE", "true").lower() not in ("0", "false", "no", "off")
# CLUSTER-AWARE (2026-09-21). The operator runs three Macs on Thunderbolt (>100 GB pooled). When the
# peers are joined, EXO can shard the 122B (65 GB, 10B active) across them and that is the tribunal's
# model; when they are not — measured today: both peers dropped off after a reboot, topology = 1
# node — the same ladder falls to what THIS host can hold. EXO itself is the oracle: a rung is
# placeable iff /instance/previews returns a placement without an error for the current topology.
# THE LADDER IS MEMORY-AWARE (2026-09-21). Measured on this 48 GB host with the fleet, two Nuxt dev
# servers and two EXO instances up: 16 GB available, swap 93% used. Loading a 19 GB model into that
# does not make the tournament better, it takes the machine down. A rung is tried only when its
# weights plus a working margin fit in RAM that is actually free; a model that is ALREADY resident
# (an EXO instance that is ready, an Ollama model that is loaded) costs nothing more and is always
# eligible. GiB needed to load, by substring of the model name:
NEED_GB = {"35b-a3b": 26, "27b": 24, "32b": 24, "80b": 46, "120b": 70, "122b": 72, "9b": 8, "4b": 5}
THINKING = os.environ.get("ORCH_LOCAL_THINKING", "false").lower() in ("1", "true", "yes", "on")
NUM_CTX = int(os.environ.get("ORCH_LOCAL_NUM_CTX", "32768"))
EXO_PLACE_WAIT_S = int(os.environ.get("ORCH_EXO_PLACE_WAIT_S", "600"))


def _http(url, body=None, timeout=60, method=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def extract_json(text):
    try:
        import frontier
        return frontier.extract_json(text)
    except Exception:
        try:
            return json.loads(text)
        except Exception:
            return None


def strip_thinking(text):
    t = str(text or "")
    while "<think>" in t and "</think>" in t:
        a, b = t.index("<think>"), t.index("</think>") + len("</think>")
        t = t[:a] + t[b:]
    return t.strip()


def free_gb():
    """RAM available right now, GiB. EXO reports it; vm_stat is the fallback. None when unknown."""
    try:
        me = _http(f"{EXO}/node_id", timeout=5)          # THIS host only: Ollama cannot use a peer's RAM
        mem = (_http(f"{EXO}/state", timeout=8).get("nodeMemory") or {}).get(me if isinstance(me, str) else "")
        if isinstance(mem, dict) and mem.get("ramAvailable"):
            return mem["ramAvailable"]["inBytes"] / 2 ** 30
    except Exception:
        pass
    try:
        import subprocess
        out = subprocess.run(["vm_stat"], capture_output=True, text=True, timeout=5).stdout
        page = 16384
        pages = sum(int(l.split(":")[1].strip().rstrip(".")) for l in out.splitlines()
                    if l.startswith(("Pages free", "Pages inactive", "Pages speculative")))
        return pages * page / 2 ** 30
    except Exception:
        return None


def need_gb(model):
    m = (model or "").lower()
    for k, v in NEED_GB.items():
        if k in m:
            return v
    return 12


def resident(provider, model):
    try:
        if provider == "exo":
            return exo_instance_ready(model)
        if provider == "ollama":
            return any(x.get("name") == model for x in (_http(f"{OLLAMA}/api/ps", timeout=5).get("models") or []))
    except Exception:
        pass
    return False


def exo_placeable(model):
    """(ok, reason) from EXO's own placement planner for the CURRENT cluster topology and memory."""
    try:
        import urllib.parse
        d = _http(f"{EXO}/instance/previews?model_id={urllib.parse.quote(model, safe='')}", timeout=20)
        previews = d.get("previews") if isinstance(d, dict) else d
        good = [p for p in (previews or []) if not p.get("error")]
        if good:
            return True, f"exo can place it ({len(good)} placements)"
        return False, str(((previews or [{}])[0]).get("error") or "no placement")[:120]
    except Exception as e:
        return False, f"previews unavailable: {str(e)[:80]}"


def cluster():
    """Nodes EXO currently has in its topology, and the RAM it reports available on each."""
    try:
        st = _http(f"{EXO}/state", timeout=10)
        nodes = (st.get("topology") or {}).get("nodes") or []
        names = {k: (v or {}).get("friendlyName") for k, v in (st.get("nodeIdentities") or {}).items()}
        mem = {k: round(v["ramAvailable"]["inBytes"] / 2 ** 30, 1) for k, v in (st.get("nodeMemory") or {}).items()
               if isinstance(v, dict) and v.get("ramAvailable")}
        return {"joined": [names.get(n) or n[-6:] for n in nodes],
                "known_but_absent": [v for k, v in names.items() if k not in nodes],
                "free_gb": {names.get(k) or k[-6:]: g for k, g in mem.items()}}
    except Exception as e:
        return {"error": str(e)[:120]}


def fits(provider, model, free=None):
    """(ok, reason). Resident models always fit; EXO rungs ask EXO's planner; Ollama rungs need
    their weights plus a margin in RAM that is free on this host."""
    if resident(provider, model):
        return True, "resident"
    if provider == "exo" and free is None:
        return exo_placeable(model)
    free = free_gb() if free is None else free
    if free is None:
        return False, "free memory unknown"
    need = need_gb(model)
    return (free >= need), f"needs {need} GiB, {free:.1f} free"


# ── EXO ──────────────────────────────────────────────────────────────────────────────────────────
#: runner states in which the model can take a request
_SERVING = __import__("re").compile(r"Ready|Running")


def _runner_state(runners, runner_id):
    v = runners.get(runner_id)
    return next(iter(v.keys())) if isinstance(v, dict) and v else str(v)


def exo_instance_ready(model, state=None):
    """True when an EXO instance for `model` exists and ITS OWN runners report ready.

    2026-09-21: this used to require every runner in the cluster to be ready. Deleted instances
    leave runners in RunnerShuttingDown for minutes, so a perfectly good placement never looked
    ready and the caller waited out its whole timeout. Only the runners this instance's shard
    assignments name are relevant.
    """
    try:
        st = state or _http(f"{EXO}/state", timeout=10)
    except Exception:
        return False
    runners = st.get("runners") or {}
    for wrapper in (st.get("instances") or {}).values():
        inst = next(iter(wrapper.values()), {}) if isinstance(wrapper, dict) else {}
        assign = inst.get("shardAssignments") or {}
        if assign.get("modelId") != model:
            continue
        ids = list((assign.get("nodeToRunner") or {}).values())
        # A runner that is mid-request reports RunnerRunning, not RunnerReady. Treating Running as
        # unavailable (measured 2026-09-21) made a busy model look gone, so the ladder fell through
        # to an Ollama rung this host could not fund and the call was deferred on host_load.
        if ids and all(_SERVING.search(_runner_state(runners, r)) for r in ids):
            return True
    return False


def exo_ensure(model, wait_s=EXO_PLACE_WAIT_S):
    if exo_instance_ready(model):
        return True
    try:
        st = _http(f"{EXO}/state", timeout=10)
        placed = any((next(iter(w.values()), {}) if isinstance(w, dict) else {}).get("shardAssignments", {}).get("modelId") == model
                     for w in (st.get("instances") or {}).values())
        if not placed:
            if not EXO_PLACE:
                return False
            _http(f"{EXO}/place_instance", {"model_id": model, "sharding": "Pipeline", "instance_meta": "MlxRing",
                                            "min_nodes": 1}, timeout=120)
    except Exception:
        return False
    t0 = time.time()
    while time.time() - t0 < wait_s:
        if exo_instance_ready(model):
            return True
        time.sleep(10)
    return False


def _exo_chat(model, system, user, json_schema, max_tokens, temperature, timeout):
    if not exo_ensure(model):
        return {"error": "exo instance not ready"}
    body = {"model": model, "max_tokens": max_tokens, "temperature": temperature,
            "messages": ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": user}]}
    body["enable_thinking"] = THINKING
    if json_schema:
        body["response_format"] = {"type": "json_schema", "json_schema": {"name": "out", "schema": json_schema, "strict": True}}
    try:
        r = _http(f"{EXO}/v1/chat/completions", body, timeout=timeout)
    except Exception as e:
        if not json_schema:
            return {"error": f"{type(e).__name__}: {str(e)[:160]}"}
        body.pop("response_format", None)       # server may not accept response_format; ask in words
        try:
            r = _http(f"{EXO}/v1/chat/completions", body, timeout=timeout)
        except Exception as e2:
            return {"error": f"{type(e2).__name__}: {str(e2)[:160]}"}
    msg = ((r.get("choices") or [{}])[0].get("message") or {})
    u = r.get("usage") or {}
    return {"text": strip_thinking(msg.get("content") or ""), "tokens_in": int(u.get("prompt_tokens") or 0),
            "tokens_out": int(u.get("completion_tokens") or 0)}


# ── Ollama ───────────────────────────────────────────────────────────────────────────────────────
def _ollama_chat(model, system, user, json_schema, max_tokens, temperature, timeout):
    body = {"model": model, "stream": False, "think": False,
            "messages": ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": user}],
            "options": {"num_ctx": NUM_CTX, "num_predict": max_tokens, "temperature": temperature}}
    if json_schema:
        body["format"] = json_schema
    ctx = None
    try:
        import local_model_slots
        ctx = local_model_slots.slot(model, operation="consilium.local")
    except Exception:
        ctx = None
    try:
        if ctx is not None:
            with ctx:
                r = _http(f"{OLLAMA}/api/chat", body, timeout=timeout)
        else:
            r = _http(f"{OLLAMA}/api/chat", body, timeout=timeout)
    except Exception as e:
        return {"error": f"{type(e).__name__}: {str(e)[:160]}"}
    return {"text": strip_thinking(((r.get("message") or {}).get("content")) or ""),
            "tokens_in": int(r.get("prompt_eval_count") or 0), "tokens_out": int(r.get("eval_count") or 0)}


_BACKENDS = {"exo": _exo_chat, "ollama": _ollama_chat}


def chat(user, *, system=None, json_schema=None, max_tokens=8000, temperature=0.3, timeout=2400,
         models=None, tag="local", project="consilium"):
    """-> {text, json, model, provider, tokens_in, tokens_out, latency_s, tok_per_s, error, attempts}"""
    out = {"text": "", "json": None, "model": None, "provider": None, "tokens_in": 0, "tokens_out": 0,
           "latency_s": 0.0, "tok_per_s": 0.0, "error": "", "attempts": [], "cost_weighted": 0}
    if json_schema:
        user = (user + "\n\nReturn ONLY one JSON object that matches this JSON Schema exactly (no prose, no code fence):\n"
                + json.dumps(json_schema)[:6000])
    ladder = list(models or MODELS)
    ladder.sort(key=lambda sp: 0 if resident(*sp.partition(":")[::2]) else 1)   # stable: resident rungs first
    for spec in ladder:
        provider, _, model = spec.partition(":")
        fn = _BACKENDS.get(provider)
        if not fn or not model:
            continue
        ok, why = fits(provider, model)
        if not ok:
            out["attempts"].append({"model": spec, "error": f"skipped: {why}", "latency_s": 0})
            continue
        t0 = time.time()
        r = fn(model, system, user, json_schema, max_tokens, temperature, timeout)
        lat = time.time() - t0
        parsed = extract_json(r.get("text")) if (json_schema and r.get("text")) else None
        err = r.get("error") or ("" if (r.get("text") and (parsed is not None or not json_schema)) else "empty or unparseable output")
        out["attempts"].append({"model": spec, "error": err, "latency_s": round(lat, 1)})
        _telemetry(project, tag, provider, model, user, lat, ok=not err)
        if err:
            out["error"] = err
            continue
        tout = r.get("tokens_out") or 0
        out.update(text=r["text"], json=parsed, model=model, provider=provider, tokens_in=r.get("tokens_in") or 0,
                   tokens_out=tout, latency_s=round(lat, 1), tok_per_s=round(tout / lat, 1) if lat else 0.0, error="")
        return out
    out["error"] = out["error"] or "; ".join(f"{a['model']}: {a['error']}" for a in out["attempts"]) or "no local model configured"
    return out


def _telemetry(project, tag, provider, model, prompt, latency_s, ok):
    try:
        import db
        db.insert("app_operations", {"app": project or "consilium", "operation": tag, "task_class": "consilium",
                                     "provider": f"local-{provider}", "model": model, "prompt_chars": len(prompt or ""),
                                     "cost_usd": 0.0, "latency_ms": int(latency_s * 1000), "ok": bool(ok)})
    except Exception:
        pass


def available():
    for spec in MODELS:
        provider, _, model = spec.partition(":")
        try:
            if provider == "exo":
                _http(f"{EXO}/node_id", timeout=5)
                return True
            if provider == "ollama":
                tags = _http(f"{OLLAMA}/api/tags", timeout=5)
                if any(m.get("name") == model for m in (tags.get("models") or [])):
                    return True
        except Exception:
            continue
    return False


def status():
    out = {"models": MODELS, "available": available(), "cluster": cluster(),
           "ladder": [{"model": m, "fits": fits(*m.partition(":")[::2])} for m in MODELS]}
    try:
        st = _http(f"{EXO}/state", timeout=10)
        out["exo_instances"] = len(st.get("instances") or {})
        out["exo_ready"] = {m.partition(":")[2]: exo_instance_ready(m.partition(":")[2]) for m in MODELS if m.startswith("exo:")}
    except Exception as e:
        out["exo_error"] = str(e)[:120]
    try:
        out["ollama_loaded"] = [m.get("name") for m in (_http(f"{OLLAMA}/api/ps", timeout=5).get("models") or [])]
    except Exception as e:
        out["ollama_error"] = str(e)[:120]
    return out


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "probe":
        for spec in MODELS:
            r = chat("In two sentences: what does 31 CFR 1022.380 require?", system="Be precise.", max_tokens=200,
                     models=[spec], timeout=900, tag="local.probe")
            print(json.dumps({k: r[k] for k in ("model", "provider", "tokens_in", "tokens_out", "latency_s", "tok_per_s", "error")}))
            print("  ", r["text"][:200].replace("\n", " "))
    else:
        print(json.dumps(status(), indent=2))
