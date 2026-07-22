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


def test_nuxt_launcher_without_runtime_files_is_not_ready():
    with tempfile.TemporaryDirectory() as repo:
        with open(os.path.join(repo, "package.json"), "w", encoding="utf-8") as f:
            json.dump({"scripts": {"build": "nuxt build"}, "devDependencies": {"nuxt": "3.0.0"}}, f)
        os.makedirs(os.path.join(repo, "node_modules", ".bin"))
        with open(os.path.join(repo, "node_modules", ".bin", "nuxi"), "w", encoding="utf-8") as f:
            f.write("#!/bin/sh\n")
        assert dependency_prewarm._deps_ready_local(repo) is False
