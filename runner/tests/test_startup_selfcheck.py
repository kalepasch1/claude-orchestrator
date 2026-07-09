#!/usr/bin/env python3
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import startup_selfcheck


class AcceptTrustTest(unittest.TestCase):

    def _cfg_path(self, d):
        return os.path.join(d, ".claude.json")

    def test_sets_hasTrustDialogAccepted_when_missing(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = self._cfg_path(d)
            with patch.object(startup_selfcheck, "_CLAUDE_CFG", cfg):
                changed = startup_selfcheck._accept_trust("/some/repo")
            self.assertTrue(changed)
            data = json.loads(open(cfg).read())
            self.assertTrue(data["projects"]["/some/repo"]["hasTrustDialogAccepted"])

    def test_no_write_when_already_accepted(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = self._cfg_path(d)
            initial = {"projects": {"/some/repo": {"hasTrustDialogAccepted": True}}}
            with open(cfg, "w") as f:
                json.dump(initial, f)
            mtime_before = os.path.getmtime(cfg)
            with patch.object(startup_selfcheck, "_CLAUDE_CFG", cfg):
                changed = startup_selfcheck._accept_trust("/some/repo")
            self.assertFalse(changed)
            self.assertEqual(os.path.getmtime(cfg), mtime_before)

    def test_merges_into_existing_projects(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = self._cfg_path(d)
            initial = {"projects": {"/other/repo": {"hasTrustDialogAccepted": True}}}
            with open(cfg, "w") as f:
                json.dump(initial, f)
            with patch.object(startup_selfcheck, "_CLAUDE_CFG", cfg):
                startup_selfcheck._accept_trust("/new/repo")
            data = json.loads(open(cfg).read())
            self.assertTrue(data["projects"]["/other/repo"]["hasTrustDialogAccepted"])
            self.assertTrue(data["projects"]["/new/repo"]["hasTrustDialogAccepted"])

    def test_survives_missing_cfg_file(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = os.path.join(d, "nonexistent", ".claude.json")
            with patch.object(startup_selfcheck, "_CLAUDE_CFG", cfg):
                # Should not raise — fail-soft
                try:
                    startup_selfcheck._accept_trust("/some/repo")
                except Exception as e:
                    self.fail(f"_accept_trust raised unexpectedly: {e}")

    def test_survives_corrupt_cfg(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = self._cfg_path(d)
            with open(cfg, "w") as f:
                f.write("not json {{{")
            with patch.object(startup_selfcheck, "_CLAUDE_CFG", cfg):
                try:
                    startup_selfcheck._accept_trust("/some/repo")
                except Exception as e:
                    self.fail(f"_accept_trust raised unexpectedly: {e}")


if __name__ == "__main__":
    unittest.main()
