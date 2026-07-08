#!/usr/bin/env python3
"""Plan and optionally install Ollama models that fill routing gaps."""
import json
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

MODELS = [
    {"model": "qwen3-coder:30b", "role": "agentic coding", "size_gb": 19, "ram_gb": 24, "context": 256000, "cap": 9},
    {"model": "deepseek-coder-v2:16b", "role": "code fallback", "size_gb": 9, "ram_gb": 12, "context": 160000, "cap": 8},
    {"model": "gemma3:27b", "role": "vision/reasoning/review", "size_gb": 17, "ram_gb": 22, "context": 128000, "cap": 8},
    {"model": "gemma3:12b", "role": "cheap vision/reasoning/review", "size_gb": 8.1, "ram_gb": 10, "context": 128000, "cap": 7},
    {"model": "codestral:22b", "role": "FIM/code completion", "size_gb": 13, "ram_gb": 16, "context": 32000, "cap": 8},
    {"model": "oroboroslabs/claude-fable-5Q", "role": "unverified Fable-labeled canary only",
     "size_gb": 5.8, "ram_gb": 9, "context": 32000, "cap": 6,
     "experimental": True, "trust": "unverified",
     "note": "Ollama community package with no README/provenance; not treated as Anthropic Claude Fable 5."},
]


def _disk_free_gb(path=None):
    usage = shutil.disk_usage(path or os.path.expanduser("~"))
    return usage.free / (1024 ** 3)


def _ram_free_gb():
    try:
        import resource_governor
        return resource_governor.ram_free_gb()
    except Exception:
        return None


def _installed():
    try:
        import ollama_catalog
        return {c["model"] for c in ollama_catalog.candidates()}
    except Exception:
        return set()


def plan():
    free_disk = _disk_free_gb()
    free_ram = _ram_free_gb()
    installed = _installed()
    installed_base = {m for m in installed if ":" not in m}
    chosen = []
    allow_experimental = os.environ.get("ORCH_ALLOW_EXPERIMENTAL_OLLAMA_PULLS", "false").lower() in ("1", "true", "yes", "on")
    for spec in MODELS:
        already = spec["model"] in installed or spec["model"].split(":")[0] in installed_base
        disk_ok = free_disk >= spec["size_gb"] + float(os.environ.get("ORCH_OLLAMA_KEEP_FREE_GB", "20"))
        ram_ok = free_ram is None or free_ram >= min(spec["ram_gb"], float(os.environ.get("ORCH_OLLAMA_RAM_SOFT_GB", "64")))
        gated = bool(spec.get("experimental")) and not allow_experimental
        chosen.append({**spec, "installed": already, "disk_ok": disk_ok, "ram_ok": ram_ok,
                       "installable": (not already and disk_ok and not gated),
                       "recommended": (not already and disk_ok and ram_ok and not gated),
                       "gated": gated})
    # If 27B Gemma is not recommended, prefer the 12B variant for that role.
    by_model = {c["model"]: c for c in chosen}
    if not by_model["gemma3:27b"]["recommended"] and not by_model["gemma3:27b"]["installed"]:
        by_model["gemma3:12b"]["recommended"] = (not by_model["gemma3:12b"]["installed"]
                                                 and by_model["gemma3:12b"]["disk_ok"]
                                                 and by_model["gemma3:12b"]["ram_ok"])
    return {"free_disk_gb": round(free_disk, 2),
            "free_ram_gb": None if free_ram is None else round(free_ram, 2),
            "models": chosen}


def pull(models=None, dry_run=True):
    p = plan()
    wanted = set(models or [m["model"] for m in p["models"] if m["recommended"]])
    results = []
    for spec in p["models"]:
        model = spec["model"]
        if model not in wanted:
            continue
        if spec["installed"]:
            results.append({"model": model, "status": "installed"})
            continue
        if spec.get("gated"):
            results.append({"model": model, "status": "skipped",
                            "reason": "experimental/unverified; set ORCH_ALLOW_EXPERIMENTAL_OLLAMA_PULLS=true to canary"})
            continue
        if not spec["disk_ok"]:
            results.append({"model": model, "status": "skipped", "reason": "disk check"})
            continue
        warning = None if spec["ram_ok"] else "installed model may be too large to run concurrently with current free RAM"
        if dry_run:
            results.append({"model": model, "status": "would_pull", "cmd": ["ollama", "pull", model],
                            "warning": warning})
            continue
        proc = subprocess.run(["ollama", "pull", model], text=True, capture_output=True,
                              timeout=int(os.environ.get("ORCH_OLLAMA_PULL_TIMEOUT", "7200")))
        results.append({"model": model, "status": "pulled" if proc.returncode == 0 else "failed",
                        "returncode": proc.returncode, "warning": warning, "stderr": proc.stderr[-1000:]})
    return {"plan": p, "results": results}


if __name__ == "__main__":
    dry = "--pull" not in sys.argv
    models = [a for a in sys.argv[1:] if not a.startswith("--")]
    print(json.dumps(pull(models=models or None, dry_run=dry), indent=2))
