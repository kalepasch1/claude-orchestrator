#!/usr/bin/env python3
"""Tests for social_gap_intake.py."""
import sys, os, tempfile, shutil
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import social_gap_intake


def test_slug_for_gap():
    gap = {"kind": "zero_posts", "app": "smarter", "account_id": "abc12345"}
    slug = social_gap_intake._slug_for_gap(gap)
    assert slug == "gap-zero_posts-smarter-abc12345"


def test_slug_for_gap_defaults():
    gap = {}
    slug = social_gap_intake._slug_for_gap(gap)
    assert slug == "gap-gap-unknown-0"


def test_format_intake():
    content = social_gap_intake.format_intake(
        project="smarter",
        slug="gap-zero-posts-app-1234",
        title="apply starter content scheme for app",
        material="no",
        model="haiku",
        depends=[],
        proof="`nuxt build` exits 0",
        prompt="Account 1234 in app has 0 posts. Apply the starter content scheme.",
    )
    assert "PROJECT: smarter" in content
    assert "id: gap-zero-posts-app-1234" in content
    assert "title: apply starter content scheme for app" in content
    assert "material: no" in content
    assert "model: haiku" in content
    assert "proof: `nuxt build` exits 0" in content
    assert "Account 1234 in app has 0 posts" in content


def test_draft_intake_writes_files():
    """Feed sample gap rows and assert well-formed intake markdown is written to proposed/."""
    tmpdir = tempfile.mkdtemp()
    orig_proposed = social_gap_intake.PROPOSED
    try:
        social_gap_intake.PROPOSED = os.path.join(tmpdir, "proposed")

        # Mock _existing_slugs to return empty
        orig_existing = social_gap_intake._existing_slugs
        social_gap_intake._existing_slugs = lambda project: set()

        gaps = [
            {"kind": "zero_posts", "app": "testapp", "account_id": "acc1",
             "detail": "No posts in 7 days"},
            {"kind": "drafts_stuck", "app": "testapp", "account_id": "acc2",
             "detail": "Drafts stuck"},
        ]
        written = social_gap_intake.draft_intake(gaps, project="testproject")
        assert len(written) == 2

        # Verify files exist and have correct format
        for path in written:
            assert os.path.isfile(path)
            with open(path) as f:
                content = f.read()
            assert "PROJECT: testproject" in content
            assert "id: gap-" in content
            assert "proof:" in content
            assert "prompt:" in content

        # Verify proposed/ was used, NOT intake/
        assert all("proposed" in p for p in written)

        social_gap_intake._existing_slugs = orig_existing
    finally:
        social_gap_intake.PROPOSED = orig_proposed
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_draft_intake_idempotent():
    """Duplicate gaps should not produce duplicate files."""
    tmpdir = tempfile.mkdtemp()
    orig_proposed = social_gap_intake.PROPOSED
    try:
        proposed_dir = os.path.join(tmpdir, "proposed")
        social_gap_intake.PROPOSED = proposed_dir
        orig_existing = social_gap_intake._existing_slugs
        social_gap_intake._existing_slugs = lambda project: set()

        gaps = [{"kind": "zero_posts", "app": "testapp", "account_id": "acc1"}]

        written1 = social_gap_intake.draft_intake(gaps, project="test")
        assert len(written1) == 1

        # Second call: let it see the proposed dir for dedup
        def _check_proposed_only(project):
            slugs = set()
            if os.path.isdir(proposed_dir):
                for fname in os.listdir(proposed_dir):
                    if fname.endswith(".md"):
                        slugs.add(fname.replace(".md", ""))
            return slugs
        social_gap_intake._existing_slugs = _check_proposed_only

        written2 = social_gap_intake.draft_intake(gaps, project="test")
        assert len(written2) == 0

        social_gap_intake._existing_slugs = orig_existing
    finally:
        social_gap_intake.PROPOSED = orig_proposed
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    test_slug_for_gap()
    test_slug_for_gap_defaults()
    test_format_intake()
    test_draft_intake_writes_files()
    test_draft_intake_idempotent()
    print("All social_gap_intake tests passed")
