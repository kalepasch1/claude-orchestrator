import json

import release_train


def test_prepare_generated_types_runs_nuxt_prepare(monkeypatch, tmp_path):
    (tmp_path / "package.json").write_text(json.dumps({"dependencies": {"nuxt": "3"}}))
    (tmp_path / "tsconfig.json").write_text('{"extends":"./.nuxt/tsconfig.json"}')

    class Result:
        returncode = 0
        stdout = "prepared"
        stderr = ""

    def run(*args, **kwargs):
        generated = tmp_path / ".nuxt"
        generated.mkdir()
        (generated / "tsconfig.json").write_text("{}")
        return Result()

    monkeypatch.setattr(release_train.subprocess, "run", run)
    ok, log = release_train._prepare_generated_types(str(tmp_path))
    assert ok
    assert "prepared" in log
