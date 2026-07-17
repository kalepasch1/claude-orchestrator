# DB Module — Quick Reference

## Purpose
`runner/db.py` is the single Supabase/PostgreSQL gateway for the orchestrator.
All task queries, fleet config reads, event inserts, and control-plane
operations route through this module.

## Usage Pattern
```python
import db
rows = db.query("SELECT * FROM tasks WHERE state = %s", ("QUEUED",))
db.execute("UPDATE tasks SET state = %s WHERE id = %s", ("DONE", task_id))
```

## Connection Management
- Connection parameters come from environment variables (`DATABASE_URL` or
  individual `PGHOST`/`PGPORT`/`PGUSER`/`PGPASSWORD`/`PGDATABASE`).
- Connections are reused within a thread; the module handles reconnection on
  transient failures.

## Fail-Soft Principle
Query helpers swallow exceptions and return empty results rather than raising,
so a transient DB blip never wedges the runner loop. Callers that need strict
error handling should use the raw connection directly.

## Thread Safety
Each thread gets its own connection via thread-local storage, so concurrent
task threads do not share cursors.
