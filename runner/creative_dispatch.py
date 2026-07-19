#!/usr/bin/env python3
"""
creative_dispatch.py - dispatch tasks to specialized creative AI APIs.

Complements swarm_executor.py (text-completion providers: Claude/OpenAI/DeepSeek/
Gemini/Groq/xAI) by handling creative-generation vendors that are NOT text-completion
APIs: image, video, 3D, and audio/voice generation.

Vendors:
    BFL (FLUX.2)  — image generation      POST https://api.bfl.ml/v1/flux-pro-1.1
    Ideogram      — text-in-image         POST https://api.ideogram.ai/generate
    ElevenLabs    — text-to-speech/voice  POST https://api.elevenlabs.io/v1/text-to-speech/{voice_id}
    Kling         — video generation      POST https://api.klingai.com/v1/videos/text2video
    Meshy         — 3D model generation   POST https://api.meshy.ai/v2/text-to-3d

Uses runner.vendor_capabilities for capability detection/routing and stdlib only
(urllib) for HTTP, matching the codebase's fail-soft, thread-safe, env-var-config
conventions.

Env:
    CREATIVE_MAX_USD_HOUR (default 5)   per-hour spend cap
    CREATIVE_MAX_USD_DAY  (default 20)  per-day spend cap
    BFL_API_KEY / IDEOGRAM_API_KEY / ELEVENLABS_API_KEY / KLING_API_KEY / MESHY_API_KEY
"""
import os, sys, json, time, threading, logging, urllib.request, urllib.error
from typing import Dict, List, Optional, Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
log = logging.getLogger(__name__)

try:
    import vendor_capabilities as _vc
except Exception:
    _vc = None

try:
    import db as _db
except Exception:
    _db = None

# ---------------------------------------------------------------------------
# Provider registry
# ---------------------------------------------------------------------------
CREATIVE_PROVIDERS: Dict[str, dict] = {
    "bfl": {
        "capability": "image_generation",
        "base_url": "https://api.bfl.ml/v1/flux-pro-1.1",
        "key_env": "BFL_API_KEY",
        "model": "flux-2-pro",
        "cost_per_unit": 0.03,  # per image
        "auth_style": "bearer",
        "async_poll": True,
    },
    "ideogram": {
        "capability": "text_in_image",
        "base_url": "https://api.ideogram.ai/generate",
        "key_env": "IDEOGRAM_API_KEY",
        "model": "ideogram-3.0",
        "cost_per_unit": 0.04,  # per image
        "auth_style": "api-key",
        "async_poll": False,
    },
    "elevenlabs": {
        "capability": "audio_generation",
        "base_url": "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
        "key_env": "ELEVENLABS_API_KEY",
        "model": "eleven-multilingual-v2",
        "cost_per_unit": 0.0003,  # per character (approx)
        "auth_style": "xi-api-key",
        "async_poll": False,
    },
    "kling": {
        "capability": "video_generation",
        "base_url": "https://api.klingai.com/v1/videos/text2video",
        "key_env": "KLING_API_KEY",
        "model": "kling-3.0",
        "cost_per_unit": 0.075,  # per second
        "auth_style": "bearer",
        "async_poll": True,
    },
    "meshy": {
        "capability": "3d_generation",
        "base_url": "https://api.meshy.ai/v2/text-to-3d",
        "key_env": "MESHY_API_KEY",
        "model": "meshy-4",
        "cost_per_unit": 0.20,  # per generation
        "auth_style": "bearer",
        "async_poll": True,
    },
}

DEFAULT_VOICE_ID = os.environ.get("ELEVENLABS_DEFAULT_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")

# ---------------------------------------------------------------------------
# Budget tracker (thread-safe) — mirrors swarm_executor's pattern
# ---------------------------------------------------------------------------
MAX_USD_HOUR = float(os.environ.get("CREATIVE_MAX_USD_HOUR", "5"))
MAX_USD_DAY = float(os.environ.get("CREATIVE_MAX_USD_DAY", "20"))

_budget_lock = threading.Lock()
_spend_log: List[tuple] = []  # (timestamp, usd, provider)


def _check_budget():
    now = time.time()
    with _budget_lock:
        hour_spend = sum(u for t, u, _ in _spend_log if now - t < 3600)
        day_spend = sum(u for t, u, _ in _spend_log if now - t < 86400)
    if hour_spend >= MAX_USD_HOUR:
        raise RuntimeError(f"creative hourly cap ${MAX_USD_HOUR:.2f} reached (${hour_spend:.2f})")
    if day_spend >= MAX_USD_DAY:
        raise RuntimeError(f"creative daily cap ${MAX_USD_DAY:.2f} reached (${day_spend:.2f})")


