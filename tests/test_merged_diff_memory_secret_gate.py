"""Merged-diff memory must not ingest credentials.

`adapt_diff` refuses to carry a secret across the *reuse* boundary, but that
gate ran after the fact: `record()` persisted the raw diff into `merged_diffs`,
and `find()` hands that stored diff straight back out to a different project's
prompt. A credential that never enters memory cannot leak out of it, so the
redaction belongs at the write boundary. These tests pin that.
"""
import os
import sys

import pytest

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runner")
)
import merged_diff_library as mdl  # noqa: E402


SECRET_LINE = '+API_KEY = "sk-abcdefghijklmnopqrstuvwxyz012345"'
CLEAN_LINE = "+def handler(request):"


def test_redact_secrets_replaces_only_the_offending_line():
    text = "\n".join([CLEAN_LINE, SECRET_LINE, "+    return 1"])
    out = mdl.redact_secrets(text)
    assert "sk-abcdefghijklmnopqrstuvwxyz012345" not in out
    assert "[redacted-secret]" in out
    assert CLEAN_LINE in out
    assert "+    return 1" in out


def test_redact_secrets_is_a_no_op_on_clean_text():
    text = "\n".join([CLEAN_LINE, "+    return 1"])
    assert mdl.redact_secrets(text) == text


@pytest.mark.parametrize("bad", [None, 123, b"bytes", {}])
def test_redact_secrets_is_fail_soft_on_bad_input(bad):
    assert mdl.redact_secrets(bad) == ""


def test_record_never_persists_a_secret(monkeypatch):
    """The row handed to the DB must be redacted, not the raw diff."""
    dirty = "\n".join(["diff --git a/app.py b/app.py", CLEAN_LINE, SECRET_LINE])
    monkeypatch.setattr(mdl, "_changed_files", lambda *a, **k: ["app.py"])
    monkeypatch.setattr(mdl, "_diff", lambda *a, **k: dirty)

    captured = {}

    def fake_insert(table, body, **kwargs):
        captured[table] = body
        return True

    monkeypatch.setattr(mdl.db, "insert", fake_insert)

    assert mdl.record("proj", "slug", "build", "ghp_aaaaaaaaaaaaaaaaaaaaaa now fix it",
                      "/repo", "base", "head") is True

    row = captured["merged_diffs"]
    assert "sk-abcdefghijklmnopqrstuvwxyz012345" not in row["diff"]
    assert "ghp_aaaaaaaaaaaaaaaaaaaaaa" not in row["prompt"]
    assert "[redacted-secret]" in row["diff"]
    # the structurally useful part of the diff survives redaction
    assert CLEAN_LINE in row["diff"]
    assert row["files"] == ["app.py"]
