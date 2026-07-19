import json
import os
import tempfile

import dependency_prewarm


def test_zero_dependency_package_is_ready_without_node_modules():
    with tempfile.TemporaryDirectory() as repo:
        with open(os.path.join(repo, "package.json"), "w", encoding="utf-8") as f:
            json.dump({"name": "leaf", "version": "1.0.0"}, f)
        assert dependency_prewarm._deps_ready_local(repo) is True


def test_declared_dependency_still_requires_node_modules():
    with tempfile.TemporaryDirectory() as repo:
        with open(os.path.join(repo, "package.json"), "w", encoding="utf-8") as f:
            json.dump({"dependencies": {"left-pad": "1.3.0"}}, f)
        assert dependency_prewarm._deps_ready_local(repo) is False
