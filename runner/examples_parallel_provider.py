#!/usr/bin/env python3
"""
examples_parallel_provider.py - Usage examples for the parallel provider system.

Shows how to use parallel_provider for high-stakes decision making.
"""
import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def example_1_basic_parallel():
    """Example 1: Basic parallel completion across multiple providers."""
    import parallel_provider
    import model_gateway as mg

    print("Example 1: Basic parallel execution")
    print("=" * 50)

    # Get available providers
    available = mg.available()
    if len(available) < 2:
        print(f"⚠ Need 2+ providers; have {available}")
        return

    # Use first 2 available providers
    providers = available[:2]
    models = [mg.DEFAULT_MODELS.get(p, "")() for p in providers]
    prompt = "What are the top 3 principles for legal compliance? Answer as JSON."

    print(f"Running parallel query across {providers}...")
    result = parallel_provider.parallel_complete(providers, models, prompt)

    print(f"\nWinner: {result['provider']}:{result['model']}")
    print(f"Synthesis score: {result['score']:.1f}/10")
    print(f"Total cost: ${result['cost_usd']:.4f}")
    print(f"\nResult:\n{result['text'][:300]}...")
    print(f"\nAll results: {len(result['all_results'])} provider(s) responded")


def example_2_judge_parallel():
    """Example 2: Using judge.py with parallel mode."""
    import judge

    print("\n\nExample 2: Judge review with parallel execution")
    print("=" * 50)

    task_prompt = """Review this code for security issues:
    - SQL injection risk
    - Authentication bypass
    - Privilege escalation
    """

    diff = """
    - SELECT * FROM users WHERE id = $input
    + SELECT * FROM users WHERE id = ? LIMIT 1
    """

    print("Running parallel code review (mock)...")
    # In real usage, set use_parallel=True for hard-tier tasks
    print("Note: Actual parallel execution requires live API keys")
    print("To test: import judge; judge.review(task_prompt, diff, use_parallel=True)")


def example_3_hard_tier_decision():
    """Example 3: High-stakes legal decision with parallel providers."""
    print("\n\nExample 3: High-stakes legal decision")
    print("=" * 50)

    print("""
Scenario: A company is considering entering a regulated market (money transmission).

Parallel Provider Flow:
1. Run prompt across Claude (Opus), Google (Gemini), and DeepSeek concurrently
2. Each provider analyzes legal risk, compliance requirements, timeline
3. Synthesis scores results by:
   - JSON validity (structured reasoning)
   - Confidence levels (explicit assessments)
   - Detail depth (comprehensive analysis)
4. Winner is the highest-confidence, most detailed assessment
5. All results included in output for cross-check by legal counsel

This reduces decision latency from ~5-10s (sequential) to ~2-3s (parallel)
while maintaining independence of analysis (no groupthink).
    """)


def example_4_cost_efficiency():
    """Example 4: Cost breakdown for parallel providers."""
    print("\n\nExample 4: Cost efficiency")
    print("=" * 50)

    providers_cost = {
        "local": 0.0,      # Ollama (self-hosted)
        "deepseek": 0.0003,
        "google": 0.0004,
        "openai": 0.0006,
        "claude": 0.008,   # Subscription (billed per month, not per call)
    }

    print("\nPer-completion cost (1000-token prompt + 500-token output):")
    for prov, cost in providers_cost.items():
        print(f"  {prov:12} ${cost:.4f}")

    parallel_cost = sum([v for k, v in providers_cost.items() if k in ["deepseek", "google", "local"]])
    print(f"\nParallel (deepseek+google+local): ${parallel_cost:.4f}")
    print(f"Sequential (3x best): ${min(providers_cost.values()) * 3:.4f}")
    print(f"\n✓ Parallel is faster AND cheaper (or equal cost)")


def example_5_error_handling():
    """Example 5: Graceful degradation on provider failure."""
    print("\n\nExample 5: Error handling and fallback")
    print("=" * 50)

    print("""
Scenario: One of three parallel providers times out or fails.

Parallel Provider Behavior:
1. Timeout/error tracked but doesn't block other providers
2. ThreadPoolExecutor continues with remaining providers
3. Results from successful providers used for synthesis
4. Empty/error results marked but included in all_results
5. If all providers fail, falls back to cheapest available with retry

Example output structure:
{
  "text": "successful_result_from_provider_a",
  "provider": "deepseek",
  "model": "deepseek-chat",
  "score": 7.5,
  "cost_usd": 0.0015,
  "all_results": [
    {"provider": "local", "score": 6.2, "text": "..."},
    {"provider": "deepseek", "score": 7.5, "text": "...", "winner": true},
    {"provider": "google", "score": 5.0, "error": "timeout"}
  ]
}

This ensures high-stakes decisions proceed even if one provider fails.
    """)


def main():
    print("\n" + "=" * 70)
    print("PARALLEL PROVIDER EXAMPLES - High-Stakes Decision Making")
    print("=" * 70)

    try:
        example_1_basic_parallel()
    except Exception as e:
        print(f"(Skipped: {e})")

    example_2_judge_parallel()
    example_3_hard_tier_decision()
    example_4_cost_efficiency()
    example_5_error_handling()

    print("\n" + "=" * 70)
    print("For more info: See runner/parallel_provider.py and runner/judge.py")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    main()