def _record_spend(usd: float, provider: str = ""):
    try:
        with _budget_lock:
            _spend_log.append((time.time(), float(usd or 0.0), provider))
            cutoff = time.time() - 90000
            while _spend_log and _spend_log[0][0] < cutoff:
                _spend_log.pop(0)
        if _db is not None:
            try:
                _db.insert("creative_spend", {
                    "provider": provider, "cost_usd": float(usd or 0.0),
                    "ts": time.time(),
                })
            except Exception:
                pass
    except Exception:
        pass


# ---------------------------------------------------------------------------
# HTTP helper (stdlib only)
# ---------------------------------------------------------------------------

def _post(url, headers, payload, timeout=90):
    """POST JSON, return parsed JSON response. Raises on non-2xx / network error."""
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={**headers, "Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read().decode(errors="replace")
    return json.loads(raw) if raw else {}


def _get(url, headers, timeout=60):
    req = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read().decode(errors="replace")
    return json.loads(raw) if raw else {}


def _standard_result(status="error", provider="", model="", output_url="",
                     cost_usd=0.0, elapsed_s=0.0, errors=None):
    return {
        "status": status, "provider": provider, "model": model,
        "output_url": output_url, "cost_usd": round(float(cost_usd or 0.0), 4),
        "elapsed_s": round(float(elapsed_s or 0.0), 3),
        "errors": errors or [],
    }


def _key_for(provider: str) -> str:
    cfg = CREATIVE_PROVIDERS.get(provider, {})
    return os.environ.get(cfg.get("key_env", ""), "")


def _headers_for(provider: str, key: str) -> dict:
    cfg = CREATIVE_PROVIDERS.get(provider, {})
    style = cfg.get("auth_style", "bearer")
    if style == "bearer":
        return {"Authorization": f"Bearer {key}"}
    if style == "api-key":
        return {"Api-Key": key}
    if style == "xi-api-key":
        return {"xi-api-key": key}
    return {}


# ---------------------------------------------------------------------------
# Provider-specific call functions
# ---------------------------------------------------------------------------

def _poll_async(poll_url: str, headers: dict, status_field: str = "status",
                done_values=("Ready", "SUCCEEDED", "completed", "succeeded"),
                fail_values=("Error", "FAILED", "failed"),
                result_field: str = "result", max_wait: float = 120,
                interval: float = 3.0) -> dict:
    """Generic poll loop for async creative APIs. Fail-soft: returns {} on timeout/error."""
    deadline = time.time() + max_wait
    while time.time() < deadline:
        try:
            data = _get(poll_url, headers)
        except Exception as e:
            log.warning("poll error: %s", e)
            return {}
        status = data.get(status_field) or data.get("state") or ""
        if status in done_values:
            return data
        if status in fail_values:
            return {}
        time.sleep(interval)
    return {}


def _call_bfl(prompt: str, width: int = 1024, height: int = 1024, **kw) -> dict:
    t0 = time.time()
    provider, cfg = "bfl", CREATIVE_PROVIDERS["bfl"]
    key = _key_for(provider)
    if not key:
        return _standard_result(provider=provider, model=cfg["model"],
                                errors=[f"{cfg['key_env']} not configured"])
    try:
        headers = {"X-Key": key}  # BFL uses X-Key, not standard Bearer
        payload = {"prompt": prompt, "width": width, "height": height}
        submit = _post(cfg["base_url"], headers, payload)
        poll_url = submit.get("polling_url", "")
        if not poll_url:
            return _standard_result(provider=provider, model=cfg["model"],
                                    elapsed_s=time.time() - t0,
                                    errors=["no polling_url in BFL response"])
        result = _poll_async(poll_url, headers, status_field="status",
                             done_values=("Ready",), fail_values=("Error", "Content Moderated"))
        if not result:
            return _standard_result(provider=provider, model=cfg["model"],
                                    elapsed_s=time.time() - t0, errors=["BFL generation timed out/failed"])
        output_url = (result.get("result") or {}).get("sample", "")
        cost = cfg["cost_per_unit"]
        _record_spend(cost, provider)
        return _standard_result(status="ok", provider=provider, model=cfg["model"],
                                output_url=output_url, cost_usd=cost, elapsed_s=time.time() - t0)
    except Exception as e:
        log.warning("bfl error: %s", e)
        return _standard_result(provider=provider, model=cfg["model"],
                                elapsed_s=time.time() - t0, errors=[str(e)])


def _call_ideogram(prompt: str, aspect_ratio: str = "ASPECT_1_1", **kw) -> dict:
    t0 = time.time()
    provider, cfg = "ideogram", CREATIVE_PROVIDERS["ideogram"]
    key = _key_for(provider)
    if not key:
        return _standard_result(provider=provider, model=cfg["model"],
                                errors=[f"{cfg['key_env']} not configured"])
    try:
        headers = _headers_for(provider, key)
        payload = {"image_request": {"prompt": prompt, "aspect_ratio": aspect_ratio,
                                     "model": "V_3"}}
        data = _post(cfg["base_url"], headers, payload)
        images = data.get("data", [])
        if not images:
            return _standard_result(provider=provider, model=cfg["model"],
                                    elapsed_s=time.time() - t0, errors=["no image data returned"])
        output_url = images[0].get("url", "")
        cost = cfg["cost_per_unit"]
        _record_spend(cost, provider)
        return _standard_result(status="ok", provider=provider, model=cfg["model"],
                                output_url=output_url, cost_usd=cost, elapsed_s=time.time() - t0)
    except Exception as e:
        log.warning("ideogram error: %s", e)
        return _standard_result(provider=provider, model=cfg["model"],
                                elapsed_s=time.time() - t0, errors=[str(e)])


def _call_elevenlabs(text: str, voice_id: str = "", **kw) -> dict:
    t0 = time.time()
    provider, cfg = "elevenlabs", CREATIVE_PROVIDERS["elevenlabs"]
    key = _key_for(provider)
    if not key:
        return _standard_result(provider=provider, model=cfg["model"],
                                errors=[f"{cfg['key_env']} not configured"])
    voice_id = voice_id or DEFAULT_VOICE_ID
    try:
        url = cfg["base_url"].format(voice_id=voice_id)
        headers = _headers_for(provider, key)
        payload = {"text": text, "model_id": cfg["model"]}
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode(),
            headers={**headers, "Content-Type": "application/json", "Accept": "audio/mpeg"},
            method="POST")
        with urllib.request.urlopen(req, timeout=90) as r:
            audio_bytes = r.read()
        if not audio_bytes:
            return _standard_result(provider=provider, model=cfg["model"],
                                    elapsed_s=time.time() - t0, errors=["empty audio response"])
        # Persist to a temp/output path so callers get a usable URL/path.
        out_dir = os.environ.get("CREATIVE_OUTPUT_DIR", "/tmp/creative_dispatch")
        try:
            os.makedirs(out_dir, exist_ok=True)
            out_path = os.path.join(out_dir, f"tts_{int(time.time()*1000)}.mp3")
            with open(out_path, "wb") as f:
                f.write(audio_bytes)
        except OSError:
            out_path = ""
        cost = round(len(text) * cfg["cost_per_unit"], 4)
        _record_spend(cost, provider)
        return _standard_result(status="ok", provider=provider, model=cfg["model"],
                                output_url=out_path, cost_usd=cost, elapsed_s=time.time() - t0)
    except Exception as e:
        log.warning("elevenlabs error: %s", e)
        return _standard_result(provider=provider, model=cfg["model"],
                                elapsed_s=time.time() - t0, errors=[str(e)])


