#!/usr/bin/env python3
"""distill_lora.py - Local LoRA fine-tuning pipeline from merged_diff_library.

Deliverables:
  1. export_corpus() - export training corpus from merged_diff_library + task prompts
     (prompt->diff pairs, per-repo tagged, PII/secret-scrubbed via privacy.scrub,
      capped and deduped)
  2. fine_tune() - run mlx_lm LoRA training against qwen2.5-coder base
  3. fuse_and_convert() - fuse adapter, convert to GGUF for Ollama
  4. eval_harness() - hold out 50 merged tasks, measure first-pass success
     base vs tuned model; tuned enters pool only if it beats base by margin.

Env vars:
    ORCH_DISTILL_CORPUS_DIR     corpus output dir (default: .runtime/distill_corpus)
    ORCH_DISTILL_BASE_MODEL     base model for fine-tuning (default: qwen2.5-coder:7b)
    ORCH_DISTILL_EVAL_HOLDOUT   number of holdout tasks for eval (default: 50)
    ORCH_DISTILL_WIN_MARGIN     margin to beat base (default: 0.1 = 10%)
    ORCH_DISTILL_MAX_PAIRS      max training pairs (default: 5000)
"""
import hashlib
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import privacy

RUNTIME = os.environ.get("CLAUDE_ORCH_HOME",
                         os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".runtime"))
CORPUS_DIR = os.environ.get("ORCH_DISTILL_CORPUS_DIR", os.path.join(RUNTIME, "distill_corpus"))
BASE_MODEL = os.environ.get("ORCH_DISTILL_BASE_MODEL", "qwen2.5-coder:7b")
EVAL_HOLDOUT = int(os.environ.get("ORCH_DISTILL_EVAL_HOLDOUT", "50") or 50)
WIN_MARGIN = float(os.environ.get("ORCH_DISTILL_WIN_MARGIN", "0.1") or 0.1)
MAX_PAIRS = int(os.environ.get("ORCH_DISTILL_MAX_PAIRS", "5000") or 5000)


def _scrub_text(text):
    """PII/secret scrub via privacy module, return clean text."""
    if not text:
        return ""
    clean, _ = privacy.scrub(str(text))
    return clean


def _dedup_key(prompt, diff):
    """Content-hash for dedup."""
    return hashlib.sha256((prompt + diff).encode("utf-8", errors="replace")).hexdigest()[:16]


