# merge-legacy-agent-ce2-batch-1783860886-recovered

## Decision: Do Not Merge — Obsolete

The legacy branch `agent/ce2-batch-1783860886-recovered` is heavily diverged from
master (844 files changed, 7,343 insertions vs 60,197 deletions). The branch
predates significant master evolution and its changes are either:

- Already superseded by newer work on master
- Deletions of the web/ directory structure that has since been rebuilt
- Stale runner/ features that have been reimplemented

Merging would regress the codebase. The branch is preserved for historical
reference but should not be integrated.

## Branch preserved at
`origin/agent/ce2-batch-1783860886-recovered`
