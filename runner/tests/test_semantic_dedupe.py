#!/usr/bin/env python3
"""
Tests for semantic_dedupe.py — offline, no network.

Uses an injected deterministic embedder so tests run without real embedding models.
"""
import os, sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from semantic_dedupe import find_duplicates, dedupe_queued, _cosine, _task_text


# ── Helpers ──────────────────────────────────────────────────────────────────

def _fake_embedder_identity(texts):
    """Each text gets a unique-ish vector based on hash, length 8."""
    vecs = []
    for t in texts:
        h = hash(t) % (10**8)
        vecs.append([(h >> i & 0xF) / 15.0 for i in range(8)])
    return vecs


def _fake_embedder_identical(texts):
    """All texts get the exact same vector → cosine = 1.0."""
    return [[1.0, 0.0, 0.5, 0.3]] * len(texts)


def _fake_embedder_near_identical(texts):
    """First two texts get nearly identical vectors, rest get distinct ones."""
    vecs = []
    for i, t in enumerate(texts):
        if i == 0:
            vecs.append([0.9, 0.1, 0.3, 0.5])
        elif i == 1:
            vecs.append([0.89, 0.11, 0.31, 0.49])  # very close to [0]
        else:
            vecs.append([float(i) / 10, 0.5, 0.1 * i, 0.2])
    return vecs


def _make_task(slug, prompt="do something", title=None, created_at=None):
    return {
        "slug": slug,
        "prompt": prompt,
        "title": title or slug,
        "created_at": created_at or "2026-01-01T00:00:00Z",
    }


# ── _cosine tests ────────────────────────────────────────────────────────────

def test_cosine_identical_vectors():
    assert _cosine([1, 0, 0], [1, 0, 0]) == 1.0


def test_cosine_orthogonal_vectors():
    assert _cosine([1, 0], [0, 1]) == 0.0


def test_cosine_zero_vector():
    assert _cosine([0, 0, 0], [1, 2, 3]) == 0.0


def test_cosine_parallel_different_magnitude():
    sim = _cosine([2, 4, 6], [1, 2, 3])
    assert abs(sim - 1.0) < 1e-9


# ── _task_text tests ─────────────────────────────────────────────────────────

def test_task_text_combines_slug_title_prompt():
    t = _make_task("fix-login", prompt="Fix the login bug", title="Login Fix")
    text = _task_text(t)
    assert "fix-login" in text
    assert "Login Fix" in text
    assert "Fix the login bug" in text


def test_task_text_handles_missing_fields():
    t = {"slug": "only-slug"}
    text = _task_text(t)
    assert "only-slug" in text


def test_task_text_truncates_long_prompts():
    t = _make_task("s", prompt="x" * 1000)
    text = _task_text(t)
    assert len(text) < 1600  # slug + title + truncated prompt


# ── find_duplicates tests ────────────────────────────────────────────────────

def test_find_duplicates_empty_list():
    assert find_duplicates([], _fake_embedder_identity) == []


def test_find_duplicates_single_task():
    tasks = [_make_task("only-one")]
    assert find_duplicates(tasks, _fake_embedder_identity) == []


def test_find_duplicates_identical_embeddings_collapsed():
    """Two tasks with identical embeddings should be detected as duplicates."""
    tasks = [
        _make_task("task-a", prompt="Deploy new feature"),
        _make_task("task-b", prompt="Deploy new feature"),
    ]
    dupes = find_duplicates(tasks, _fake_embedder_identical, threshold=0.99)
    assert len(dupes) == 1
    keeper, dup, sim = dupes[0]
    assert keeper["slug"] == "task-a"
    assert dup["slug"] == "task-b"
    assert sim >= 0.99


def test_find_duplicates_near_identical_caught():
    """Near-identical tasks (first two) should be collapsed."""
    tasks = [
        _make_task("fix-auth-v1", prompt="Fix authentication flow"),
        _make_task("fix-auth-v2", prompt="Fix the authentication flow"),
        _make_task("add-logging", prompt="Add structured logging to API"),
    ]
    dupes = find_duplicates(tasks, _fake_embedder_near_identical, threshold=0.90)
    assert len(dupes) == 1
    assert dupes[0][1]["slug"] == "fix-auth-v2"  # second is the duplicate


def test_find_duplicates_unrelated_not_collapsed():
    """Unrelated tasks should not be deduplicated."""
    tasks = [
        _make_task("deploy-frontend", prompt="Deploy React frontend to Vercel"),
        _make_task("fix-db-migration", prompt="Fix broken Prisma migration"),
        _make_task("add-rate-limit", prompt="Add rate limiting to API endpoints"),
    ]
    dupes = find_duplicates(tasks, _fake_embedder_identity, threshold=0.92)
    assert len(dupes) == 0


def test_find_duplicates_greedy_one_match():
    """A task appears as duplicate at most once (greedy first-match)."""
    tasks = [
        _make_task("a", prompt="same"),
        _make_task("b", prompt="same"),
        _make_task("c", prompt="same"),
    ]
    dupes = find_duplicates(tasks, _fake_embedder_identical, threshold=0.90)
    # b matches a → removed. c matches a → also removed. Two pairs.
    assert len(dupes) == 2
    dup_slugs = {d[1]["slug"] for d in dupes}
    assert "a" not in dup_slugs  # a is always the keeper


def test_find_duplicates_respects_threshold():
    """Higher threshold means fewer matches."""
    tasks = [
        _make_task("x", prompt="test"),
        _make_task("y", prompt="test"),
    ]
    # With threshold=1.0, near-identical but not exact should not match
    dupes_strict = find_duplicates(tasks, _fake_embedder_near_identical, threshold=1.0)
    assert len(dupes_strict) == 0


# ── dedupe_queued tests ──────────────────────────────────────────────────────

def test_dedupe_queued_dry_run():
    """Without mark_fn, duplicates are found but not acted on."""
    tasks = [
        _make_task("a", prompt="deploy"),
        _make_task("b", prompt="deploy"),
    ]
    count = dedupe_queued(tasks, _fake_embedder_identical, threshold=0.90)
    assert count == 1


def test_dedupe_queued_calls_mark_fn():
    """mark_fn is called for each duplicate found."""
    marked = []
    def recorder(keeper, dup, sim):
        marked.append((keeper["slug"], dup["slug"], sim))

    tasks = [
        _make_task("keep-me", prompt="original"),
        _make_task("dupe-me", prompt="original"),
    ]
    count = dedupe_queued(tasks, _fake_embedder_identical, threshold=0.90, mark_fn=recorder)
    assert count == 1
    assert len(marked) == 1
    assert marked[0][0] == "keep-me"
    assert marked[0][1] == "dupe-me"


def test_dedupe_queued_no_duplicates():
    """Distinct tasks produce zero duplicates."""
    tasks = [
        _make_task("alpha", prompt="Build authentication system"),
        _make_task("beta", prompt="Fix database connection pooling"),
    ]
    count = dedupe_queued(tasks, _fake_embedder_identity, threshold=0.92)
    assert count == 0
