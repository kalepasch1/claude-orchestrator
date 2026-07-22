#!/usr/bin/env python3
"""Discover and rank local Ollama models."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _host():
    try:
        import model_gateway
        return model_gateway._ollama_host()
    except Exception:
        return os.environ.get("OLLAMA_HOST", "http://localhost:11434").split()[0]


def models():
    """Return local Ollama model names from /api/tags, env fallback included."""
    found = []

    def add_from_tags(data):
        for item in data.get("models", []) if isinstance(data, dict) else []:
            name = item.get("name") or item.get("model")
            if name:
                found.append(name)

    try:
        with urllib.request.urlopen(_host() + "/api/tags", timeout=2) as r:
            data = json.loads(r.read().decode())
        add_from_tags(data)
    except Exception:
        try:
            proc = subprocess.run(["curl", "-s", _host() + "/api/tags"],
                                  capture_output=True, text=True, timeout=3)
            if proc.returncode == 0:
                add_from_tags(json.loads(proc.stdout))
        except Exception:
            pass
    try:
        proc = subprocess.run(["ollama", "list"], capture_output=True, text=True, timeout=3)
        if proc.returncode == 0:
            for line in proc.stdout.splitlines()[1:]:
                parts = line.split()
                if parts:
                    found.append(parts[0])
    except Exception:
        pass
    found.extend(_manifest_models())
    env_models = []
    for key in ("OLLAMA_MODEL", "OLLAMA_STRONG_MODEL", "OLLAMA_MODELS"):
        raw = os.environ.get(key, "")
        env_models.extend([x.strip() for x in raw.split(",") if x.strip()])
    out, seen = [], set()
    for m in found + env_models:
        if m and m not in seen:
            seen.add(m); out.append(m)
    return out or ["llama3.1"]


def _manifest_models():
    """Read local Ollama manifests when localhost is unavailable to sandboxed Python."""
    root = Path(os.environ.get(
        "OLLAMA_MANIFESTS_DIR",
        Path.home() / ".ollama" / "models" / "manifests",
    ))
    if not root.exists():
        return []
    out = []
    for manifest in root.glob("*/*/*/*"):
        if not manifest.is_file():
            continue
        try:
            registry, namespace, name, tag = manifest.relative_to(root).parts
        except ValueError:
            continue
        if namespace == "library":
            out.append(f"{name}:{tag}")
        else:
            out.append(f"{namespace}/{name}:{tag}")
    return out


def _overrides():
    raw = os.environ.get("OLLAMA_MODEL_CAPS_JSON", "")
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _truthy(name, default=False):
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.lower() in ("1", "true", "yes", "on")


def provenance(model):
    name = str(model or "").lower()
    if name.startswith("oroboroslabs/claude-fable-5q") or "claude-fable" in name:
        return {
            "trust": "unverified",
            "status": "experimental",
            "note": "Community Ollama package; do not assume it is Anthropic Claude Fable 5.",
        }
    if "claude" in name or "opus" in name or "fable" in name:
        return {
            "trust": "community-claim",
            "status": "experimental",
            "note": "Model name references a proprietary vendor model; require canary evidence before promotion.",
        }
    return {"trust": "catalog", "status": "candidate", "note": ""}


def infer_cap(model):
    """Rough local capability estimate; override with OLLAMA_MODEL_CAPS_JSON."""
    name = str(model or "").lower()
    over = _overrides()
    if model in over:
        try:
            return int(over[model])
        except Exception:
            pass
    prov = provenance(model)
    if prov["trust"] in ("unverified", "community-claim") and not _truthy("ORCH_TRUST_COMMUNITY_CLAUDE_OLLAMA", False):
        if "fable" in name:
            return 6
        return 7
    if "opus" in name or "4.6" in name or "4-6" in name:
        return 10
    if "qwen3-coder" in name:
        return 9
    if re.search(r"\b(70b|72b|120b|405b)\b", name):
        return 9
    if "deepseek-coder-v2" in name or "codestral" in name:
        return 8
    if "gemma3:27b" in name:
        return 8
    if "gemma3:12b" in name:
        return 7
    if any(x in name for x in ("qwen", "coder", "deepseek", "mixtral", "32b", "34b")):
        return 7
    if any(x in name for x in ("llama3.1", "llama3", "mistral", "14b", "13b")):
        return 6
    return 5


def _canary_only_models():
    raw = os.environ.get("ORCH_CANARY_ONLY_OLLAMA_MODELS", "oroboroslabs/claude-fable-5Q")
    return [m.strip() for m in raw.split(",") if m.strip()]


def _heavy_hot_lane_ram_floor_gb():
    return float(os.environ.get("ORCH_HEAVY_OLLAMA_HOT_LANE_RAM_GB", "16"))


def _heavy_hot_lane_headroom_gb():
    return float(os.environ.get("ORCH_HEAVY_OLLAMA_HOT_LANE_HEADROOM_GB", "12"))


def _model_ram_gb(model):
    try:
        import local_model_slots
        return local_model_slots.ram_gb(model)
    except Exception:
        return 0


def _is_heavy_for_hot_lane(model):
    """Very heavy local models (e.g. codestral:22b) can clamp system RAM and throttle the
    fleet down to a single lane when they get pulled into real agentic work. Keep them
    canary/calibration-only by default; only let them into the hot lane when the box
    clearly has the headroom, or the operator explicitly opts in."""
    if _truthy("ORCH_TRUST_HEAVY_OLLAMA_HOT_LANE", False):
        return False
    need = _model_ram_gb(model)
    if need < _heavy_hot_lane_ram_floor_gb():
        return False
    try:
        import resource_governor
        total = resource_governor.total_gb()
    except Exception:
        total = None
    if total is None:
        return True  # unknown headroom -> stay cautious, canary-only
    return total < (need + _heavy_hot_lane_headroom_gb())


def _is_canary_only(candidate):
    trust_gated = (candidate.get("trust") in ("unverified", "community-claim")
                   and not _truthy("ORCH_TRUST_COMMUNITY_CLAUDE_OLLAMA", False))
    if trust_gated:
        return True
    return _is_heavy_for_hot_lane(candidate.get("model"))


def candidates(include_canary_only=False):
    out = []
    for m in models():
        prov = provenance(m)
        c = {"provider": "local", "model": m, "cap": infer_cap(m), "tier": "free",
             "trust": prov["trust"], "status": prov["status"], "note": prov["note"]}
        if _is_canary_only(c):
            c["canary_only"] = True
            if not include_canary_only:
                continue
        out.append(c)
    if include_canary_only:
        present = {c["model"] for c in out}
        for m in _canary_only_models():
            if m in present:
                continue
            prov = provenance(m)
            out.append({"provider": "local", "model": m, "cap": infer_cap(m), "tier": "free",
                        "trust": prov["trust"], "status": prov["status"], "note": prov["note"],
                        "canary_only": True, "not_installed": m not in models()})
    return out


def best(task_class="review", need=5):
    try:
        import model_catalog
        return model_catalog.choose(task_class, need=need, available_providers=["local"])
    except Exception:
        cs = [c for c in candidates() if c["cap"] >= int(need or 0)]
        return sorted(cs or candidates(), key=lambda c: (-c["cap"], c["model"]))[0]


if __name__ == "__main__":
    print(json.dumps(candidates(), indent=2))
