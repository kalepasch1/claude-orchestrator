PROJECT: apparently

- id: deployfix-vercel-ignore-agent-branches-apparently
  title: Skip Vercel builds for agent/recovery branches (vercel.json ignoreCommand)
  material: no
  model: haiku
  depends: []
  proof: `node -e "JSON.parse(require('fs').readFileSync('vercel.json'))"` exits 0
  prompt: |
    Add to vercel.json (create if absent, preserve all existing keys including crons):
    "ignoreCommand": "bash -c 'case \"$VERCEL_GIT_COMMIT_REF\" in agent/*|recover*|rework*) exit 0;; *) exit 1;; esac'"
    Reason: the orchestrator now pushes agent/* branches to origin (two-Mac branch-share fix);
    without this every agent branch push triggers a wasted Vercel preview build. Keep JSON valid.

PROJECT: smarter

- id: deployfix-vercel-ignore-agent-branches-smarter
  title: Skip Vercel builds for agent/recovery branches (vercel.json ignoreCommand)
  material: no
  model: haiku
  depends: []
  proof: `node -e "JSON.parse(require('fs').readFileSync('vercel.json'))"` exits 0
  prompt: |
    Add to vercel.json (create if absent, preserve all existing keys):
    "ignoreCommand": "bash -c 'case \"$VERCEL_GIT_COMMIT_REF\" in agent/*|recover*|rework*) exit 0;; *) exit 1;; esac'"
    Reason: the orchestrator now pushes agent/* branches to origin (two-Mac branch-share fix);
    without this every agent branch push triggers a wasted Vercel preview build. Keep JSON valid.

PROJECT: pareto-2080

- id: deployfix-vercel-ignore-agent-branches-pareto-2080
  title: Skip Vercel builds for agent/recovery branches (vercel.json ignoreCommand)
  material: no
  model: haiku
  depends: []
  proof: `node -e "JSON.parse(require('fs').readFileSync('vercel.json'))"` exits 0
  prompt: |
    Add to vercel.json (create if absent — NOTE this repo dual-registers crons in vercel.json,
    preserve them exactly):
    "ignoreCommand": "bash -c 'case \"$VERCEL_GIT_COMMIT_REF\" in agent/*|recover*|rework*) exit 0;; *) exit 1;; esac'"
    Reason: agent/* branches are now pushed to origin fleet-wide; skip their preview builds.
    Keep JSON valid and crons untouched.

PROJECT: santas-secret-workshop

- id: deployfix-vercel-ignore-agent-branches-santas-secret-workshop
  title: Skip Vercel builds for agent/recovery branches (vercel.json ignoreCommand)
  material: no
  model: haiku
  depends: []
  proof: `node -e "JSON.parse(require('fs').readFileSync('vercel.json'))"` exits 0
  prompt: |
    Add to vercel.json (create if absent, preserve existing keys):
    "ignoreCommand": "bash -c 'case \"$VERCEL_GIT_COMMIT_REF\" in agent/*|recover*|rework*) exit 0;; *) exit 1;; esac'"
    Reason: agent/* branches are now pushed to origin fleet-wide; skip their preview builds so the
    Expo-web Vercel project doesn't burn build slots. Keep JSON valid.

PROJECT: racefeed

- id: deployfix-vercel-ignore-agent-branches-racefeed
  title: Skip Vercel builds for agent/recovery branches (vercel.json ignoreCommand)
  material: no
  model: haiku
  depends: []
  proof: `node -e "JSON.parse(require('fs').readFileSync('vercel.json'))"` exits 0
  prompt: |
    Add to vercel.json (create if absent, preserve existing keys):
    "ignoreCommand": "bash -c 'case \"$VERCEL_GIT_COMMIT_REF\" in agent/*|recover*|rework*) exit 0;; *) exit 1;; esac'"
    Reason: agent/* branches are now pushed to origin fleet-wide; skip their preview builds.
    Keep JSON valid.
