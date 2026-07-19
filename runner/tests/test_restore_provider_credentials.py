import os
import stat

import pytest

import restore_provider_credentials as credentials


def test_restores_missing_key_without_returning_secret(tmp_path):
    env = tmp_path / ".env"
    env.write_text("XAI_API_KEY=active\n")
    backup = tmp_path / ".env.bak-new"
    backup.write_text("GROQ_API_KEY=secret-value\n")

    result = credentials.restore("GROQ_API_KEY", str(env))

    assert result == {"key": "GROQ_API_KEY", "status": "restored"}
    assert "secret-value" not in str(result)
    assert "GROQ_API_KEY=secret-value" in env.read_text()
    assert stat.S_IMODE(os.stat(env).st_mode) == 0o600


def test_does_not_overwrite_active_key(tmp_path):
    env = tmp_path / ".env"
    env.write_text("GROQ_API_KEY=current\n")
    (tmp_path / ".env.bak").write_text("GROQ_API_KEY=old\n")
    assert credentials.restore("GROQ_API_KEY", str(env))["status"] == "already-active"
    assert env.read_text() == "GROQ_API_KEY=current\n"


def test_rejects_arbitrary_environment_names(tmp_path):
    with pytest.raises(ValueError):
        credentials.restore("UNSAFE_KEY", str(tmp_path / ".env"))