def _call_kling(prompt: str, duration_s: int = 5, **kw) -> dict:
    t0 = time.time()
    provider, cfg = "kling", CREATIVE_PROVIDERS["kling"]
    key = _key_for(provider)
    if not key:
        return _standard_result(provider=provider, model=cfg["model"],
                                errors=[f"{cfg['key_env']} not configured"])
    try:
        headers = _headers_for(provider, key)
        payload = {"model_name": cfg["model"], "prompt": prompt, "duration": str(duration_s)}
        submit = _post(cfg["base_url"], headers, payload)
        task_id = (submit.get("data") or {}).get("task_id", "")
        if not task_id:
            return _standard_result(provider=provider, model=cfg["model"],
                                    elapsed_s=time.time() - t0, errors=["no task_id in Kling response"])
        poll_url = f"{cfg['base_url']}/{task_id}"
        result = _poll_async(poll_url, headers, status_field="task_status",
                             done_values=("succeed",), fail_values=("failed",), max_wait=300)
        if not result:
            return _standard_result(provider=provider, model=cfg["model"],
                                    elapsed_s=time.time() - t0, errors=["Kling generation timed out/failed"])
        videos = ((result.get("data") or {}).get("task_result") or {}).get("videos", [])
        output_url = videos[0].get("url", "") if videos else ""
        cost = round(duration_s * cfg["cost_per_unit"], 4)
        _record_spend(cost, provider)
        return _standard_result(status="ok", provider=provider, model=cfg["model"],
                                output_url=output_url, cost_usd=cost, elapsed_s=time.time() - t0)
    except Exception as e:
        log.warning("kling error: %s", e)
        return _standard_result(provider=provider, model=cfg["model"],
                                elapsed_s=time.time() - t0, errors=[str(e)])


