import json

import fleet_deploy_doctor as doctor


def _target(tmp_path):
    return {
        "app": "pasch",
        "repo_path": str(tmp_path),
        "github_repo": "kalepasch1/pasch",
        "branch": "main",
        "vercel_project": "kale-pasch",
        "supabase_project_ref": "ref123",
    }


def test_local_binding_accepts_exact_links(tmp_path, monkeypatch):
    (tmp_path / ".vercel").mkdir()
    (tmp_path / ".vercel" / "project.json").write_text(json.dumps({"projectName": "kale-pasch"}))
    (tmp_path / "supabase" / ".temp").mkdir(parents=True)
    (tmp_path / "supabase" / ".temp" / "project-ref").write_text("ref123")
    monkeypatch.setattr(doctor, "_git", lambda *_: "https://github.com/kalepasch1/pasch.git")
    assert doctor.check_local_binding(_target(tmp_path)) == []


def test_local_binding_rejects_credentialed_remote_and_wrong_projects(tmp_path, monkeypatch):
    (tmp_path / ".vercel").mkdir()
    (tmp_path / ".vercel" / "project.json").write_text(json.dumps({"projectName": "pasch"}))
    monkeypatch.setattr(
        doctor, "_git", lambda *_: "https://user:token@github.com/kalepasch1/pasch.git"
    )
    issues = doctor.check_local_binding(_target(tmp_path))
    assert any("embeds credentials" in issue for issue in issues)
    assert any("local Vercel link is pasch" in issue for issue in issues)
    assert any("local Supabase link is missing" in issue for issue in issues)
