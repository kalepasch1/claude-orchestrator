"""A worktree records the slug it serves, so the reconciler never has to guess it.

On 2026-08-23 tools/reconcile_worktree_evidence.py classified three dirty worktrees as
RECOVERABLE_VALUE while all three were owned by RUNNING tasks. `madeus-group-3` is the
case that proves path-guessing cannot work: it serves the slug
`dropbox-beethoven-madeus-web-multi-tenant-claude-preneur-platform-bi-group-3`, which
shares no prefix, no suffix and no token boundary with the directory name.
"""
import json
import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "runner"))

import worktree_identity as wi  # noqa: E402

MADEUS_SLUG = "dropbox-beethoven-madeus-web-multi-tenant-claude-preneur-platform-bi-group-3"


class TestRecordAndRead:
    def test_round_trips_the_slug(self, tmp_path):
        assert wi.record(str(tmp_path), "my-slug", "task-1", "agent/my-slug") is True
        assert wi.slug_for(str(tmp_path)) == "my-slug"
        assert wi.branch_for(str(tmp_path)) == "agent/my-slug"
        assert wi.task_id_for(str(tmp_path)) == "task-1"

    def test_defaults_the_branch_from_the_slug(self, tmp_path):
        wi.record(str(tmp_path), "my-slug")
        assert wi.branch_for(str(tmp_path)) == "agent/my-slug"

    def test_records_a_schema_tag(self, tmp_path):
        wi.record(str(tmp_path), "my-slug")
        with open(os.path.join(str(tmp_path), wi.IDENTITY_FILE)) as fh:
            assert json.load(fh)["schema"] == wi.SCHEMA

    def test_the_identity_file_is_a_dotfile(self):
        """A non-dotfile would make every worktree permanently dirty evidence."""
        assert wi.IDENTITY_FILE.startswith(".")

    def test_never_stores_the_lease_token(self, tmp_path):
        """The file lives in an agent-writable directory; a token is a credential."""
        wi.record(str(tmp_path), "my-slug", "task-1", "agent/my-slug", lease_token_present=True)
        raw = open(os.path.join(str(tmp_path), wi.IDENTITY_FILE)).read()
        assert "leased" in raw
        assert "lease_token" not in raw

    def test_rewrite_replaces_rather_than_appends(self, tmp_path):
        wi.record(str(tmp_path), "first")
        wi.record(str(tmp_path), "second")
        assert wi.slug_for(str(tmp_path)) == "second"

    def test_leaves_no_temp_files_behind(self, tmp_path):
        wi.record(str(tmp_path), "my-slug")
        leftovers = [n for n in os.listdir(str(tmp_path)) if n.endswith(".tmp")]
        assert leftovers == []


class TestFailSoft:
    @pytest.mark.parametrize("path", [None, "", 7, []])
    def test_record_returns_false_on_a_bad_path(self, path):
        assert wi.record(path, "slug") is False

    def test_record_returns_false_without_a_slug(self, tmp_path):
        assert wi.record(str(tmp_path), "") is False

    @pytest.mark.parametrize("path", [None, "", "/nonexistent/xyz"])
    def test_read_returns_empty_on_a_bad_path(self, path):
        assert wi.read(path) == {}
        assert wi.slug_for(path) == ""

    def test_malformed_identity_reads_as_unknown(self, tmp_path):
        with open(os.path.join(str(tmp_path), wi.IDENTITY_FILE), "w") as fh:
            fh.write("{not json")
        assert wi.read(str(tmp_path)) == {}
        assert wi.slug_for(str(tmp_path)) == ""

    def test_non_object_identity_reads_as_unknown(self, tmp_path):
        with open(os.path.join(str(tmp_path), wi.IDENTITY_FILE), "w") as fh:
            json.dump(["not", "a", "dict"], fh)
        assert wi.read(str(tmp_path)) == {}

    def test_non_string_slug_reads_as_unknown(self, tmp_path):
        with open(os.path.join(str(tmp_path), wi.IDENTITY_FILE), "w") as fh:
            json.dump({"slug": 42}, fh)
        assert wi.slug_for(str(tmp_path)) == ""


class TestResolveSlug:
    def test_recorded_beats_the_directory_name(self, tmp_path):
        """The madeus-group-3 case: directory name and slug are unrelated."""
        wt = tmp_path / "madeus-group-3"
        wt.mkdir()
        wi.record(str(wt), MADEUS_SLUG, "task-9")
        assert wi.resolve_slug(str(wt)) == (MADEUS_SLUG, "recorded")

    def test_falls_back_to_the_directory_name_for_a_pre_existing_worktree(self, tmp_path):
        wt = tmp_path / "some-slug"
        wt.mkdir()
        assert wi.resolve_slug(str(wt)) == ("some-slug", "dirname")

    def test_reports_the_source_so_a_guess_is_never_mistaken_for_proof(self, tmp_path):
        wt = tmp_path / "some-slug"
        wt.mkdir()
        _, source = wi.resolve_slug(str(wt))
        assert source == "dirname"

    @pytest.mark.parametrize("path", [None, "", 7])
    def test_unknowable_path_resolves_to_nothing(self, path):
        assert wi.resolve_slug(path) == ("", "")

    def test_trailing_slash_does_not_produce_an_empty_name(self, tmp_path):
        wt = tmp_path / "some-slug"
        wt.mkdir()
        assert wi.resolve_slug(str(wt) + os.sep) == ("some-slug", "dirname")


class TestReconcilerWiring:
    def test_the_reconciler_carries_slug_and_provenance_on_every_item(self, tmp_path):
        sys.path.insert(0, os.path.join(REPO, "tools"))
        import reconcile_worktree_evidence as rwe

        wt = tmp_path / "madeus-group-3"
        wt.mkdir()
        wi.record(str(wt), MADEUS_SLUG, "task-9")

        item = rwe.Item(ref=str(wt))
        rwe.classify_worktree(item, str(wt), "", "", "origin/master", REPO, set())
        assert item.owner_slug == MADEUS_SLUG
        assert item.owner_slug_source == "recorded"

    def test_an_unrecorded_worktree_is_marked_as_a_guess(self, tmp_path):
        sys.path.insert(0, os.path.join(REPO, "tools"))
        import reconcile_worktree_evidence as rwe

        wt = tmp_path / "plain-slug"
        wt.mkdir()
        item = rwe.Item(ref=str(wt))
        rwe.classify_worktree(item, str(wt), "", "", "origin/master", REPO, set())
        assert item.owner_slug == "plain-slug"
        assert item.owner_slug_source == "dirname"

    def test_a_missing_directory_still_produces_an_item(self, tmp_path):
        """Fail-soft contract: unreachable identity must not stop a ledger."""
        sys.path.insert(0, os.path.join(REPO, "tools"))
        import reconcile_worktree_evidence as rwe

        missing = str(tmp_path / "gone")
        item = rwe.Item(ref=missing)
        rwe.classify_worktree(item, missing, "", "", "origin/master", REPO, set())
        assert item.classification != "UNKNOWN"
        assert item.owner_slug == "gone"


class TestSetupWorktreesWiring:
    def test_setup_worktrees_records_the_identity(self):
        script = os.path.join(REPO, "runner", "setup-worktrees.sh")
        body = open(script, encoding="utf-8").read()
        assert "worktree_identity.py" in body
        assert "record" in body
        # Best-effort: bookkeeping must never fail worktree creation.
        assert "|| true" in body.split("worktree_identity.py")[1].split("\n")[0]
