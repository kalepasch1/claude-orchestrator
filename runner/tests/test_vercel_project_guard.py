import json

import pytest

import vercel_project_guard as guard


def _link(tmp_path, **data):
    folder = tmp_path / ".vercel"
    folder.mkdir()
    (folder / "project.json").write_text(json.dumps(data))


def test_refuses_unlinked_directory(tmp_path):
    with pytest.raises(guard.VercelProjectGuardError, match="not linked"):
        guard.assert_linked_project(tmp_path, "pasch")


def test_refuses_mismatched_project(tmp_path):
    _link(tmp_path, projectId="prj_123", projectName="pasch", orgId="team_123")
    with pytest.raises(guard.VercelProjectGuardError, match="does not match"):
        guard.assert_linked_project(tmp_path, "smrter")


def test_accepts_explicit_project_name_or_id(tmp_path):
    _link(tmp_path, projectId="prj_123", projectName="pasch", orgId="team_123")
    assert guard.assert_linked_project(tmp_path, "pasch")["projectId"] == "prj_123"
    assert guard.assert_linked_project(tmp_path, "prj_123")["projectName"] == "pasch"