def _call_meshy(prompt: str, **kw) -> dict:
    t0 = time.time()
    provider, cfg = "meshy", CREATIVE_PROVIDERS["meshy"]
    key = _key_for(provider)
    if not key:
        return _standard_result(provider=provider, model=cfg["model"],
                                errors=[f"{cfg['key_env']} not configured"])
    try:
        headers = _headers_for(provider, key)
        payload = {"mode": "preview", "prompt": prompt, "art_style": "realistic"}
        submit = _post(cfg["base_url"], headers, payload)
        task_id = submit.get("result", "")
        if not task_id:
            return _standard_result(provider=provider, model=cfg["model"],
                                    elapsed_s=time.time() - t0, errors=["no task id in Meshy response"])
        poll_url = f"{cfg['base_url']}/{task_id}"
        result = _poll_async(poll_url, headers, status_field="status",
                             done_values=("SUCCEEDED",), fail_values=("FAILED",), max_wait=300)
        if not result:
            return _standard_result(provider=provider, model=cfg["model"],
                                    elapsed_s=time.time() - t0, errors=["Meshy generation timed out/failed"])
        model_urls = result.get("model_urls") or {}
        output_url = model_urls.get("glb", "") or model_urls.get("fbx", "")
        cost = cfg["cost_per_unit"]
        _record_spend(cost, provider)
        return _standard_result(status="ok", provider=provider, model=cfg["model"],
                                output_url=output_url, cost_usd=cost, elapsed_s=time.time() - t0)
    except Exception as e:
        log.warning("meshy error: %s", e)
        return _standard_result(provider=provider, model=cfg["model"],
                                elapsed_s=time.time() - t0, errors=[str(e)])


_CALLERS = {
    "bfl": _call_bfl,
    "ideogram": _call_ideogram,
    "elevenlabs": _call_elevenlabs,
    "kling": _call_kling,
    "meshy": _call_meshy,
}

# ---------------------------------------------------------------------------
# Vendor selection
# ---------------------------------------------------------------------------

def _pick_provider(capability: str, requested: str = "auto") -> Optional[str]:
    """Pick a provider for a capability, honoring explicit request or falling
    back to vendor_capabilities.best_vendor_for_capability / static candidates."""
    if requested and requested != "auto":
        return requested if requested in CREATIVE_PROVIDERS else None

    candidates = [p for p, cfg in CREATIVE_PROVIDERS.items() if cfg["capability"] == capability]
    if not candidates:
        return None

    if _vc is not None:
        try:
            best = _vc.best_vendor_for_capability(capability, prefer_cost=True)
            if best in candidates:
                return best
        except Exception:
            pass

    # Fail-soft fallback: first candidate with an API key configured
    for p in candidates:
        if _key_for(p):
            return p
    return candidates[0] if candidates else None


def _run_provider(provider: str, capability: str, **kwargs) -> dict:
    if not provider:
        return _standard_result(errors=[f"no vendor available for capability={capability}"])
    try:
        _check_budget()
    except RuntimeError as e:
        return _standard_result(provider=provider, errors=[str(e)])
    caller = _CALLERS.get(provider)
    if not caller:
        return _standard_result(provider=provider, errors=[f"unknown provider {provider}"])
    return caller(**kwargs)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_image(prompt: str, provider: str = "auto", width: int = 1024,
                   height: int = 1024, text_in_image: bool = False) -> dict:
    """Generate an image. Routes to Ideogram if text_in_image else FLUX/BFL."""
    if not prompt:
        return _standard_result(errors=["empty prompt"])
    capability = "text_in_image" if text_in_image else "image_generation"
    chosen = _pick_provider(capability, provider)
    if chosen == "ideogram":
        return _run_provider(chosen, capability, prompt=prompt)
    if chosen == "bfl" or chosen is None:
        chosen = chosen or "bfl"
        return _run_provider(chosen, capability, prompt=prompt, width=width, height=height)
    return _run_provider(chosen, capability, prompt=prompt)


