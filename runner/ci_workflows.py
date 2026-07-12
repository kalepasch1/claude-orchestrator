#!/usr/bin/env python3
"""
ci_workflows.py — generate GitHub Actions workflow templates for agentic CI execution.

Produces .github/workflows/orch-agent.yml (or per-repo variants) that:
  - Trigger on repository_dispatch with type 'orch-agent-task'
  - Checkout, install, run a headless agentic coder with the slug+prompt payload
  - Commit to agent/<slug> and push

The generated workflow reads ANTHROPIC_API_KEY (or equivalent) from repo secrets,
never from the dispatch payload.
"""
import os
import yaml


WORKFLOW_TEMPLATE = {
    "name": "Orchestrator Agent Task",
    "on": {
        "repository_dispatch": {
            "types": ["orch-agent-task"]
        }
    },
    "concurrency": {
        "group": "orch-agent-${{ github.event.client_payload.slug }}",
        "cancel-in-progress": False,
    },
    "jobs": {
        "agent": {
            "runs-on": "ubuntu-latest",
            "timeout-minutes": 30,
            "env": {
                "PYTHONPATH": "runner/",
                "ANTHROPIC_API_KEY": "${{ secrets.ANTHROPIC_API_KEY }}",
            },
            "steps": [
                {"uses": "actions/checkout@v4"},
                {"name": "Set up Python", "uses": "actions/setup-python@v5",
                 "with": {"python-version": "3.11"}},
                {"name": "Install deps", "run": "pip install pytest"},
                {"name": "Create agent branch",
                 "run": "git checkout -b agent/${{ github.event.client_payload.slug }}"},
                {"name": "Run agentic task",
                 "run": ("echo \"Slug: ${{ github.event.client_payload.slug }}\"\n"
                         "echo \"Prompt: ${{ github.event.client_payload.prompt }}\"\n"
                         "# Headless coder execution placeholder\n"
                         "python3 -c \"print('agent task complete')\"")},
                {"name": "Commit and push",
                 "run": ("git config user.name 'orch-agent'\n"
                         "git config user.email 'orch-agent@noreply'\n"
                         "git add -A\n"
                         "git diff --cached --quiet || git commit -m "
                         "'agent/${{ github.event.client_payload.slug }}'\n"
                         "git push origin agent/${{ github.event.client_payload.slug }}")},
            ],
        }
    },
}


def generate(repo_path=None):
    """Return the orch-agent workflow YAML string."""
    return yaml.dump(WORKFLOW_TEMPLATE, default_flow_style=False, sort_keys=False)


def write_workflow(repo_path):
    """Write orch-agent.yml into <repo>/.github/workflows/."""
    dest = os.path.join(repo_path, ".github", "workflows", "orch-agent.yml")
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "w") as f:
        f.write(generate(repo_path))
    return dest


if __name__ == "__main__":
    print(generate())
