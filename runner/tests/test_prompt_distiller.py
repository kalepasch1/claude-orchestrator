"""Tests for prompt_distiller.py"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from prompt_distiller import (
    compress_prompt, estimate_tokens, extract_core_spec,
    distill_batch, MergedOutcome, DistilledPattern, DistillationReport,
)


def test_compress_strips_agentic_repair():
    raw = "Fix the bug.\n\nAGENTIC-REPAIR DIRECTIVE\nRepair category: rework\nOriginal task slug: foo\n\nDone."
    result = compress_prompt(raw)
    assert "AGENTIC-REPAIR" not in result
    assert "Fix the bug" in result


def test_compress_strips_preflight():
    raw = "Build X.\n\nPREFLIGHT DIRECTIVE\nA cheap preflight model thought this might not produce.\n\nEnd."
    result = compress_prompt(raw)
    assert "PREFLIGHT" not in result
    assert "Build X" in result


def test_compress_collapses_whitespace():
    raw = "A\n\n\n\n\nB"
    result = compress_prompt(raw)
    assert "\n\n\n" not in result


def test_estimate_tokens():
    assert estimate_tokens("hello world") > 0
    assert estimate_tokens("a" * 400) == 100


def test_extract_core_spec():
    prompt = "Create the widget.\n\nPRIOR ATTEMPT FAILED — foo\nbar"
    core = extract_core_spec(prompt)
    assert core == "Create the widget."
    assert "PRIOR ATTEMPT" not in core


def test_extract_core_spec_no_markers():
    prompt = "Just build the thing."
    assert extract_core_spec(prompt) == "Just build the thing."


def test_distill_batch_token_savings():
    outcomes = [
        MergedOutcome(
            task_id="t1", slug="slug-1",
            prompt="Build feature X.\n\nAGENTIC-REPAIR DIRECTIVE\nRepair category: rework\nblah blah blah long boilerplate text here",
            prompt_tokens=100, completion_tokens=200,
            merged_at="2026-07-13T00:00:00Z",
        ),
        MergedOutcome(
            task_id="t2", slug="slug-2",
            prompt="Fix bug Y.\n\nPREFLIGHT DIRECTIVE\nA cheap preflight model said no.\n\nAUTO-REMEDIATION DIRECTIVE\nRecover and fix.",
            prompt_tokens=80, completion_tokens=150,
            merged_at="2026-07-13T00:00:00Z",
        ),
    ]
    patterns, report = distill_batch(outcomes)

    assert report.total_prompts_processed == 2
    assert report.total_saving_pct > 0
    assert report.patterns_extracted >= 1
    assert len(patterns) >= 1
    assert all(p.pattern_id for p in patterns)


def test_distill_batch_deduplicates():
    same_prompt = "Build feature X."
    outcomes = [
        MergedOutcome(task_id="t1", slug="s1", prompt=same_prompt,
                      prompt_tokens=50, completion_tokens=100, merged_at="2026-07-13"),
        MergedOutcome(task_id="t2", slug="s2", prompt=same_prompt,
                      prompt_tokens=50, completion_tokens=100, merged_at="2026-07-13"),
    ]
    patterns, report = distill_batch(outcomes)
    assert len(patterns) == 1
    assert patterns[0].usage_count == 2
    assert "s1" in patterns[0].source_slugs
    assert "s2" in patterns[0].source_slugs