def generate_video(prompt: str, provider: str = "auto", duration_s: int = 5) -> dict:
    """Generate a video via Kling (or configured video vendor)."""
    if not prompt:
        return _standard_result(errors=["empty prompt"])
    chosen = _pick_provider("video_generation", provider) or "kling"
    return _run_provider(chosen, "video_generation", prompt=prompt, duration_s=duration_s)


def generate_3d(prompt: str, provider: str = "auto") -> dict:
    """Generate a 3D model via Meshy (or configured 3D vendor)."""
    if not prompt:
        return _standard_result(errors=["empty prompt"])
    chosen = _pick_provider("3d_generation", provider) or "meshy"
    return _run_provider(chosen, "3d_generation", prompt=prompt)


def generate_audio(text: str, voice_id: str = "default", provider: str = "auto") -> dict:
    """Generate TTS audio via ElevenLabs (or configured audio vendor)."""
    if not text:
        return _standard_result(errors=["empty text"])
    chosen = _pick_provider("audio_generation", provider) or "elevenlabs"
    vid = "" if voice_id in ("default", "", None) else voice_id
    return _run_provider(chosen, "audio_generation", text=text, voice_id=vid)


def dispatch(task: dict) -> dict:
    """Auto-detect which creative capability a task needs and route to the right vendor.

    Task dict fields consulted: slug, title, description, prompt, kind, needs.
    Fail-soft: returns an error result dict (never raises) if nothing matches.
    """
    if not isinstance(task, dict):
        return _standard_result(errors=["task must be a dict"])

    prompt = task.get("prompt") or task.get("description") or task.get("title") or ""
    if not prompt:
        return _standard_result(errors=["no prompt/description/title on task"])

    required: set = set()
    if _vc is not None:
        try:
            required = _vc.detect_required_capabilities(task)
        except Exception:
            required = set()

    provider_hint = task.get("provider", "auto")

    if "3d_generation" in required:
        return generate_3d(prompt, provider=provider_hint)
    if "video_generation" in required or "image_to_video" in required:
        return generate_video(prompt, provider=provider_hint,
                              duration_s=int(task.get("duration_s", 5) or 5))
    if "audio_generation" in required or "text_to_speech" in required:
        return generate_audio(prompt, voice_id=task.get("voice_id", "default"),
                              provider=provider_hint)
    if "text_in_image" in required:
        return generate_image(prompt, provider=provider_hint, text_in_image=True)
    if "image_generation" in required or "image_editing" in required:
        return generate_image(prompt, provider=provider_hint)

    return _standard_result(errors=["task does not require any creative capability"])


def available() -> List[str]:
    """List creative vendors with API keys configured. Fail-soft: [] on error."""
    try:
        return [p for p in CREATIVE_PROVIDERS if _key_for(p)]
    except Exception:
        return []


def stats() -> dict:
    """Usage/spend stats for operator dashboards. Fail-soft: {} on error."""
    try:
        now = time.time()
        with _budget_lock:
            hour_spend = sum(u for t, u, _ in _spend_log if now - t < 3600)
            day_spend = sum(u for t, u, _ in _spend_log if now - t < 86400)
            by_provider: Dict[str, float] = {}
            for _, u, p in _spend_log:
                by_provider[p] = by_provider.get(p, 0.0) + u
        return {
            "available_vendors": available(),
            "total_vendors": len(CREATIVE_PROVIDERS),
            "hour_spend_usd": round(hour_spend, 4),
            "day_spend_usd": round(day_spend, 4),
            "hour_cap_usd": MAX_USD_HOUR,
            "day_cap_usd": MAX_USD_DAY,
            "spend_by_provider": {k: round(v, 4) for k, v in by_provider.items()},
            "call_count": len(_spend_log),
        }
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# CLI for quick testing
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO)
    ap = argparse.ArgumentParser(description="creative_dispatch quick test")
    ap.add_argument("kind", choices=["image", "video", "3d", "audio", "available", "stats"])
    ap.add_argument("prompt", nargs="?", default="a red fox in a snowy forest")
    ap.add_argument("--provider", default="auto")
    args = ap.parse_args()

    if args.kind == "available":
        print(json.dumps(available(), indent=2))
    elif args.kind == "stats":
        print(json.dumps(stats(), indent=2))
    elif args.kind == "image":
        print(json.dumps(generate_image(args.prompt, provider=args.provider), indent=2))
    elif args.kind == "video":
        print(json.dumps(generate_video(args.prompt, provider=args.provider), indent=2))
    elif args.kind == "3d":
        print(json.dumps(generate_3d(args.prompt, provider=args.provider), indent=2))
    elif args.kind == "audio":
        print(json.dumps(generate_audio(args.prompt, provider=args.provider), indent=2))
