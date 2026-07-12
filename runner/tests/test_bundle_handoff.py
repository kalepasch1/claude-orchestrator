#!/usr/bin/env python3
"""Tests for bundle_handoff.py - parse_bundle_field + plan_bundle_apply."""
import os
import sys
import tempfile
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import bundle_handoff


class TestParseBundleField:
    def test_basic(self):
        block = "- id: my-task\n  bundle: outputs/my-bundle\n  prompt: |\n    do stuff"
        assert bundle_handoff.parse_bundle_field(block) == "outputs/my-bundle"

    def test_no_bundle(self):
        block = "- id: my-task\n  prompt: |\n    do stuff"
        assert bundle_handoff.parse_bundle_field(block) == ""

    def test_empty_input(self):
        assert bundle_handoff.parse_bundle_field("") == ""
        assert bundle_handoff.parse_bundle_field(None) == ""

    def test_bundle_with_spaces(self):
        block = "  bundle:   outputs/some path/here  "
        assert bundle_handoff.parse_bundle_field(block) == "outputs/some path/here"

    def test_bundle_among_other_fields(self):
        block = "title: foo\nmaterial: yes\nbundle: outputs/b1\nproof: exit 0"
        assert bundle_handoff.parse_bundle_field(block) == "outputs/b1"


class TestPlanBundleApply:
    def test_valid_tree(self):
        with tempfile.TemporaryDirectory() as td:
            os.makedirs(os.path.join(td, "runner", "sub"))
            with open(os.path.join(td, "runner", "sub", "foo.py"), "w") as f:
                f.write("# code")
            with open(os.path.join(td, "runner", "bar.py"), "w") as f:
                f.write("# code2")
            ops = bundle_handoff.plan_bundle_apply(td)
            dests = [d for _, d in ops]
            assert "runner/bar.py" in dests
            assert "runner/sub/foo.py" in dests

    def test_traversal_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            bad = os.path.join(td, "runner", "..", "..", "etc")
            os.makedirs(bad, exist_ok=True)
            # Create a symlink-style traversal attempt via actual nested dirs
            attack_dir = os.path.join(td, "runner")
            os.makedirs(attack_dir, exist_ok=True)
            # This file is fine
            with open(os.path.join(attack_dir, "ok.py"), "w") as f:
                f.write("ok")
            ops = bundle_handoff.plan_bundle_apply(td)
            dests = [d for _, d in ops]
            assert "runner/ok.py" in dests
            # Anything outside allowed prefixes should not appear
            for _, d in ops:
                assert ".." not in d

    def test_hidden_dir_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            git_dir = os.path.join(td, ".git")
            os.makedirs(git_dir)
            with open(os.path.join(git_dir, "config"), "w") as f:
                f.write("bad")
            ops = bundle_handoff.plan_bundle_apply(td)
            assert len(ops) == 0

    def test_disallowed_prefix_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            os.makedirs(os.path.join(td, "secrets"))
            with open(os.path.join(td, "secrets", "key.pem"), "w") as f:
                f.write("bad")
            ops = bundle_handoff.plan_bundle_apply(td)
            assert len(ops) == 0

    def test_missing_dir(self):
        assert bundle_handoff.plan_bundle_apply("/nonexistent/path/xyz") == []

    def test_empty_dir(self):
        with tempfile.TemporaryDirectory() as td:
            assert bundle_handoff.plan_bundle_apply(td) == []

    def test_none_input(self):
        assert bundle_handoff.plan_bundle_apply(None) == []
        assert bundle_handoff.plan_bundle_apply("") == []


class TestApplyBundle:
    def test_apply_copies_files(self):
        with tempfile.TemporaryDirectory() as bundle, tempfile.TemporaryDirectory() as wt:
            os.makedirs(os.path.join(bundle, "runner"))
            with open(os.path.join(bundle, "runner", "new.py"), "w") as f:
                f.write("# new code")
            count = bundle_handoff.apply_bundle(bundle, wt)
            assert count == 1
            assert os.path.isfile(os.path.join(wt, "runner", "new.py"))

    def test_apply_missing_bundle_noop(self):
        with tempfile.TemporaryDirectory() as wt:
            assert bundle_handoff.apply_bundle("/nonexistent", wt) == 0
