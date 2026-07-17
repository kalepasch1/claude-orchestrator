# Historical Merged Tasks: Review and Deduplication Guide

## Overview
When reviewing legacy tasks for merging, follow this process to avoid
duplication with current active work.

## Review Steps
1. Query the task queue for tasks with state MERGED or DONE sharing
   the same project_id and similar slugs.
2. Compare the prompt and acceptance criteria of the historical task
   against any currently QUEUED or RUNNING tasks.
3. If a near-duplicate exists, mark the newer task with a dedup note
   referencing the original merged task slug.
4. Only proceed with merge if no active duplicate is found.

## Deduplication Criteria
- Slug similarity above 0.8 threshold
- Matching project_id and overlapping prompt intent
- Same target files or modules affected

## Notes
This guide does not alter any code, dependencies, or product behavior.
It serves as onboarding documentation for the merge train operators.
