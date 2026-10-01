"""post_posture_only must cover every repo that REQUIRES db-steering/posture.

kalepasch1/tomorrow requires the context too; when the stopgap posted for smarter alone,
every tomorrow PR sat BLOCKED from 2026-09-22 on with no status ever arriving."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import post_posture_only as ppo  # noqa: E402


def _env(monkeypatch, **kv):
    for k in ("POSTURE_ONLY_PROJECTS", "POSTURE_ONLY_PROJECT"):
        monkeypatch.delenv(k, raising=False)
    for k, v in kv.items():
        monkeypatch.setenv(k, v)


def test_default_covers_smarter_and_tomorrow(monkeypatch):
    _env(monkeypatch)
    assert ppo._projects() == ["smarter", "tomorrow"]


def test_plural_list_is_split_trimmed_and_deduplicated(monkeypatch):
    _env(monkeypatch, POSTURE_ONLY_PROJECTS=" smarter, tomorrow ,smarter,, ")
    assert ppo._projects() == ["smarter", "tomorrow"]


def test_singular_variable_still_honoured(monkeypatch):
    _env(monkeypatch, POSTURE_ONLY_PROJECT="smarter")
    assert ppo._projects() == ["smarter"]


def test_plural_wins_over_singular(monkeypatch):
    _env(monkeypatch, POSTURE_ONLY_PROJECT="smarter", POSTURE_ONLY_PROJECTS="tomorrow")
    assert ppo._projects() == ["tomorrow"]


def test_declines_above_load_ceiling_before_any_network(monkeypatch):
    _env(monkeypatch)
    monkeypatch.setattr(ppo, "_load1", lambda: ppo.LOAD_CEILING + 1)
    out = ppo.main()
    assert out["projects"] == ["smarter", "tomorrow"]
    assert "skipped" in out and "gate" not in out
