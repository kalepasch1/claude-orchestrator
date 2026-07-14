import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_web_only_auto_deploys_production_branch():
    config = json.loads((ROOT / "web" / "vercel.json").read_text())
    assert config["git"]["deploymentEnabled"] == {"*": False, "master": True}
    assert config["ignoreCommand"] == "git diff --quiet HEAD^ HEAD -- . ../packages/darwin-kernel"


def test_release_defaults_batch_builds():
    config = json.loads((ROOT / "scripts" / "fleet_config_baseline.json").read_text())
    assert config["ORCH_PUSH_ON_MERGE"] == "false"
    assert int(config["RELEASE_MIN_BATCH"]) >= 10
    assert float(config["RELEASE_INTERVAL_HOURS"]) >= 6


def test_cowork_executor_cannot_launch_vercel_builds():
    skill = (ROOT / "runner" / "cowork_executor" / "SKILL.md").read_text()
    forbidden = "npx " + "vercel@latest deploy"
    assert forbidden not in skill
    assert "RELEASE QUEUE ONLY" in skill


def test_cloud_runner_cannot_push_every_merge_to_production():
    service = (ROOT / "deploy" / "runner.service").read_text()
    assert "Environment=ORCH_PUSH_ON_MERGE=false" in service
    assert "Environment=RELEASE_MIN_BATCH=10" in service
    assert "Environment=RELEASE_INTERVAL_HOURS=6" in service