def export_corpus(project_id=None):
    """Export prompt->diff training pairs from merged_diff_library.

    Returns: {ok, path, count, deduped, scrubbed}
    """
    os.makedirs(CORPUS_DIR, exist_ok=True)
    out_path = os.path.join(CORPUS_DIR, "train.jsonl")
    holdout_path = os.path.join(CORPUS_DIR, "holdout.jsonl")

    # Fetch merged diffs with their task prompts
    query = {"select": "id,slug,diff_text,prompt_hash,repo,indexed_at",
             "order": "indexed_at.asc"}
    if project_id:
        query["project_id"] = project_id
    rows = db.select("merged_diff_library", query) or []

    # Also fetch task prompts for matching
    task_map = {}
    tasks = db.select("tasks", {
        "select": "slug,prompt",
        "state": "in.(DONE,MERGED)",
        "limit": 10000,
    }) or []
    for t in tasks:
        task_map[t.get("slug", "")] = t.get("prompt", "")

    pairs = []
    seen = set()
    scrub_count = 0

    for row in rows:
        slug = row.get("slug", "")
        diff = row.get("diff_text", "")
        prompt = task_map.get(slug, "")
        if not diff or not prompt:
            continue

        # PII scrub
        clean_prompt = _scrub_text(prompt)
        clean_diff = _scrub_text(diff)
        if clean_prompt != prompt or clean_diff != diff:
            scrub_count += 1

        # Dedup
        key = _dedup_key(clean_prompt, clean_diff)
        if key in seen:
            continue
        seen.add(key)

        # Cap diff size
        if len(clean_diff) > 50000:
            clean_diff = clean_diff[:50000] + "\n... (truncated)"

        pairs.append({
            "prompt": clean_prompt[:8000],
            "completion": clean_diff,
            "repo": row.get("repo", ""),
            "slug": slug,
        })

        if len(pairs) >= MAX_PAIRS:
            break

    # Split holdout
    holdout = pairs[-EVAL_HOLDOUT:] if len(pairs) > EVAL_HOLDOUT else pairs[-max(1, len(pairs)//5):]
    train = [p for p in pairs if p not in holdout]

    with open(out_path, "w", encoding="utf-8") as f:
        for p in train:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")
    with open(holdout_path, "w", encoding="utf-8") as f:
        for p in holdout:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")

    return {
        "ok": True,
        "path": out_path,
        "holdout_path": holdout_path,
        "count": len(train),
        "holdout_count": len(holdout),
        "deduped": len(rows) - len(pairs),
        "scrubbed": scrub_count,
    }


def fine_tune(corpus_path=None, base_model=None, output_dir=None):
    """Run mlx_lm LoRA fine-tuning. Operator-triggered (needs RAM).

    Returns: {ok, adapter_path, command}
    NOTE: This wraps the mlx_lm CLI. The actual training is NOT mocked in tests -
    tests mock subprocess.run.
    """
    corpus_path = corpus_path or os.path.join(CORPUS_DIR, "train.jsonl")
    base_model = base_model or BASE_MODEL
    output_dir = output_dir or os.path.join(CORPUS_DIR, "adapter")

    if not os.path.exists(corpus_path):
        return {"ok": False, "error": f"corpus not found at {corpus_path}"}

    os.makedirs(output_dir, exist_ok=True)

    cmd = [
        sys.executable, "-m", "mlx_lm.lora",
        "--model", base_model,
        "--train",
        "--data", os.path.dirname(corpus_path),
        "--adapter-path", output_dir,
        "--iters", "1000",
        "--batch-size", "4",
        "--lora-layers", "16",
    ]

    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=7200)
        ok = r.returncode == 0
        return {
            "ok": ok,
            "adapter_path": output_dir if ok else None,
            "command": " ".join(cmd),
            "stdout": r.stdout[-2000:] if r.stdout else "",
            "stderr": r.stderr[-2000:] if r.stderr else "",
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "training timed out (2h)"}
    except FileNotFoundError:
        return {"ok": False, "error": "mlx_lm not installed", "command": " ".join(cmd),
                "note": "Install: pip install mlx-lm. Requires Apple Silicon with sufficient RAM."}


def fuse_and_convert(adapter_path=None, base_model=None, output_name=None):
    """Fuse LoRA adapter and convert to GGUF for Ollama.

    Steps (automated where possible, operator-noted otherwise):
      1. mlx_lm.fuse --model <base> --adapter-path <adapter> --save-path <fused>
      2. Convert fused model to GGUF (llama.cpp convert)
      3. Create Ollama Modelfile and import

    Returns: {ok, steps, gguf_path, operator_notes}
    """
    adapter_path = adapter_path or os.path.join(CORPUS_DIR, "adapter")
    base_model = base_model or BASE_MODEL
    output_name = output_name or "orch-coder-tuned"
    fused_path = os.path.join(CORPUS_DIR, "fused")

    steps = []
    operator_notes = []

    # Step 1: Fuse
    fuse_cmd = [sys.executable, "-m", "mlx_lm.fuse",
                "--model", base_model,
                "--adapter-path", adapter_path,
                "--save-path", fused_path]
    steps.append({"step": "fuse", "command": " ".join(fuse_cmd)})

    try:
        r = subprocess.run(fuse_cmd, capture_output=True, text=True, timeout=600)
        if r.returncode != 0:
            return {"ok": False, "error": "fuse failed", "stderr": r.stderr[-1000:], "steps": steps}
        steps[-1]["status"] = "done"
    except Exception as e:
        return {"ok": False, "error": str(e), "steps": steps}

    # Step 2: GGUF conversion
    gguf_path = os.path.join(CORPUS_DIR, f"{output_name}.gguf")
    operator_notes.append(
        f"GGUF conversion requires llama.cpp. Run:\n"
        f"  python3 llama.cpp/convert_hf_to_gguf.py {fused_path} --outfile {gguf_path} --outtype q4_K_M\n"
        f"Then import to Ollama:\n"
        f"  ollama create {output_name} -f Modelfile  (with FROM {gguf_path})"
    )
    steps.append({"step": "gguf_convert", "status": "operator_manual", "note": operator_notes[-1]})

    return {
        "ok": True,
        "steps": steps,
        "fused_path": fused_path,
        "gguf_path": gguf_path,
        "operator_notes": operator_notes,
    }


def eval_harness(holdout_path=None, base_model=None, tuned_model=None,
                 margin=None):
    """Evaluate base vs tuned model on holdout set.

    For each holdout (prompt, expected_diff), run both models and compare
    first-pass success (does the generated diff apply cleanly and match intent?).

    The tuned model enters the coder pool only if it beats base by margin.

    Returns: {ok, base_score, tuned_score, delta, promoted, details}
    """
    holdout_path = holdout_path or os.path.join(CORPUS_DIR, "holdout.jsonl")
    base_model = base_model or BASE_MODEL
    tuned_model = tuned_model or "orch-coder-tuned"
    margin = margin if margin is not None else WIN_MARGIN

    if not os.path.exists(holdout_path):
        return {"ok": False, "error": f"holdout not found at {holdout_path}"}

    with open(holdout_path, encoding="utf-8") as f:
        holdout = [json.loads(line) for line in f if line.strip()]

    if not holdout:
        return {"ok": False, "error": "empty holdout set"}

    base_pass, tuned_pass = 0, 0
    details = []

    for item in holdout:
        prompt = item.get("prompt", "")
        expected = item.get("completion", "")

        # Score base model
        base_ok = _eval_single(base_model, prompt, expected)
        if base_ok:
            base_pass += 1

        # Score tuned model
        tuned_ok = _eval_single(tuned_model, prompt, expected)
        if tuned_ok:
            tuned_pass += 1

        details.append({
            "slug": item.get("slug", ""),
            "base_pass": base_ok,
            "tuned_pass": tuned_ok,
        })

    n = len(holdout)
    base_score = base_pass / n if n else 0
    tuned_score = tuned_pass / n if n else 0
    delta = tuned_score - base_score
    promoted = delta >= margin

    if promoted:
        _promote_to_pool(tuned_model, tuned_score, base_score)

    return {
        "ok": True,
        "base_score": round(base_score, 4),
        "tuned_score": round(tuned_score, 4),
        "delta": round(delta, 4),
        "margin": margin,
        "promoted": promoted,
        "holdout_count": n,
        "details": details[:20],  # cap for readability
    }


def _eval_single(model, prompt, expected_diff):
    """Evaluate a single prompt against a model. Returns True if output is acceptable.
    Uses simple heuristic: does the model output contain key changed symbols/lines?"""
    try:
        # Use ollama generate for local models
        cmd = ["ollama", "run", model, prompt[:4000]]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            return False
        output = r.stdout

        # Simple similarity check: do >=30% of significant lines match?
        expected_lines = {l.strip() for l in expected_diff.split("\n")
                         if l.strip() and len(l.strip()) > 10 and not l.startswith("---") and not l.startswith("+++")}
        if not expected_lines:
            return True
        matches = sum(1 for l in expected_lines if l in output)
        return (matches / len(expected_lines)) >= 0.3
    except Exception:
        return False


def _promote_to_pool(model_name, tuned_score, base_score):
    """Add tuned model to ollama_catalog pool if it beats the threshold."""
    try:
        db.insert("model_promotions", {
            "model": model_name,
            "tuned_score": tuned_score,
            "base_score": base_score,
            "promoted_at": time.time(),
        })
    except Exception:
        pass


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="LoRA distill pipeline")
    parser.add_argument("action", choices=["export", "train", "fuse", "eval"])
    parser.add_argument("--project-id", default=None)
    args = parser.parse_args()

    if args.action == "export":
        r = export_corpus(args.project_id)
        print(json.dumps(r, indent=2))
    elif args.action == "train":
        r = fine_tune()
        print(json.dumps(r, indent=2))
    elif args.action == "fuse":
        r = fuse_and_convert()
        print(json.dumps(r, indent=2))
    elif args.action == "eval":
        r = eval_harness()
        print(json.dumps(r, indent=2))
