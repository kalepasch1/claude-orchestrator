#!/usr/bin/env python3
"""
parallel_provider.py - run 2-3 providers in parallel for hard-tier tasks and synthesize results.

For high-stakes decisions (legal, security, hard-tier), parallel execution reduces latency and
increases confidence through diverse model perspectives. Each provider gets the same prompt,
runs concurrently, and results are synthesized to pick the best answer based on confidence
and quality metrics.

parallel_complete(providers, model_list, prompt, project=None, timeout=90)
  -> {
       "text": "best answer",
       "provider": "provider_that_won",
       "model": "model_that_won",
       "score": 8.5,
       "cost_usd": 0.015,
       "all_results": [{provider, model, text, cost, score}, ...]
     }
"""
import os, sys, json, time, re
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import model_gateway as mg


def _score_result(result):
    """
    Score a result based on heuristics: length, JSON validity, confidence markers.
    Returns a float 0-10 where higher is better.
    """
    text = result.get("text", "")
    if not text:
        return 0.0

    # Prefer longer, more detailed answers (but cap at reasonable length)
    length_score = min(10, len(text) / 500 * 10)

    # If result contains JSON with confidence/score fields, parse and weight it
    try:
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            data = json.loads(m.group(0))
            # If the result includes a confidence or score field, use it
            if "confidence" in data:
                conf_score = min(10, data["confidence"] / 10.0)
                length_score = (length_score + conf_score) / 2
            elif "score" in data:
                score_val = min(10, data["score"])
                length_score = (length_score + score_val) / 2
    except Exception:
        pass

    # Bonus for structured output (contains JSON)
    if "{" in text and "}" in text:
        length_score = min(10, length_score + 1)

    # Penalty for error messages
    if "error" in text.lower() or "failed" in text.lower():
        length_score = max(0, length_score - 2)

    return round(length_score, 1)


def parallel_complete(providers, model_list, prompt, project=None, timeout=90):
    """
    Run multiple providers in parallel with the same prompt. Synthesize results to pick the best.

    Args:
      providers: list of provider names, e.g. ["claude", "openai", "google"]
      model_list: list of models (same order), e.g. ["claude-opus", "gpt-4o", "gemini-2.0"]
      prompt: the input prompt (same for all providers)
      project: optional project name for telemetry
      timeout: per-provider timeout in seconds

    Returns:
      {
        "text": "best answer",
        "provider": "winning provider",
        "model": "winning model",
        "score": 8.5,  # synthesis quality score
        "cost_usd": total cost,
        "all_results": [
          {"provider": "...", "model": "...", "text": "...", "cost_usd": 0.01, "score": 7.2},
          ...
        ]
      }
    """
    if not providers or not model_list:
        return {"text": "", "cost_usd": 0, "provider": "none", "model": "none",
                "score": 0, "error": "no providers specified"}

    if len(providers) != len(model_list):
        return {"text": "", "cost_usd": 0, "provider": "none", "model": "none",
                "score": 0, "error": "providers and model_list length mismatch"}

    all_results = []
    errors = []

    def call_provider(prov, mdl):
        try:
            t0 = time.time()
            res = mg.complete(prov, mdl, prompt, project=project, timeout=timeout,
                            operation="parallel_completion", task_class="hard", fallback=False)
            elapsed = time.time() - t0
            score = _score_result(res)
            return {
                "provider": prov,
                "model": mdl,
                "text": res.get("text", ""),
                "cost_usd": res.get("cost_usd", 0),
                "score": score,
                "latency_ms": int(elapsed * 1000)
            }
        except Exception as e:
            return {
                "provider": prov,
                "model": mdl,
                "text": "",
                "cost_usd": 0,
                "score": 0,
                "error": str(e)
            }

    # Run all providers in parallel
    with ThreadPoolExecutor(max_workers=min(3, len(providers))) as executor:
        futures = [executor.submit(call_provider, prov, mdl)
                   for prov, mdl in zip(providers, model_list)]

        for future in futures:
            try:
                result = future.result(timeout=timeout + 10)  # allow extra time for thread to finish
                all_results.append(result)
                if result.get("error"):
                    errors.append(result["error"])
            except FutureTimeoutError:
                errors.append("provider timeout")
            except Exception as e:
                errors.append(str(e))

    # Pick the best result
    valid_results = [r for r in all_results if r.get("text")]
    if not valid_results:
        return {
            "text": "",
            "cost_usd": 0,
            "provider": "none",
            "model": "none",
            "score": 0,
            "error": f"all providers failed: {'; '.join(errors)}",
            "all_results": all_results
        }

    # Sort by score (descending)
    best = sorted(valid_results, key=lambda r: r.get("score", 0), reverse=True)[0]

    total_cost = sum(r.get("cost_usd", 0) for r in all_results)

    # Mark it as winning
    best["winner"] = True

    return {
        "text": best["text"],
        "provider": best["provider"],
        "model": best["model"],
        "score": best.get("score", 0),
        "cost_usd": round(total_cost, 4),
        "all_results": all_results
    }


def parallel_complete_with_fallback(providers, model_list, prompt, project=None, timeout=90):
    """
    Same as parallel_complete but falls back to cheapest single provider if parallel fails entirely.
    """
    result = parallel_complete(providers, model_list, prompt, project=project, timeout=timeout)

    if result.get("text"):
        return result

    # Fallback: try the first provider alone with fallback enabled
    if providers:
        fallback_res = mg.complete(providers[0], model_list[0], prompt, project=project,
                                   timeout=timeout, fallback=True, record_op=True)
        return {
            "text": fallback_res.get("text", ""),
            "provider": fallback_res.get("provider", providers[0]),
            "model": fallback_res.get("model", model_list[0]),
            "score": 5.0,
            "cost_usd": fallback_res.get("cost_usd", 0),
            "fallback": True,
            "all_results": [fallback_res]
        }

    return result


if __name__ == "__main__":
    # Test: parallel complete with mock providers
    import os
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Set ANTHROPIC_API_KEY to test")
        sys.exit(1)

    # Test with available providers
    avail = mg.available()
    if len(avail) < 2:
        print(f"Need 2+ providers; have {avail}")
        sys.exit(1)

    providers = avail[:2]
    models = [mg.DEFAULT_MODELS.get(p, "")() for p in providers]
    prompt = "What is 2+2? Answer with a JSON object: {answer: number}."

    result = parallel_complete(providers, models, prompt)
    print(json.dumps(result, indent=2))
